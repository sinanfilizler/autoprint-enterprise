"""
core/label_merger.py
====================
Replacement + Partner Upload için A4 landscape PDF oluşturma (reportlab).
"""

import io
import re

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

_ORDER_ID_RE = re.compile(r'\b\d{3}-\d{7}-\d{7}\b')
_ETSY_ORDER_ID_RE = re.compile(r'Order\s*#:\s*(\d+)')

A4L = landscape(A4)
PAGE_W, PAGE_H = A4L
HALF_W = PAGE_W / 2


def extract_etsy_label_order_ids(pdf_bytes: bytes) -> dict[str, int]:
    """
    Etsy label PDF'ini okur. Her sayfada "Order #: <ID>" arar.
    Returns: {order_id: page_index} — her label sayfası kendi ID'sini taşır.
    """
    import pdfplumber
    result: dict[str, int] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            m = _ETSY_ORDER_ID_RE.search(text)
            if m:
                result[m.group(1).strip()] = page_idx
    return result


def _render_etsy_label_upright(pdf_bytes: bytes, page_idx: int) -> bytes | None:
    """
    Etsy label sayfasından USPS label kutusunu kırpır ve 90° CW döndürür.
    Çıktı: Dik ve okunabilir USPS label PNG bytes.

    pdfplumber koordinatları (fiziksel top'tan):
      Header  : top=0-72  (kırpılır)
      Label   : x=90-522, top=72-360  (kullanılan alan)
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None

    SCALE = 150 / 72
    doc = pdfium.PdfDocument(pdf_bytes)
    if page_idx >= len(doc):
        return None

    bitmap = doc[page_idx].render(scale=SCALE)
    img = bitmap.to_pil()
    W, H = img.size

    PAD = 5  # pt cinsinden kenar payı
    left  = max(0, int((90 - PAD) * SCALE))
    upper = max(0, int((72 - PAD) * SCALE))
    right = min(W, int((522 + PAD) * SCALE))
    lower = min(H, int((360 + PAD) * SCALE))

    label_crop = img.crop((left, upper, right, lower))
    upright = label_crop.rotate(-90, expand=True)  # 90° CW → dik okunabilir

    buf = io.BytesIO()
    upright.save(buf, format="PNG")
    return buf.getvalue()


def build_etsy_batch_pdf(
    oid_source_map: dict[str, tuple[bytes, int]],
    oid_to_items: dict[str, list[dict]],
    sku_names: dict[str, str] | None = None,
) -> bytes:
    """
    Her Etsy siparişi için A4 landscape sayfa üretir.
    Sol: ORDER bilgisi (düz metin, rotasyon yok).
    Sağ: Kırpılmış + 90° CW döndürülmüş dik USPS label.

    oid_source_map: {order_id: (pdf_bytes, page_index)}
    oid_to_items:   {order_id: [item_dict, ...]}
    """
    PERSONA_KEYS = [
        ("name",    "NAME"),    ("name2",   "NAME 2"),  ("name3",  "NAME 3"),
        ("name4",   "NAME 4"),  ("name5",   "NAME 5"),  ("name6",  "NAME 6"),
        ("name7",   "NAME 7"),  ("name8",   "NAME 8"),  ("name9",  "NAME 9"),
        ("name10",  "NAME 10"), ("year",    "YEAR"),    ("message","MESSAGE"),
        ("gift_box","GIFT BOX"),
    ]

    sku_names = {k.upper(): v for k, v in (sku_names or {}).items()}

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4L)
    margin = 12 * mm

    items_list = [(oid, items) for oid, items in oid_to_items.items()
                  if oid in oid_source_map]

    for page_num, (oid, items) in enumerate(items_list):
        pdf_bytes, page_idx = oid_source_map[oid]

        # ── Sol yarı: ORDER bilgisi ──────────────────────────────────────────
        x = margin
        y = PAGE_H - 16 * mm

        c.setFont("Helvetica-Bold", 16)
        c.setFillColorRGB(0.08, 0.30, 0.65)
        c.drawString(x, y, "ORDER")
        y -= 10 * mm

        c.setStrokeColorRGB(0.08, 0.30, 0.65)
        c.setLineWidth(0.8)
        c.line(x, y + 2 * mm, HALF_W - margin, y + 2 * mm)
        y -= 6 * mm

        c.setFont("Helvetica-Bold", 11)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(x, y, f"Order ID:  {oid}")
        y -= 8 * mm

        for item_idx, item in enumerate(items):
            if y < 15 * mm:
                break

            sku = item.get("sku") or "—"
            qty = item.get("qty", 1)
            c.setFont("Helvetica-Bold", 10)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(x, y, f"SKU:  {sku}    QTY:  {qty}")
            y -= 6 * mm

            product_name = sku_names.get(sku.upper(), "")
            if product_name and y >= 15 * mm:
                c.setFont("Helvetica-Oblique", 9)
                c.setFillColorRGB(0.35, 0.35, 0.35)
                c.drawString(x + 2 * mm, y, product_name[:60])
                y -= 5 * mm
            else:
                y -= 1 * mm

            persona_fields = [(k, lbl) for k, lbl in PERSONA_KEYS if item.get(k)]
            for suffix, slabel in (("_male", "M"), ("_female", "F")):
                for i in range(1, 11):
                    k = f"name{'' if i == 1 else i}{suffix}"
                    if item.get(k):
                        persona_fields.append((k, f"NAME ({slabel}{'' if i == 1 else i})"))
            # Custom / bilinmeyen field'lar (DOG_NAME, ANIMAL vb.)
            extra_fields = item.get("extra_fields") or {}

            if persona_fields or extra_fields:
                c.setFont("Helvetica-Bold", 9)
                c.setFillColorRGB(0, 0, 0)
                c.drawString(x, y, "Personalization")
                y -= 1 * mm
                c.setStrokeColorRGB(0.6, 0.6, 0.6)
                c.setLineWidth(0.4)
                c.line(x, y, HALF_W - margin, y)
                y -= 5.5 * mm

                lbl_x = x + 3 * mm
                val_x = x + 30 * mm

                for key, label in persona_fields:
                    if y < 12 * mm:
                        break
                    c.setFont("Helvetica-Bold", 9)
                    c.setFillColorRGB(0, 0, 0)
                    c.drawString(lbl_x, y, f"{label}:")
                    c.setFont("Helvetica", 9)
                    c.setFillColorRGB(0.1, 0.1, 0.1)
                    c.drawString(val_x, y, str(item.get(key, ""))[:50])
                    y -= 5.5 * mm

                for ef_key, ef_val in extra_fields.items():
                    if y < 12 * mm:
                        break
                    lbl = ef_key.replace("_", " ")
                    c.setFont("Helvetica-Bold", 9)
                    c.setFillColorRGB(0, 0, 0)
                    c.drawString(lbl_x, y, f"{lbl}:")
                    c.setFont("Helvetica", 9)
                    c.setFillColorRGB(0.1, 0.1, 0.1)
                    c.drawString(val_x, y, str(ef_val)[:50])
                    y -= 5.5 * mm

            if item_idx < len(items) - 1:
                y -= 3 * mm

        # ── Orta çizgi ──────────────────────────────────────────────────────
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.setLineWidth(0.5)
        c.line(HALF_W, 5 * mm, HALF_W, PAGE_H - 5 * mm)

        # ── Sağ yarı: dik Etsy USPS label ───────────────────────────────────
        label_png = _render_etsy_label_upright(pdf_bytes, page_idx)
        if label_png:
            try:
                img = ImageReader(io.BytesIO(label_png))
                iw, ih = img.getSize()
                avail_w = HALF_W - 2 * margin
                avail_h = PAGE_H - 2 * margin
                scale = min(avail_w / iw, avail_h / ih)
                dw, dh = iw * scale, ih * scale
                ix = HALF_W + (HALF_W - dw) / 2
                iy = (PAGE_H - dh) / 2
                c.drawImage(img, ix, iy, width=dw, height=dh, preserveAspectRatio=True)
            except Exception as exc:
                c.setFont("Helvetica", 9)
                c.setFillColorRGB(0.5, 0.5, 0.5)
                c.drawString(HALF_W + margin, PAGE_H / 2, f"Label yuklenemedi: {exc}")
        else:
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(HALF_W + margin, PAGE_H / 2, "Label bulunamadi")

        if page_num < len(items_list) - 1:
            c.showPage()

    c.save()
    buf.seek(0)
    return buf.getvalue()


def split_label_pdf(pdf_bytes: bytes) -> tuple[list[bytes], list[str]]:
    """
    Multi-page label PDF'ini ayırır.
    Sondan geriye doğru, 3+ order ID içeren sayfalar sipariş listesi sayılır.
    Kalan sayfalar birer label PNG (150dpi) olarak döner.
    Returns: (label_pngs, order_ids)
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise RuntimeError("pypdfium2 yüklü değil: pip install pypdfium2")

    doc = pdfium.PdfDocument(pdf_bytes)
    n = len(doc)
    if n == 0:
        return [], []

    def _is_list_page(text: str, found: list) -> bool:
        """Sayfanın order listesi mi yoksa label mi olduğunu belirler."""
        if len(found) >= 3:
            return True
        if len(found) >= 1 and "list of orders" in text.lower():
            return True
        return False

    # Tek sayfa: eğer order ID listesiyse liste, değilse label
    if n == 1:
        textpage = doc[0].get_textpage()
        text = textpage.get_text_range()
        found = _ORDER_ID_RE.findall(text)
        if _is_list_page(text, found):
            return [], found
        bitmap = doc[0].render(scale=150 / 72)
        buf = io.BytesIO()
        bitmap.to_pil().save(buf, format="PNG")
        return [buf.getvalue()], []

    # Sondan itibaren, order listesi sayfalarını tespit et
    order_ids: list[str] = []
    list_page_count = 0
    for i in range(n - 1, max(n - 6, -1), -1):
        textpage = doc[i].get_textpage()
        text = textpage.get_text_range()
        found = _ORDER_ID_RE.findall(text)
        if _is_list_page(text, found):
            order_ids = found + order_ids
            list_page_count += 1
        else:
            break

    label_page_count = n - list_page_count

    label_pngs: list[bytes] = []
    for i in range(label_page_count):
        bitmap = doc[i].render(scale=150 / 72)
        buf = io.BytesIO()
        bitmap.to_pil().save(buf, format="PNG")
        label_pngs.append(buf.getvalue())

    return label_pngs, order_ids


def build_partner_batch_pdf(matched: list[dict], sku_names: dict[str, str] | None = None) -> bytes:
    """
    Her eşleşen sipariş için bir A4 landscape sayfa oluşturur.
    matched: [{
        "order_id": str,
        "ship_name": str,
        "ship_address": str,
        "items": [{"sku": str, "qty": int, "persona": {key: val}}, ...],
        "label_png": bytes|None
    }, ...]
    sku_names: {sku_upper: product_name} — SKU'nun altına ürün adı yazar.

    Sol yarı: müşteri adı/adresi → order ID → her item için SKU (Qty-N) + personalizasyon
    Sağ yarı: shipping label PNG
    """
    sku_names = {k.upper(): v for k, v in (sku_names or {}).items()}
    _PERSONA_LABELS = {
        "name": "Name", "name2": "Name 2", "name3": "Name 3",
        "name4": "Name 4", "name5": "Name 5", "name6": "Name 6",
        "name7": "Name 7", "name8": "Name 8", "name9": "Name 9",
        "name10": "Name 10", "year": "Year", "message": "Message",
        "gift_box": "Gift Box",
    }

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4L)
    margin = 12 * mm

    for page_num, item in enumerate(matched):
        x = margin
        y = PAGE_H - 14 * mm

        # ── Sol yarı ────────────────────────────────────────────────────────

        # Müşteri adı
        ship_name = item.get("ship_name", "")
        if ship_name:
            c.setFont("Helvetica-Bold", 13)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(x, y, ship_name)
            y -= 7 * mm

        # Müşteri adresi
        ship_address = item.get("ship_address", "")
        if ship_address:
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(0.3, 0.3, 0.3)
            c.drawString(x, y, ship_address[:70])
            y -= 6 * mm

        # Order ID
        c.setFont("Helvetica-Bold", 10)
        c.setFillColorRGB(0.08, 0.30, 0.65)
        c.drawString(x, y, f"Order ID: {item.get('order_id', '—')}")
        y -= 5 * mm

        # Ayraç
        c.setStrokeColorRGB(0.08, 0.30, 0.65)
        c.setLineWidth(0.7)
        c.line(x, y, HALF_W - margin, y)
        y -= 7 * mm

        # Her item: SKU (Qty-N) + personalizasyon
        items = item.get("items", [])
        for item_idx, it in enumerate(items):
            if y < 12 * mm:
                break

            sku = it.get("sku", "—")
            qty = it.get("qty", 1)

            c.setFont("Helvetica-Bold", 11)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(x, y, f"{sku}  (Qty-{qty})")
            y -= 6 * mm

            product_name = sku_names.get(sku.upper(), "")
            if product_name and y >= 10 * mm:
                c.setFont("Helvetica-Oblique", 9)
                c.setFillColorRGB(0.35, 0.35, 0.35)
                c.drawString(x + 2 * mm, y, product_name[:60])
                y -= 5 * mm

            persona = it.get("persona", {})
            for key, label in _PERSONA_LABELS.items():
                val = persona.get(key)
                if not val:
                    continue
                if y < 10 * mm:
                    break
                c.setFont("Helvetica", 9)
                c.setFillColorRGB(0.15, 0.15, 0.15)
                c.drawString(x + 4 * mm, y, f"{label}: {str(val)[:55]}")
                y -= 5 * mm

            if item_idx < len(items) - 1:
                y -= 3 * mm

        # ── Orta çizgi ──────────────────────────────────────────────────────
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.setLineWidth(0.5)
        c.line(HALF_W, 5 * mm, HALF_W, PAGE_H - 5 * mm)

        # ── Sağ yarı: shipping label ─────────────────────────────────────────
        label_png = item.get("label_png")
        if label_png:
            try:
                img = ImageReader(io.BytesIO(label_png))
                iw, ih = img.getSize()
                avail_w = HALF_W - 2 * margin
                avail_h = PAGE_H - 2 * margin
                scale = min(avail_w / iw, avail_h / ih)
                dw, dh = iw * scale, ih * scale
                ix = HALF_W + (HALF_W - dw) / 2
                iy = (PAGE_H - dh) / 2
                c.drawImage(img, ix, iy, width=dw, height=dh, preserveAspectRatio=True)
            except Exception as exc:
                c.setFont("Helvetica", 9)
                c.setFillColorRGB(0.5, 0.5, 0.5)
                c.drawString(HALF_W + margin, PAGE_H / 2, f"Label yuklenemedi: {exc}")
        else:
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(HALF_W + margin, PAGE_H / 2, "Label bulunamadi")

        if page_num < len(matched) - 1:
            c.showPage()

    c.save()
    buf.seek(0)
    return buf.getvalue()


def parse_personalization(text: str) -> dict[str, str]:
    """# formatındaki personalization metnini {KEY: value} dict'e çevirir."""
    result: dict[str, str] = {}
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if line.startswith("#"):
            parts = line[1:].split(":", 1)
            if len(parts) == 2:
                result[parts[0].strip()] = parts[1].strip()
    return result


def build_a4_pdf(
    sku: str,
    replacement_type: str,
    items: list,
    created_at: str,
    label_image_bytes: bytes | None,
) -> bytes:
    """
    A4 landscape PDF döner.
    Sol: kırmızı [!] REPLACEMENT başlığı + sipariş bilgileri.
    Sağ: label görseli (PNG bytes olarak alınır).
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4L)

    margin = 12 * mm

    # ── Sol yarı ─────────────────────────────────────────────────────────────
    x = margin
    y = PAGE_H - 16 * mm

    # REPLACEMENT başlığı (kırmızı)
    c.setFont("Helvetica-Bold", 18)
    c.setFillColorRGB(0.78, 0.08, 0.08)
    c.drawString(x, y, "[!] REPLACEMENT")
    y -= 12 * mm

    # Ayraç çizgisi (sol yarıda başlık altı)
    c.setStrokeColorRGB(0.78, 0.08, 0.08)
    c.setLineWidth(0.8)
    c.line(x, y + 3 * mm, HALF_W - margin, y + 3 * mm)
    y -= 4 * mm

    # SKU
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x, y, f"SKU:  {sku}")
    y -= 8 * mm

    # Replacement tipi
    c.setFont("Helvetica", 11)
    c.drawString(x, y, f"Tip:  {replacement_type}")
    y -= 7 * mm

    # Tarih
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(x, y, f"Tarih:  {created_at}")
    y -= 11 * mm

    # Personalization başlığı
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x, y, "Personalization")
    y -= 1 * mm
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setLineWidth(0.4)
    c.line(x, y, HALF_W - margin, y)
    y -= 6 * mm

    for item in (items or []):
        item_sku = str(item.get("sku", ""))
        persona  = item.get("personalization", {})
        if y < 15 * mm:
            break
        if item_sku:
            c.setFont("Helvetica-Bold", 10)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(x + 3 * mm, y, f"SKU: {item_sku}")
            y -= 6 * mm
        for k, v in persona.items():
            if y < 10 * mm:
                break
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(x + 6 * mm, y, f"{k}: {v}")
            y -= 5 * mm
        y -= 3 * mm

    # Orta ayraç
    c.setStrokeColorRGB(0.82, 0.82, 0.82)
    c.setLineWidth(0.5)
    c.line(HALF_W, 5 * mm, HALF_W, PAGE_H - 5 * mm)

    # ── Sağ yarı ─────────────────────────────────────────────────────────────
    if label_image_bytes:
        try:
            img = ImageReader(io.BytesIO(label_image_bytes))
            iw, ih = img.getSize()
            avail_w = HALF_W - 2 * margin
            avail_h = PAGE_H - 2 * margin
            scale = min(avail_w / iw, avail_h / ih)
            dw, dh = iw * scale, ih * scale
            ix = HALF_W + (HALF_W - dw) / 2
            iy = (PAGE_H - dh) / 2
            c.drawImage(img, ix, iy, width=dw, height=dh, preserveAspectRatio=True)
        except Exception as exc:
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(HALF_W + margin, PAGE_H / 2, f"Gorsel yuklenemedi: {exc}")
    else:
        c.setFont("Helvetica", 9)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(HALF_W + margin, PAGE_H / 2, "Label PDF bulunamadi")

    c.save()
    buf.seek(0)
    return buf.getvalue()
