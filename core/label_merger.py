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


def render_etsy_label_page(pdf_bytes: bytes, page_idx: int) -> bytes | None:
    """Etsy label PDF'inden tek sayfayı PNG olarak render eder."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf_bytes)
        if page_idx >= len(doc):
            return None
        bitmap = doc[page_idx].render(scale=150 / 72)
        buf = io.BytesIO()
        bitmap.to_pil().save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


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

    # Tek sayfa: eğer order ID listesiyse liste, değilse label
    if n == 1:
        textpage = doc[0].get_textpage()
        found = _ORDER_ID_RE.findall(textpage.get_text_range())
        if len(found) >= 3:
            return [], found
        bitmap = doc[0].render(scale=150 / 72)
        buf = io.BytesIO()
        bitmap.to_pil().save(buf, format="PNG")
        return [buf.getvalue()], []

    # Sondan itibaren, 3+ order ID içeren sayfaları liste sayfası say
    order_ids: list[str] = []
    list_page_count = 0
    for i in range(n - 1, max(n - 6, -1), -1):
        textpage = doc[i].get_textpage()
        found = _ORDER_ID_RE.findall(textpage.get_text_range())
        if len(found) >= 3:
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


def build_partner_batch_pdf(matched: list[dict]) -> bytes:
    """
    Her eşleşen sipariş için bir A4 landscape sayfa oluşturur.
    matched: [{"order_id", "order_item_ids": [str], "skus": [str],
               "summary": str, "label_png": bytes|None}, ...]
    Returns: çok sayfalı PDF bytes.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4L)
    margin = 12 * mm

    for page_num, item in enumerate(matched):
        x = margin
        y = PAGE_H - 16 * mm

        # ── Sol yarı ────────────────────────────────────────────────────────
        c.setFont("Helvetica-Bold", 14)
        c.setFillColorRGB(0.1, 0.35, 0.7)
        c.drawString(x, y, "PARTNER SİPARİŞ")
        y -= 10 * mm

        c.setStrokeColorRGB(0.1, 0.35, 0.7)
        c.setLineWidth(0.8)
        c.line(x, y + 2 * mm, HALF_W - margin, y + 2 * mm)
        y -= 6 * mm

        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x, y, f"Order ID: {item.get('order_id', '—')}")
        y -= 8 * mm

        skus = item.get("skus", [])
        c.setFont("Helvetica", 10)
        c.drawString(x, y, f"SKU: {', '.join(skus) or '—'}")
        y -= 7 * mm

        for iid in item.get("order_item_ids", [])[:5]:
            c.setFont("Helvetica-Oblique", 8)
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.drawString(x + 2 * mm, y, f"Item: {iid}")
            y -= 5 * mm

        summary = item.get("summary", "")
        if summary:
            y -= 3 * mm
            c.setFont("Helvetica-Bold", 9)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(x, y, "Personalization:")
            y -= 5 * mm
            c.setFont("Helvetica", 9)
            for line in summary.splitlines()[:12]:
                if y < 15 * mm:
                    break
                c.drawString(x + 3 * mm, y, line[:60])
                y -= 5 * mm

        # ── Orta çizgi ──────────────────────────────────────────────────────
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.setLineWidth(0.5)
        c.line(HALF_W, 5 * mm, HALF_W, PAGE_H - 5 * mm)

        # ── Sağ yarı (label) ─────────────────────────────────────────────────
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
                c.drawString(HALF_W + margin, PAGE_H / 2, f"Gorsel yuklenemedi: {exc}")
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
