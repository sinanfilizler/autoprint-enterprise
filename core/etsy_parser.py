"""
core/etsy_parser.py
===================
Etsy packing slip PDF'lerini parse eder.
Her PDF birden fazla sipariş içerebilir (her sayfa "Order #<N>" ile başlar).
Private notes bölümündeki # etiketli veriden personalization alanları çıkarılır.
"""

import re
from pathlib import Path

_FOOTER_MARKERS = ["Do the green thing", "do the green thing"]


class EtsyParser:
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        if not self.filepath.exists():
            raise FileNotFoundError(f"Dosya bulunamadı: {filepath}")

    def parse(self) -> tuple[list[dict], list[str]]:
        """(orders, warnings) döner. AmazonParser ile aynı imza."""
        text = self._extract_text()
        return self._parse_text(text)

    # ── PDF metin çıkarma ─────────────────────────────────────────────────────

    def _extract_text(self) -> str:
        import pdfplumber
        pages = []
        with pdfplumber.open(str(self.filepath)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages.append(t)
        return "\n".join(pages)

    # ── Ana parse ─────────────────────────────────────────────────────────────

    def _parse_text(self, text: str) -> tuple[list[dict], list[str]]:
        for marker in _FOOTER_MARKERS:
            text = text.replace(marker, "")

        # "Order #12345" ile böl, delimiter'ı koruyarak
        parts = re.split(r'(Order\s*#\s*\d+)', text)

        order_blocks: list[tuple[str, str]] = []
        i = 1
        while i < len(parts):
            header = parts[i]
            m = re.match(r'Order\s*#\s*(\d+)', header)
            if m:
                order_id = m.group(1).strip()
                block = parts[i + 1] if i + 1 < len(parts) else ""
                order_blocks.append((order_id, block))
                i += 2
            else:
                i += 1

        if not order_blocks:
            return [], ["PDF'de 'Order #' pattern bulunamadı."]

        all_orders, all_warnings = [], []
        for order_id, block in order_blocks:
            orders, warns = self._parse_order_block(order_id, block)
            all_orders.extend(orders)
            all_warnings.extend([f"Order #{order_id}: {w}" for w in warns])

        return all_orders, all_warnings

    # ── Blok parse ────────────────────────────────────────────────────────────

    def _parse_order_block(self, order_id: str, block: str) -> tuple[list[dict], list[str]]:
        ship_name = self._extract_ship_name(block)
        notes = self._extract_private_notes(block)

        if not notes:
            return [], ["Private notes bulunamadı — sipariş atlanıyor"]

        # Her "#SKU" görüldüğünde yeni item başlar
        sku_sections = re.split(r'(?=#SKU\b)', notes, flags=re.IGNORECASE)
        sku_sections = [s.strip() for s in sku_sections if s.strip()]

        if not sku_sections:
            return [], ["Private notes'ta #SKU bulunamadı"]

        orders, warnings = [], []
        for item_idx, section in enumerate(sku_sections):
            order, warns = self._parse_item_section(order_id, item_idx, section, ship_name)
            if order is not None:
                orders.append(order)
            warnings.extend(warns)

        return orders, warnings

    def _extract_ship_name(self, block: str) -> str:
        m = re.search(r'Ship to\s*\n([^\n]+)', block, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _extract_private_notes(self, block: str) -> str:
        m = re.search(r'Private notes?\s*\n(.*)', block, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    # ── Item parse ────────────────────────────────────────────────────────────

    def _parse_item_section(
        self, order_id: str, item_idx: int, section: str, ship_name: str
    ) -> tuple[dict | None, list[str]]:
        warnings: list[str] = []
        lines = [l.strip() for l in section.splitlines() if l.strip()]

        # (#TAG, value) çiftlerini sırasıyla topla
        ordered_pairs: list[tuple[str, str]] = []
        current_tag: str | None = None
        value_lines: list[str] = []

        def _flush():
            if current_tag is not None:
                ordered_pairs.append((current_tag, " ".join(value_lines).strip()))

        for line in lines:
            if line.startswith("#"):
                _flush()
                current_tag = line[1:].strip().upper()
                value_lines = []
            elif current_tag is not None:
                value_lines.append(line)
        _flush()

        # Alanları çıkar
        sku = ""
        qty = 1
        name_list: list[str] = []
        name_male = ""
        name_female = ""
        year = ""
        message = ""
        font_option = "SERIF"
        color_option = "BLACK"
        extra_fields: dict[str, str] = {}

        for tag, val in ordered_pairs:
            if tag == "SKU":
                sku = val
            elif tag in ("QUANTITY", "QTY"):
                try:
                    qty = int(val)
                except (ValueError, TypeError):
                    qty = 1
            elif tag == "NAME":
                name_list.append(val)
            elif tag == "NAME_MALE":
                name_male = val
                name_list.append(val)
            elif tag == "NAME_FEMALE":
                name_female = val
                name_list.append(val)
            elif tag == "YEAR":
                year = val
            elif tag == "MESSAGE":
                message = val
            elif tag in ("FONT", "FONT_OPTION"):
                font_option = val
            elif tag in ("COLOR", "COLOR_OPTION"):
                color_option = val
            else:
                extra_fields[tag] = val

        if not sku:
            warnings.append(f"item {item_idx + 1}: #SKU eksik — sipariş işaretlendi")

        result: dict = {
            "order_id":      order_id,
            "order_item_id": f"{order_id}-{item_idx + 1}",
            "sku":           sku,
            "qty":           qty,
            "name":          name_list[0] if name_list else "",
            "year":          year,
            "message":       message,
            "font_option":   font_option,
            "color_option":  color_option,
            "is_manual":     False,
            "platform":      "etsy",
            "ship_name":     ship_name,
        }

        for i, n in enumerate(name_list[1:], start=2):
            if i <= 10:
                result[f"name{i}"] = n

        if name_male:
            result["name_male"] = name_male
        if name_female:
            result["name_female"] = name_female
        if extra_fields:
            result["extra_fields"] = extra_fields

        return result, warnings
