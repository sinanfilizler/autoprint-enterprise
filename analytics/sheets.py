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
COSTS_SHEET = os.getenv("GOOGLE_SHEETS_COSTS_SHEET", "Costs")

# ── Sütun düzeni ────────────────────────────────────────────────────────────
QUEUE_COLUMNS = [
    "order_id", "order_item_id", "sku", "qty",
    "name", "name2", "name3", "name4", "name5",
    "name6", "name7", "name8", "name9", "name10",
    "year", "message", "font_option", "color_option",
    "gift_box", "item_price", "shipping_fee",
    "seller_name", "order_date", "is_manual", "added_at",
]

LOG_COLUMNS = QUEUE_COLUMNS + ["processed_at"]
COSTS_COLUMNS = ["sku", "cost"]


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
        self._costs = self._get_or_create_sheet(COSTS_SHEET, COSTS_COLUMNS)

        self._cache: dict = {}  # key → (timestamp, value)

    # ── Sheet yönetimi ───────────────────────────────────────────────────────

    def _get_or_create_sheet(
        self, name: str, columns: list[str]
    ) -> gspread.Worksheet:
        try:
            ws = self._spreadsheet.worksheet(name)
            self._migrate_headers(ws, columns)
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(
                title=name, rows=10000, cols=len(columns)
            )
            ws.append_row(columns, value_input_option="RAW")
        return ws

    def _migrate_headers(self, ws: gspread.Worksheet, expected: list[str]) -> None:
        """Header'ı expected ile tam sıra uyumlu hale getirir. Veri yoksa direkt yazar."""
        try:
            current = ws.row_values(1)
        except Exception:
            return

        # Sondaki boş hücreleri temizle
        while current and current[-1].strip() == "":
            current.pop()

        if current == expected:
            return  # Zaten doğru

        # Veri satırı var mı kontrol et
        try:
            row_count = len(ws.get_all_values())
        except Exception:
            row_count = 1

        if row_count <= 1:
            # Veri yok — header'ı direkt yaz
            if len(expected) > ws.col_count:
                ws.resize(cols=len(expected))
            ws.update([expected], "1:1")
        else:
            # Veri var — sadece eksik sütunları sona ekle (veriyi bozmamak için)
            missing = [c for c in expected if c not in current]
            if missing:
                new_header = current + missing
                if len(new_header) > ws.col_count:
                    ws.resize(cols=len(new_header))
                ws.update([new_header], "1:1")

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
            elif col == "gift_box":
                row.append("TRUE" if order.get("gift_box") else "FALSE")
            elif col == "qty":
                row.append(str(order.get("qty", 1)))
            elif col in ("item_price", "shipping_fee"):
                row.append(str(order.get(col, 0.0)))
            else:
                row.append(str(order.get(col, "")))
        return row

    def _sheet_to_dicts(self, ws: gspread.Worksheet, expected_headers: list[str] | None = None) -> list[dict]:
        records = ws.get_all_records(default_blank="")
        for r in records:
            if "qty" in r:
                try:
                    r["qty"] = int(r["qty"])
                except (ValueError, TypeError):
                    r["qty"] = 1
            if "is_manual" in r:
                r["is_manual"] = str(r["is_manual"]).upper() == "TRUE"
            if "gift_box" in r:
                r["gift_box"] = str(r["gift_box"]).upper() == "TRUE"
            if "item_price" in r:
                try:
                    r["item_price"] = float(r["item_price"])
                except (ValueError, TypeError):
                    r["item_price"] = 0.0
            if "shipping_fee" in r:
                try:
                    r["shipping_fee"] = float(r["shipping_fee"])
                except (ValueError, TypeError):
                    r["shipping_fee"] = 0.0
        return records

    def _get_sheet_columns(self, ws: gspread.Worksheet) -> list[str]:
        """Sheet'in gerçek başlık satırını döner (boş hücreler temizlenmiş)."""
        try:
            row = ws.row_values(1)
            return [c for c in row if c.strip()]
        except Exception:
            return []

    def _get_all_item_ids(self, ws: gspread.Worksheet) -> set[str]:
        """Bir sheet'teki tüm order_item_id'leri set olarak döner — hızlı duplicate kontrolü."""
        try:
            cols = self._get_sheet_columns(ws)
            col_idx = cols.index("order_item_id") + 1  # 1-indexed
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
        """Queue sheet'indeki tüm aktif siparişleri döner (2dk cache)."""
        cached = self._cache.get("queue")
        if cached and time.monotonic() - cached[0] < 120:
            return cached[1]
        result = self._sheet_to_dicts(self._queue)
        self._cache["queue"] = (time.monotonic(), result)
        return result

    def mark_processed(self, order_item_id: str) -> bool:
        """Tek siparişi Queue'dan Log'a taşır. Başarılıysa True döner."""
        result = self.mark_processed_batch([order_item_id])
        return result["moved"] == 1

    def mark_processed_batch(self, order_item_ids: list[str]) -> dict:
        """
        Birden fazla siparişi tek seferde Queue'dan Log'a taşır.
        Toplam 3 API çağrısı yapar (get + append_rows + delete).
        Döndürür: {"moved": int, "not_found": list[str]}
        """
        oids = {str(oid).strip() for oid in order_item_ids}
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1 read: tüm queue satırlarını çek (başlık dahil)
        all_rows = self._queue.get_all_values()
        if len(all_rows) <= 1:
            return {"moved": 0, "not_found": list(oids)}

        header = all_rows[0]
        data_rows = all_rows[1:]  # (row_index_in_sheet = i+2)

        # Gerçek header'daki order_item_id pozisyonu (migration sonrası değişmez ama güvenli)
        try:
            oid_col = header.index("order_item_id")
        except ValueError:
            oid_col = QUEUE_COLUMNS.index("order_item_id")

        log_rows_to_add = []
        sheet_rows_to_delete = []  # sheet satır numaraları (1-indexed, başlık=1)
        found_oids = set()

        for i, row in enumerate(data_rows):
            cell_val = row[oid_col].strip() if oid_col < len(row) else ""
            if cell_val in oids:
                # Queue satırını Log header uzunluğuna pad'le, sonuna processed_at ekle
                log_header = self._get_sheet_columns(self._log)
                target_len = len(log_header) if log_header else len(LOG_COLUMNS)
                padded = list(row) + [""] * max(0, target_len - 1 - len(row))
                # processed_at sütununu bul ve yaz
                try:
                    proc_col = log_header.index("processed_at") if log_header else target_len - 1
                except ValueError:
                    proc_col = target_len - 1
                while len(padded) <= proc_col:
                    padded.append("")
                padded[proc_col] = now
                log_rows_to_add.append(padded)
                sheet_rows_to_delete.append(i + 2)  # +1 header, +1 1-indexed
                found_oids.add(cell_val)

        if not log_rows_to_add:
            return {"moved": 0, "not_found": list(oids)}

        # 1 write: batch log append
        self._log.append_rows(log_rows_to_add, value_input_option="RAW")

        # 1 write: tüm silmeleri tek batch_update isteğine topla
        # Yüksek satırdan başla → düşük satıra git (index kayması önlemi)
        delete_requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": self._queue.id,
                        "dimension": "ROWS",
                        "startIndex": row_num - 1,  # 0-indexed
                        "endIndex": row_num,
                    }
                }
            }
            for row_num in sorted(sheet_rows_to_delete, reverse=True)
        ]
        self._spreadsheet.batch_update({"requests": delete_requests})

        self._cache.pop("queue", None)
        self._cache.pop("row_counts", None)

        return {
            "moved": len(found_oids),
            "not_found": list(oids - found_oids),
        }

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

    def backfill_log_fields(self, orders: list[dict], fields: list[str]) -> dict:
        """
        Log sheet'indeki mevcut satırları order_item_id eşleştirmesiyle günceller.
        Sadece belirtilen fields güncellenir. Illustrator'a göndermez.
        Döndürür: {"updated": int, "not_found": int}
        """
        all_rows = self._log.get_all_values()
        if len(all_rows) <= 1:
            return {"updated": 0, "not_found": len(orders)}

        header = all_rows[0]
        try:
            oid_col = header.index("order_item_id")
        except ValueError:
            return {"updated": 0, "not_found": len(orders)}

        # Güncellenecek sütun index'leri
        col_indices = {}
        for f in fields:
            try:
                col_indices[f] = header.index(f)
            except ValueError:
                pass

        if not col_indices:
            return {"updated": 0, "not_found": len(orders)}

        # order_item_id → satır numarası (1-indexed, başlık=1)
        row_map = {}
        for i, row in enumerate(all_rows[1:], start=2):
            oid = row[oid_col].strip() if oid_col < len(row) else ""
            if oid:
                row_map[oid] = (i, row)

        # Batch update hazırla
        updates = []
        updated, not_found = 0, 0
        for order in orders:
            oid = str(order.get("order_item_id", "")).strip()
            if oid not in row_map:
                not_found += 1
                continue
            row_num, row_data = row_map[oid]
            for field, col_idx in col_indices.items():
                val = order.get(field, "")
                if val and str(val) != str(row_data[col_idx] if col_idx < len(row_data) else ""):
                    col_letter = chr(ord('A') + col_idx)
                    updates.append({
                        "range": f"{col_letter}{row_num}",
                        "values": [[str(val)]],
                    })
            updated += 1

        if updates:
            self._log.batch_update(updates, value_input_option="RAW")
            self._cache.pop("log", None)

        return {"updated": updated, "not_found": not_found}

    def clear_log(self) -> int:
        """Log sheet'ini temizler (başlık satırı kalır). Silinen satır sayısını döner."""
        all_rows = self._log.get_all_values()
        count = max(0, len(all_rows) - 1)
        if count:
            self._log.delete_rows(2, len(all_rows))
            self._cache.pop("row_counts", None)
        return count

    def row_counts(self) -> dict[str, int]:
        """Queue ve Log sheet'lerindeki veri satırı sayılarını döner (5dk cache)."""
        cached = self._cache.get("row_counts")
        if cached and time.monotonic() - cached[0] < 300:
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

    # ── Costs API ────────────────────────────────────────────────────────────

    def get_costs(self) -> dict[str, float]:
        """Costs sheet'inden {sku: cost} dict döner (30s cache)."""
        cached = self._cache.get("costs")
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        records = self._costs.get_all_records(default_blank="")
        result = {}
        for r in records:
            sku = str(r.get("sku", "")).strip()
            if not sku:
                continue
            try:
                result[sku] = float(r.get("cost", 0.0))
            except (ValueError, TypeError):
                result[sku] = 0.0
        self._cache["costs"] = (time.monotonic(), result)
        return result

    def upsert_cost(self, sku: str, cost: float) -> None:
        """SKU için maliyet ekler veya günceller."""
        sku = sku.strip()
        all_rows = self._costs.get_all_values()
        sku_col = 1  # A sütunu (1-indexed)

        for i, row in enumerate(all_rows[1:], start=2):
            if row and row[0].strip() == sku:
                self._costs.update_cell(i, 2, str(cost))
                self._cache.pop("costs", None)
                return

        self._costs.append_row([sku, str(cost)], value_input_option="RAW")
        self._cache.pop("costs", None)
