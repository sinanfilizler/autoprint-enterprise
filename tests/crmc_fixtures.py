"""Sentetik slips.pdf / ZIP üretimi (gerçek müşteri verisi kullanılmaz)."""

import io
import zipfile

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGE = (792, 612)  # Letter yatay

_LABEL = io.BytesIO()
Image.new("RGB", (340, 500), (230, 230, 230)).save(_LABEL, "PNG")


def page(order_id, lines, label=True, name="Test Customer"):
    """Bir sayfa tanımı. lines: sol yarıya yazılacak satırlar ('' = boşluk)."""
    return {"order_id": order_id, "lines": lines, "label": label, "name": name}


def item(sku, qty=1, title="Personalized Ornament", fields=None, gift=True):
    out = [f"{sku} - (QTY: {qty}) - {title}"]
    for i, (k, v) in enumerate((fields or {}).items(), 1):
        out.append(f"{i}. {k}: {v}")
    out.append(f"{len(fields or {}) + 1}. GIFT BOX: " + ("Yes, add gift box." if gift else "No, thank you!"))
    out.append("")
    return out


def slips_pdf(pages):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE)
    for p in pages:
        y = 570
        header = [p["name"], "123 Sample St", "Springfield, IL 62701", "",
                  f"Order ID: {p['order_id']}" if p["order_id"] else "Order ID: -", ""]
        c.setFont("Helvetica", 10)
        for ln in header + p["lines"]:
            if ln:
                c.drawString(30, y, ln)
            y -= 14 if ln else 10
        if p["label"]:
            c.drawImage(ImageReader(io.BytesIO(_LABEL.getvalue())), 411, 50, width=340, height=500)
        c.showPage()
    c.save()
    return buf.getvalue()


def zip_bytes(pages, extra_svg=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("slips.pdf", slips_pdf(pages))
        if extra_svg:
            zf.writestr("design_1.svg", "<svg/>")
    return buf.getvalue()
