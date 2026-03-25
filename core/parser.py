import re
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup

FONT_MAP = {
    "monotype corsiva": "SERIF",
    "abel": "SANS",
    "elegant script": "SCRIPT",
    "welcome christmas": "WELCOME",
}

VALID_COLORS = {"BLACK", "WHITE", "GOLD", "RED", "SILVER", "IVORY"}
VALID_FONTS = {"SERIF", "SANS", "SCRIPT", "WELCOME"}


class ParseError(Exception):
    pass


class AmazonParser:
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        if not self.filepath.exists():
            raise FileNotFoundError(f"Dosya bulunamadı: {filepath}")

    def parse(self) -> tuple[list[dict], list[str]]:
        """
        (orders, warnings) döner.
        orders: başarıyla parse edilen sipariş listesi
        warnings: parse edilemeyen satırlar için mesajlar
        """
        suffix = self.filepath.suffix.lower()
        raw_text = self.filepath.read_text(encoding="utf-8", errors="replace")

        if suffix in (".html", ".htm"):
            return self._parse_html(raw_text)
        else:
            return self._parse_txt(raw_text)

    def _parse_html(self, raw_text: str) -> tuple[list[dict], list[str]]:
        soup = BeautifulSoup(raw_text, "lxml")
        orders, warnings = [], []

        # Amazon packing slip'te her sipariş satırı genellikle bir tablo satırında (<tr>) bulunur.
        # Sipariş ID'si sayfanın üst bölümünde yer alır.
        order_id = self._extract_order_id_html(soup)

        # Sipariş item satırlarını bul
        rows = self._find_item_rows(soup)

        if not rows:
            # Tek sipariş sayfası olarak dene
            try:
                order = self._parse_single_html(soup, order_id)
                orders.append(order)
            except ParseError as e:
                warnings.append(str(e))
            return orders, warnings

        for i, row in enumerate(rows):
            try:
                order = self._parse_row_html(row, soup, order_id)
                orders.append(order)
            except ParseError as e:
                warnings.append(f"Satır {i+1}: {e}")

        return orders, warnings

    def _extract_order_id_html(self, soup: BeautifulSoup) -> str:
        # "Order #" veya "Sipariş #" içeren text
        text = soup.get_text(" ")
        m = re.search(r"Order\s*#?\s*([0-9]{3}-[0-9]{7}-[0-9]{7})", text, re.IGNORECASE)
        if m:
            return m.group(1)
        # Daha geniş format
        m = re.search(r"([0-9]{3}-[0-9]+-[0-9]+)", text)
        return m.group(1) if m else ""

    def _find_item_rows(self, soup: BeautifulSoup) -> list:
        # Amazon packing slip'te "Merchant SKU" veya "ASIN" başlıklı sütun içeren tabloyu bul
        tables = soup.find_all("table")
        for table in tables:
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if any(h in headers for h in ["merchant sku", "sku", "asin", "quantity", "qty"]):
                return table.find_all("tr")[1:]  # başlık satırını atla
        return []

    def _parse_row_html(self, row, soup: BeautifulSoup, order_id: str) -> dict:
        cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
        if not cells:
            raise ParseError("Boş satır")

        # Sütun sırasını dinamik belirle
        headers = self._get_table_headers(row)
        raw = self._cells_to_dict(headers, cells)

        sku = raw.get("merchant sku") or raw.get("sku") or raw.get("asin") or ""
        qty_str = raw.get("quantity") or raw.get("qty") or "1"
        order_item_id = raw.get("order item id") or raw.get("order-item-id") or ""

        custom_text = raw.get("customization") or raw.get("personalization") or ""
        custom = self._parse_customization(custom_text)

        return self._build_order_dict(
            order_id=order_id,
            order_item_id=order_item_id,
            sku=sku.strip(),
            qty=qty_str,
            custom=custom,
        )

    def _get_table_headers(self, row) -> list[str]:
        table = row.find_parent("table")
        if not table:
            return []
        header_row = table.find("tr")
        if not header_row:
            return []
        return [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

    def _cells_to_dict(self, headers: list[str], cells: list[str]) -> dict:
        d = {}
        for i, h in enumerate(headers):
            if i < len(cells):
                d[h] = cells[i]
        return d

    def _parse_single_html(self, soup: BeautifulSoup, order_id: str) -> dict:
        text = soup.get_text("\n")
        return self._parse_from_text(text, order_id)

    def _parse_txt(self, raw_text: str) -> tuple[list[dict], list[str]]:
        orders, warnings = [], []
        # Birden fazla sipariş bloğu için split — "Order #" ile ayır
        blocks = re.split(r"(?=Order\s*#?\s*[0-9]{3}-)", raw_text, flags=re.IGNORECASE)
        blocks = [b.strip() for b in blocks if b.strip()]

        if not blocks:
            blocks = [raw_text]

        for i, block in enumerate(blocks):
            try:
                order_id = self._extract_order_id_txt(block)
                order = self._parse_from_text(block, order_id)
                orders.append(order)
            except ParseError as e:
                warnings.append(f"Blok {i+1}: {e}")

        return orders, warnings

    def _extract_order_id_txt(self, text: str) -> str:
        m = re.search(r"([0-9]{3}-[0-9]{7}-[0-9]{7})", text)
        if m:
            return m.group(1)
        m = re.search(r"([0-9]{3}-[0-9]+-[0-9]+)", text)
        return m.group(1) if m else ""

    def _parse_from_text(self, text: str, order_id: str) -> dict:
        sku = self._regex_extract(text, r"(?:Merchant\s*SKU|SKU)[:\s]+([A-Z0-9]+)")
        qty_str = self._regex_extract(text, r"(?:Quantity|Qty)[:\s]+([0-9]+)") or "1"
        order_item_id = self._regex_extract(
            text, r"(?:Order\s*Item\s*ID|order-item-id)[:\s]+([0-9]+)"
        ) or ""

        # Kişiselleştirme bloğu
        custom_match = re.search(
            r"(?:Customization|Personalization)[:\s]*(.*?)(?=\n\n|\Z)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        custom_text = custom_match.group(1) if custom_match else text
        custom = self._parse_customization(custom_text)

        return self._build_order_dict(
            order_id=order_id,
            order_item_id=order_item_id,
            sku=sku.strip() if sku else "",
            qty=qty_str,
            custom=custom,
        )

    def _regex_extract(self, text: str, pattern: str) -> str:
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _parse_customization(self, text: str) -> dict:
        result = {}
        if not text:
            return result

        # "Key: Value" satırları
        pairs = re.findall(r"([A-Za-z0-9_ ]+?)\s*:\s*([^\n|;]+)", text)
        kv = {k.strip().lower(): v.strip() for k, v in pairs}

        # name, name2..name10
        for i in range(1, 11):
            key = "name" if i == 1 else f"name{i}"
            raw_key_variants = [key, f"name {i}" if i > 1 else "name", f"recipient{i}"]
            for rk in raw_key_variants:
                if rk in kv and kv[rk]:
                    result[key] = kv[rk]
                    break

        result["year"] = kv.get("year", "")
        result["message"] = kv.get("message", kv.get("text", ""))

        # Font mapping
        raw_font = kv.get("font", kv.get("font option", kv.get("font style", "")))
        result["font_option"] = self._map_font(raw_font)

        # Color mapping
        raw_color = kv.get("color", kv.get("color option", kv.get("colour", "")))
        result["color_option"] = self._map_color(raw_color)

        return result

    def _map_font(self, raw: str) -> str:
        if not raw:
            return "SERIF"
        lower = raw.lower().strip()
        for key, val in FONT_MAP.items():
            if key in lower:
                return val
        upper = raw.upper().strip()
        if upper in VALID_FONTS:
            return upper
        return "SERIF"

    def _map_color(self, raw: str) -> str:
        if not raw:
            return "BLACK"
        upper = raw.upper().strip()
        if upper in VALID_COLORS:
            return upper
        return "BLACK"

    def _build_order_dict(
        self,
        order_id: str,
        order_item_id: str,
        sku: str,
        qty: str,
        custom: dict,
    ) -> dict:
        if not sku:
            raise ParseError("SKU bulunamadı")
        if not order_item_id:
            raise ParseError("Order Item ID bulunamadı")

        try:
            qty_int = int(qty)
        except (ValueError, TypeError):
            qty_int = 1

        order = {
            "order_id": order_id,
            "order_item_id": order_item_id,
            "sku": sku,
            "qty": qty_int,
            "name": custom.get("name", ""),
            "year": custom.get("year", ""),
            "message": custom.get("message", ""),
            "font_option": custom.get("font_option", "SERIF"),
            "color_option": custom.get("color_option", "BLACK"),
            "is_manual": False,
        }

        # name2..name10 — sadece dolu olanlar
        for i in range(2, 11):
            key = f"name{i}"
            if custom.get(key):
                order[key] = custom[key]

        return order
