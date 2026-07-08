"""
core/label_merger.py
====================
Replacement için A4 landscape PDF oluşturma (reportlab).
"""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

A4L = landscape(A4)
PAGE_W, PAGE_H = A4L
HALF_W = PAGE_W / 2


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
