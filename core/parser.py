import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# Production amazon_parser.py ile birebir eşleşen mapping'ler
FONT_MAPPING = {
    "Monotype Corsiva": "SERIF",
    "Abel": "SANS",
    "elegant script": "SCRIPT",
    "classic serif": "SERIF",
    "modern sans": "SANS",
    "welcome christmas": "WELCOME",
}

COLOR_MAPPING = {
    "Black (#000000)": "BLACK",
    "White (#ffffff)": "WHITE",
    "Gold": "GOLD",
    "Red": "RED",
    "Silver": "SILVER",
    "Ivory": "IVORY",
}

VALID_FONTS = {"SERIF", "SANS", "SCRIPT", "WELCOME"}
VALID_COLORS = {"BLACK", "WHITE", "GOLD", "RED", "SILVER", "IVORY"}


class ParseError(Exception):
    pass


class AmazonParser:
    def __init__(self, filepath: Optional[str] = None):
        self.filepath = Path(filepath) if filepath else None
        if self.filepath and not self.filepath.exists():
            raise FileNotFoundError(f"Dosya bulunamadı: {filepath}")

    def parse(self) -> tuple[list[dict], list[str]]:
        """(orders, warnings) döner."""
        if not self.filepath:
            raise ValueError("filepath belirtilmedi. parse_file(path) kullanın.")
        content = self.filepath.read_text(encoding="utf-8", errors="replace")
        if self._is_html(content):
            return self._parse_html(content)
        return self._parse_txt(content)

    def parse_file(self, filepath: str) -> list[dict]:
        """Production API uyumlu: AmazonParser().parse_file(path) → orders listesi döner."""
        self.filepath = Path(filepath)
        if not self.filepath.exists():
            raise FileNotFoundError(f"Dosya bulunamadı: {filepath}")
        orders, _ = self.parse()
        return orders

    def parse_files(self, file_paths: list[str]) -> list[dict]:
        """Birden fazla dosyayı parse et, tüm siparişleri birleştir."""
        all_orders = []
        for fp in file_paths:
            all_orders.extend(self.parse_file(fp))
        return all_orders

    def _is_html(self, content: str) -> bool:
        return "<!doctype html" in content[:1000].lower() or "<html" in content[:1000].lower()

    # ──────────────────────────────────────────────
    # HTML PARSE — production amazon_parser.py mantığı
    # ──────────────────────────────────────────────
    def _parse_html(self, content: str) -> tuple[list[dict], list[str]]:
        orders, warnings = [], []

        # Her order bloğunu "Order ID:" ile böl (production pattern)
        order_pattern = r"Order ID:\s*([0-9\-]+)"
        order_matches = list(re.finditer(order_pattern, content))

        if not order_matches:
            warnings.append("HTML'de 'Order ID:' pattern bulunamadı.")
            return orders, warnings

        for i, match in enumerate(order_matches):
            order_id = match.group(1).strip()
            start_pos = match.start()
            end_pos = order_matches[i + 1].start() if i + 1 < len(order_matches) else len(content)
            block = content[start_pos:end_pos]

            # Seller name — order bloğundan çek
            seller_m = re.search(
                r'Thank you for buying from ([^<\n]+?) on Amazon Marketplace',
                block, re.IGNORECASE
            )
            seller_name = seller_m.group(1).strip() if seller_m else ""

            # Order date
            date_m = re.search(
                r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+([A-Za-z]+\s+\d+,\s+\d{4})\b',
                block
            )
            order_date = ""
            if date_m:
                try:
                    order_date = datetime.strptime(date_m.group(1).strip(), "%b %d, %Y").strftime("%Y-%m-%d")
                except ValueError:
                    order_date = ""

            block_orders = self._parse_html_block(block, order_id, seller_name, order_date)
            if block_orders:
                orders.extend(block_orders)
            else:
                warnings.append(f"Order {order_id}: SKU bulunamadı")

        return orders, warnings

    def _parse_html_block(self, block: str, order_id: str, seller_name: str = "", order_date: str = "") -> list[dict]:
        """Bir order bloğundaki tüm item'ları parse eder. Her SKU için ayrı dict döner."""
        sku_pattern = r'SKU:\s*</span>\s*<span>\s*([^<]+?)\s*</span>'
        sku_matches = list(re.finditer(sku_pattern, block))

        # Fallback: ASIN pattern ile tek SKU dene
        if not sku_matches:
            m = re.search(
                r'<span>\s*([^<]+?)\s*</span>\s*</div>\s*<div[^>]*>\s*<span[^>]*>\s*ASIN:',
                block, re.DOTALL
            )
            if not m:
                return []
            sku_matches = [m]

        orders = []
        for idx, sm in enumerate(sku_matches):
            sku = sm.group(1).strip()
            sub_start = sm.start()
            sub_end = sku_matches[idx + 1].start() if idx + 1 < len(sku_matches) else len(block)
            sub = block[sub_start:sub_end]

            # Order Item ID
            item_id_match = re.search(
                r'myo-order-details-product-order-item-id[^>]*>\s*(\d+)', sub
            )
            order_item_id = item_id_match.group(1).strip() if item_id_match else f"{order_id}-{idx + 1}"

            # Quantity
            qty_match = re.search(
                r'<td[^>]*class="[^"]*table-border[^"]*"[^>]*>\s*(\d+)\s*</td>', sub
            )
            qty = int(qty_match.group(1)) if qty_match else 1

            # Customizations
            custom = self._extract_html_customizations(sub)

            # Item price — nested tag'leri atla, ilk sayıyı yakala
            price_m = re.search(
                r'myo-order-details-item-sub-total[^>]*>(?:[^$<]*(?:<[^>]+>[^$<]*)*)?\$\s*([\d,]+\.?\d*)',
                sub, re.DOTALL
            )
            if not price_m:
                price_m = re.search(r'myo-order-details-item-sub-total[^>]*>[^<]*\$?\s*([\d]+\.[\d]{2})', sub, re.DOTALL)
            custom["item_price"] = float(price_m.group(1).replace(",", "")) if price_m else 0.0

            # Shipping fee
            ship_m = re.search(
                r'myo-order-details-item-shipping-total[^>]*>(?:[^$<]*(?:<[^>]+>[^$<]*)*)?\$\s*([\d,]+\.?\d*)',
                sub, re.DOTALL
            )
            if not ship_m:
                ship_m = re.search(r'myo-order-details-item-shipping-total[^>]*>[^<]*\$?\s*([\d]+\.[\d]{2})', sub, re.DOTALL)
            custom["shipping_fee"] = float(ship_m.group(1).replace(",", "")) if ship_m else 0.0
            custom["seller_name"] = seller_name
            custom["order_date"] = order_date

            orders.append(self._build_order_dict(order_id, order_item_id, sku, qty, custom))

        return orders

    def _extract_html_customizations(self, block: str) -> dict:
        """Tüm NAME varyantlarını (NAME, NAME (DAD), NAME (MOM) vb.) sırayla çeker."""

        # Tüm NAME varyantlarını pozisyon sırasıyla çek
        name_pattern = r'<span[^>]*>\s*(NAME[^<:]*?):\s*</span>\s*<span>\s*([^<]+?)\s*</span>'
        name_matches = re.findall(name_pattern, block, re.IGNORECASE | re.DOTALL)
        names = [re.sub(r'\s+', ' ', v.strip()) for _, v in name_matches]

        # YEAR, MESSAGE, Font, Color — tek değer
        def _single(field):
            m = re.search(
                rf'<span[^>]*>\s*{re.escape(field)}:\s*</span>\s*<span>\s*([^<]+?)\s*</span>',
                block, re.IGNORECASE | re.DOTALL
            )
            return re.sub(r'\s+', ' ', m.group(1).strip()) if m else ""

        gift_raw = _single("GIFT BOX")

        result = {
            "name":         names[0] if len(names) > 0 else "",
            "year":         _single("YEAR"),
            "message":      _single("MESSAGE"),
            "font_option":  self._map_font(_single("Font")),
            "color_option": self._map_color(_single("Color")),
            "gift_box":     "yes" in gift_raw.lower() if gift_raw else False,
        }
        for i, n in enumerate(names[1:], start=2):
            if i <= 10:
                result[f"name{i}"] = n

        return result

    # ──────────────────────────────────────────────
    # TXT PARSE — production amazon_parser.py mantığı
    # ──────────────────────────────────────────────
    def _parse_txt(self, content: str) -> tuple[list[dict], list[str]]:
        orders, warnings = [], []

        # "Order ID:" ile böl (production pattern)
        order_blocks = re.split(r"Order ID:\s*", content)

        for block in order_blocks[1:]:
            # Order ID
            order_id_match = re.search(r'^([0-9\-]+)', block)
            order_id = order_id_match.group(1) if order_id_match else "UNKNOWN"

            # Quantity
            qty_match = re.search(r'Quantity[^\n]*\n\s*(\d+)', block)
            qty = int(qty_match.group(1)) if qty_match else 1

            # Seller Name
            seller_m = re.search(r'Seller Name:\s*\n[^\n]*\n[^\n]*\n[^\n]*\n([^\n]+)', block)
            if not seller_m:
                seller_m = re.search(r'Seller Name:\s+([^\n]+)', block)
            seller_name = seller_m.group(1).strip() if seller_m else ""

            # Order Date
            date_m = re.search(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+([A-Za-z]+\s+\d+,\s+\d{4})\b', block)
            order_date = ""
            if date_m:
                try:
                    order_date = datetime.strptime(date_m.group(1).strip(), "%b %d, %Y").strftime("%Y-%m-%d")
                except ValueError:
                    order_date = ""

            # Her SKU için ayrı sipariş (production ile aynı)
            sku_matches = list(re.finditer(r'SKU:\s*(\w+)', block))
            if not sku_matches:
                warnings.append(f"Order {order_id}: SKU bulunamadı")
                continue

            for idx, sku_match in enumerate(sku_matches):
                sku = sku_match.group(1)
                start_pos = sku_match.end()
                next_sku = re.search(r'SKU:', block[start_pos:])
                end_pos = start_pos + next_sku.start() if next_sku else len(block)
                sku_block = block[start_pos:end_pos]

                name = self._extract_txt_field(sku_block, r'NAME:\s*(.+?)(?:\n|YEAR:|$)')
                year = self._extract_txt_field(sku_block, r'YEAR:\s*(.+?)(?:\n|Font:|$)')
                message = self._extract_txt_field(sku_block, r'MESSAGE:\s*(.+?)(?:\n|Font:|$)')
                font = self._extract_txt_field(sku_block, r'Font:\s*(.+?)(?:\n|Color:|$)')
                color = self._extract_txt_field(sku_block, r'Color:\s*(.+?)(?:\n|GIFT|$)')

                custom = {
                    "name": name or "",
                    "year": year or "",
                    "message": message or "",
                    "font_option": self._map_font(font or ""),
                    "color_option": self._map_color(color or ""),
                    "seller_name": seller_name,
                    "order_date": order_date,
                }

                try:
                    order = self._build_order_dict(
                        order_id=order_id,
                        order_item_id=f"{order_id}-{idx + 1}",
                        sku=sku,
                        qty=qty,
                        custom=custom,
                    )
                    orders.append(order)
                except ParseError as e:
                    warnings.append(f"Order {order_id} SKU {sku}: {e}")

        return orders, warnings

    def _extract_txt_field(self, text: str, pattern: str) -> Optional[str]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return re.sub(r'\s+', ' ', match.group(1).strip())
        return None

    # ──────────────────────────────────────────────
    # MAPPING
    # ──────────────────────────────────────────────
    def _map_font(self, raw: str) -> str:
        if not raw:
            return "SERIF"
        # Tam eşleşme dene
        if raw in FONT_MAPPING:
            return FONT_MAPPING[raw]
        # Büyük/küçük harf fark etmeksizin kısmi eşleşme
        raw_lower = raw.lower()
        for key, val in FONT_MAPPING.items():
            if key.lower() in raw_lower:
                return val
        # Zaten kod olarak gelmişse
        if raw.upper() in VALID_FONTS:
            return raw.upper()
        # Bilinmeyen font — raw değeri geçir, JSX kurulu olup olmadığını dener
        return raw.strip()

    def _map_color(self, raw: str) -> str:
        if not raw:
            return "BLACK"
        # Tam eşleşme dene (production COLOR_MAPPING)
        if raw in COLOR_MAPPING:
            return COLOR_MAPPING[raw]
        # Büyük/küçük harf fark etmeksizin
        raw_lower = raw.lower()
        for key, val in COLOR_MAPPING.items():
            if key.lower() in raw_lower:
                return val
        # Zaten kod olarak gelmişse
        if raw.upper() in VALID_COLORS:
            return raw.upper()
        return "BLACK"

    # ──────────────────────────────────────────────
    # ORTAK
    # ──────────────────────────────────────────────
    def _build_order_dict(
        self,
        order_id: str,
        order_item_id: str,
        sku: str,
        qty: int,
        custom: dict,
    ) -> dict:
        if not sku:
            raise ParseError("SKU bulunamadı")

        order = {
            "order_id":     order_id,
            "order_item_id": str(order_item_id),
            "sku":          sku,
            "qty":          int(qty),
            "name":         custom.get("name", ""),
            "year":         custom.get("year", ""),
            "message":      custom.get("message", ""),
            "font_option":  custom.get("font_option", "SERIF"),
            "color_option": custom.get("color_option", "BLACK"),
            "gift_box":     bool(custom.get("gift_box", False)),
            "item_price":   float(custom.get("item_price", 0.0)),
            "shipping_fee": float(custom.get("shipping_fee", 0.0)),
            "seller_name":  custom.get("seller_name", ""),
            "order_date":   custom.get("order_date", ""),
            "is_manual":    False,
        }

        # name2..name10 — sadece dolu olanlar
        for i in range(2, 11):
            key = f"name{i}"
            if custom.get(key):
                order[key] = custom[key]

        return order
