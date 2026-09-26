"""
core/etsy_parser.py
===================
Etsy packing slip PDF'lerini parse eder.
Her PDF birden fazla sipariş içerebilir (her sayfa "Order #<N>" ile başlar).

Private notes formatı (Etsy private-notes alanında seller tarafından):
  #KEY
  #VALUE
  #KEY2
  #VALUE2
  ...

Her değer de # ile başladığı için text '#' işaretine göre bölünür;
her segment ilk satırından okunur (boşluk içeren değerler korunur):
  #Mike & Rachel → "Mike & Rachel" tam olarak alınır.
Çift-tek (alternating) pozisyon: 0=KEY, 1=VALUE, 2=KEY, 3=VALUE …

Bu sayede DOG_NAME, ANIMAL gibi özel field'lar da otomatik yakalanır;
known-tags listesi gerekmez.
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
        """(orders, warnings) döner."""
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
        tokens = self._extract_note_tokens(block)

        if not tokens:
            return [], ["Private notes bulunamadı — sipariş atlanıyor"]

        # İlk #SKU'dan önceki tokenları at (gürültü / preamble)
        first_sku = next((i for i, t in enumerate(tokens) if t.upper() == "SKU"), None)
        if first_sku is None:
            return [], ["Private notes'ta #SKU bulunamadı"]
        tokens = tokens[first_sku:]

        # "SKU" token'ı görüldükçe yeni item section başlatılır
        sections: list[list[str]] = []
        current: list[str] = []
        for tok in tokens:
            if tok.upper() == "SKU" and current:
                sections.append(current)
                current = []
            current.append(tok)
        if current:
            sections.append(current)

        if not sections:
            return [], ["Private notes'ta geçerli #SKU section bulunamadı"]

        orders, warnings = [], []
        for item_idx, section in enumerate(sections):
            order, warns = self._parse_token_section(order_id, item_idx, section, ship_name)
            if order is not None:
                orders.append(order)
            warnings.extend(warns)

        return orders, warnings

    def _extract_ship_name(self, block: str) -> str:
        # "Ship to N items?\n<Ad Soyad>"
        m = re.search(r'Ship to\s+\d+\s+items?\s*\n([^\n]+)', block, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r'Ship to\s*\n([^\n]+)', block, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _extract_note_tokens(self, block: str) -> list[str]:
        """
        Private notes bölümündeki #KEY / #VALUE çiftlerini çıkarır.
        Her '#' işareti yeni bir token başlatır; token değeri boşluk içerebilir
        (örn. #Mike & Rachel). pdfplumber sütun karışmasından gelen gürültü
        genellikle ayrı satırlarda gelir — her segmentten sadece ilk satır alınır.
        """
        m = re.search(r'Private notes?\s*(.*)', block, re.IGNORECASE | re.DOTALL)
        if not m:
            return []
        notes_text = m.group(1)
        tokens = []
        for seg in notes_text.split('#'):
            lines = [l.strip() for l in seg.splitlines() if l.strip()]
            if lines:
                tokens.append(lines[0])
        return tokens

    # ── Token section parse ───────────────────────────────────────────────────

    def _parse_token_section(
        self, order_id: str, item_idx: int, tokens: list[str], ship_name: str
    ) -> tuple[dict | None, list[str]]:
        warnings: list[str] = []

        # Alternating pozisyon: 0=KEY, 1=VALUE, 2=KEY, 3=VALUE …
        # Herhangi bir #TAG otomatik KEY — known-list gerekmez.
        kv_pairs: list[tuple[str, str]] = []
        for i in range(0, len(tokens) - 1, 2):
            key = tokens[i].upper()
            val = tokens[i + 1]
            kv_pairs.append((key, val))

        # Field mapping
        sku = ""
        qty = 1
        name_list: list[str] = []
        name_male = ""
        name_female = ""
        year = ""
        message = ""
        gift_box = ""
        font_option = "SERIF"
        color_option = "BLACK"
        state = ""
        extra_fields: dict[str, str] = {}

        for tag, val in kv_pairs:
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
            elif tag == "NAME_FEMALE":
                name_female = val
            elif tag == "YEAR":
                year = val
            elif tag == "MESSAGE":
                message = val
            elif tag == "GIFTBOX":
                gift_box = val
            elif tag in ("FONT", "FONT_OPTION"):
                font_option = val
            elif tag in ("COLOR", "COLOR_OPTION"):
                color_option = val
            elif tag == "STATE":
                state = val
            else:
                extra_fields[tag] = val

        if not sku:
            warnings.append(f"item {item_idx + 1}: #SKU bulunamadı — sipariş atlanıyor")
            return None, warnings

        result: dict = {
            "order_id":      order_id,
            "order_item_id": f"{order_id}-{item_idx + 1}",
            "sku":           sku,
            "qty":           qty,
            "name":          name_list[0] if name_list else "",
            "year":          year,
            "message":       message,
            "gift_box":      gift_box,
            "font_option":   font_option,
            "color_option":  color_option,
            "is_manual":     False,
            "platform":      "etsy",
            "ship_name":     ship_name,
        }

        if state:
            result["state"] = state

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
