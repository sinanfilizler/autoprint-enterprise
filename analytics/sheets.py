"""
analytics/sheets.py
===================
Google Sheets entegrasyonu — sipariş kuyruğu ve log yönetimi.

Sheets yapısı:
  Queue sheet : Aktif siparişler (henüz Illustrator'a gönderilmemiş)
  Log sheet   : İşlenmiş siparişler (arşiv)

Her iki sheet'te duplicate kontrolü order_item_id üzerinden yapılır.
"""

import os
import time
from datetime import datetime
from pathlib import Path

import gspread
from dotenv import load_dotenv
from gspread.exceptions import APIError, SpreadsheetNotFound

load_dotenv()

# ── Ortam değişkenleri ──────────────────────────────────────────────────────
CREDENTIALS_PATH = os.getenv(
    "GOOGLE_SHEETS_CREDENTIALS",
    str(Path(__file__).parent.parent / "credentials.json"),
)
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
QUEUE_SHEET = os.getenv("GOOGLE_SHEETS_QUEUE_SHEET", "Queue")
LOG_SHEET = os.getenv("GOOGLE_SHEETS_LOG_SHEET", "Log")

# ── Sütun düzeni ────────────────────────────────────────────────────────────
QUEUE_COLUMNS = [
    "order_id", "order_item_id", "sku", "qty",
    "name", "name2", "name3", "name4", "name5",
    "name6", "name7", "name8", "name9", "name10",
    "year", "message", "font_option", "color_option",
    "is_manual", "added_at",
]

LOG_COLUMNS = QUEUE_COLUMNS + ["processed_at"]


def _build_gspread_client() -> gspread.Client:
    # 1. Lokal: credentials.json varsa direkt kullan
    creds_path = Path(CREDENTIALS_PATH)
    if creds_path.exists():
        return gspread.service_account(filename=str(creds_path))

    # 2. Cloud: st.secrets["gcp_service_account"] dict'inden oluştur
    try:
        import streamlit as st
        creds_dict = dict(st.secrets["gcp_service_account"])
        return gspread.service_account_from_dict(creds_dict)
    except Exception as e:
        raise RuntimeError(
            f"Google credentials bulunamadı. "
            f"Lokal için credentials.json yerleştir. "
            f"Cloud için Streamlit Secrets'a [gcp_service_account] ekle. "
            f"Hata: {e}"
        )


def _get_spreadsheet_id() -> str:
    env_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    if env_id:
        return env_id
    try:
        import streamlit as st
        return st.secrets["GOOGLE_SHEETS_SPREADSHEET_ID"]
    except Exception:
        return ""


SPREADSHEET_ID = _get_spreadsheet_id()


class SheetsClient:
    def __init__(self):
        spreadsheet_id = SPREADSHEET_ID
        if not spreadsheet_id:
            raise ValueError("GOOGLE_SHEETS_SPREADSHEET_ID tanımlı değil (.env veya Streamlit Secrets)")

        gc = _build_gspread_client()
        try:
            self._spreadsheet = gc.open_by_key(spreadsheet_id)
        except SpreadsheetNotFound:
            raise SpreadsheetNotFound(f"Spreadsheet bulunamadı: {spreadsheet_id}")

        self._queue = self._get_or_create_sheet(QUEUE_SHEET, QUEUE_COLUMNS)
        self._log = self._get_or_create_sheet(LOG_SHEET, LOG_COLUMNS)

        self._cache: dict = {}  # key → (timestamp, value)

    # ── Sheet yönetimi ───────────────────────────────────────────────────────

    def _get_or_create_sheet(
        self, name: str, columns: list[str]
    ) -> gspread.Worksheet:
        try:
            ws = self._spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(
                title=name, rows=10000, cols=len(columns)
            )
            ws.append_row(columns, value_input_option="RAW")
        return ws

    # ── Yardımcı ─────────────────────────────────────────────────────────────

    def _order_to_row(self, order: dict, columns: list[str]) -> list:
        row = []
        for col in columns:
            if col == "added_at":
                row.append(order.get("added_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            elif col == "processed_at":
                row.append(order.get("processed_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            elif col == "is_manual":
                row.append("TRUE" if order.get("is_manual") else "FALSE")
            elif col == "qty":
                row.append(str(order.get("qty", 1)))
            else:
                row.append(str(order.get(col, "")))
        return row

    def _sheet_to_dicts(self, ws: gspread.Worksheet) -> list[dict]:
        records = ws.get_all_records(default_blank="")
        for r in records:
            if "qty" in r:
                try:
                    r["qty"] = int(r["qty"])
                except (ValueError, TypeError):
                    r["qty"] = 1
            if "is_manual" in r:
                r["is_manual"] = str(r["is_manual"]).upper() == "TRUE"
        return records

    def _get_all_item_ids(self, ws: gspread.Worksheet) -> set[str]:
        """Bir sheet'teki tüm order_item_id'leri set olarak döner — hızlı duplicate kontrolü."""
        try:
            col_idx = QUEUE_COLUMNS.index("order_item_id") + 1  # 1-indexed
            values = ws.col_values(col_idx)
            return {v.strip() for v in values[1:] if v.strip()}  # başlık satırını atla
        except (ValueError, APIError):
            return set()

    # ── Public API ───────────────────────────────────────────────────────────

    def is_duplicate(self, order_item_id: str) -> bool:
        """order_item_id Queue veya Log sheet'inde varsa True döner."""
        oid = str(order_item_id).strip()
        return (
            oid in self._get_all_item_ids(self._queue)
            or oid in self._get_all_item_ids(self._log)
        )

    def append_queue(self, orders: list[dict]) -> dict:
        """
        Siparişleri Queue sheet'ine ekler.
        Duplicate olanları (order_item_id) atlar.
        Döndürür: {"added": int, "skipped_duplicates": int, "skipped_ids": list}
        """
        existing_queue = self._get_all_item_ids(self._queue)
        existing_log = self._get_all_item_ids(self._log)
        existing = existing_queue | existing_log

        rows_to_add, skipped_ids = [], []
        for order in orders:
            oid = str(order.get("order_item_id", "")).strip()
            if oid in existing:
                skipped_ids.append(oid)
            else:
                rows_to_add.append(self._order_to_row(order, QUEUE_COLUMNS))
                existing.add(oid)

        if rows_to_add:
            self._queue.append_rows(rows_to_add, value_input_option="RAW")
            self._cache.pop("queue", None)
            self._cache.pop("row_counts", None)

        return {
            "added": len(rows_to_add),
            "skipped_duplicates": len(skipped_ids),
            "skipped_ids": skipped_ids,
        }

    def get_queue(self) -> list[dict]:
        """Queue sheet'indeki tüm aktif siparişleri döner (30s cache)."""
        cached = self._cache.get("queue")
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
        result = self._sheet_to_dicts(self._queue)
        self._cache["queue"] = (time.monotonic(), result)
        return result

    def mark_processed(self, order_item_id: str) -> bool:
        """
        Siparişi Queue'dan Log'a taşır.
        Başarılıysa True, bulunamazsa False döner.
        """
        oid = str(order_item_id).strip()

        # Queue'da satırı bul
        try:
            cell = self._queue.find(oid, in_column=QUEUE_COLUMNS.index("order_item_id") + 1)
        except Exception:
            return False
        if cell is None:
            return False

        row_data = self._queue.row_values(cell.row)

        # Log sütun sayısına göre processed_at ekle
        log_row = row_data + [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
        # Eksik sütunları boşlukla tamamla
        while len(log_row) < len(LOG_COLUMNS):
            log_row.append("")

        self._log.append_row(log_row, value_input_option="RAW")
        self._queue.delete_rows(cell.row)
        self._cache.pop("queue", None)
        self._cache.pop("row_counts", None)
        return True

    def remove_from_queue(self, order_item_id: str) -> bool:
        """Siparişi Queue'dan siler (Log'a taşımaz). Başarılıysa True döner."""
        oid = str(order_item_id).strip()
        try:
            cell = self._queue.find(oid, in_column=QUEUE_COLUMNS.index("order_item_id") + 1)
        except Exception:
            return False
        if cell is None:
            return False
        self._queue.delete_rows(cell.row)
        self._cache.pop("queue", None)
        self._cache.pop("row_counts", None)
        return True

    def get_log(self) -> list[dict]:
        """Log sheet'indeki tüm işlenmiş siparişleri döner."""
        return self._sheet_to_dicts(self._log)

    def row_counts(self) -> dict[str, int]:
        """Queue ve Log sheet'lerindeki veri satırı sayılarını döner (30s cache)."""
        cached = self._cache.get("row_counts")
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
        result = {
            "queue": max(0, len(self._queue.get_all_values()) - 1),
            "log": max(0, len(self._log.get_all_values()) - 1),
        }
        self._cache["row_counts"] = (time.monotonic(), result)
        return result

    def clear_queue(self) -> int:
        """Queue sheet'ini temizler (başlık satırı kalır). Silinen satır sayısını döner."""
        all_rows = self._queue.get_all_values()
        count = max(0, len(all_rows) - 1)
        if count:
            self._queue.delete_rows(2, len(all_rows))
            self._cache.pop("queue", None)
            self._cache.pop("row_counts", None)
        return count
