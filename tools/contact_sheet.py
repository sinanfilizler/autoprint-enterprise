"""Template denetim PNG'lerini kontak sayfası PDF'inde birleştirir.

data/audit/*.png (Audit_Templates.jsx çıktısı, <SKU>_<font>.png) → data/audit/contact_sheet.pdf
Her sayfada 30 görsel (5 sütun x 6 satır), altında SKU ve font adı.

Kullanım:
    python3 tools/contact_sheet.py
    python3 tools/contact_sheet.py --input data/audit --output data/audit/contact_sheet.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
COLS, ROWS = 5, 6
MARGIN = 28          # pt
HEADER = 22          # pt, sayfa başlığı
CAPTION = 18         # pt, görsel altı yazı
GAP = 6              # pt, hücreler arası
THUMB_PX = 500       # PDF'e gömülen görselin en uzun kenarı (dosya küçük kalsın)


def parse_name(path: Path) -> tuple[str, str]:
    """'CRMC1246_MonotypeCorsiva.png' → ('CRMC1246', 'MonotypeCorsiva')."""
    sku, sep, font = path.stem.rpartition("_")
    return (sku, font) if sep else (path.stem, "")


def load_thumb(path: Path) -> Image.Image:
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((THUMB_PX, THUMB_PX))
    return img


def build(input_dir: Path, output: Path) -> int:
    pngs = sorted(input_dir.glob("*.png"), key=lambda p: p.name.lower())
    if not pngs:
        print(f"PNG bulunamadı: {input_dir}")
        return 0

    page_w, page_h = letter
    cell_w = (page_w - 2 * MARGIN - (COLS - 1) * GAP) / COLS
    cell_h = (page_h - 2 * MARGIN - HEADER - (ROWS - 1) * GAP) / ROWS
    img_h = cell_h - CAPTION
    per_page = COLS * ROWS
    pages = (len(pngs) + per_page - 1) // per_page

    output.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output), pagesize=letter)
    c.setTitle("Template Audit")

    for i, path in enumerate(pngs):
        pos = i % per_page
        if pos == 0:
            if i:
                c.showPage()
            c.setFont("Helvetica-Bold", 10)
            c.drawString(MARGIN, page_h - MARGIN - 10, "Template Audit")
            c.setFont("Helvetica", 8)
            c.drawRightString(page_w - MARGIN, page_h - MARGIN - 10,
                              f"Sayfa {i // per_page + 1}/{pages}  ·  {len(pngs)} görsel")

        col, row = pos % COLS, pos // COLS
        x = MARGIN + col * (cell_w + GAP)
        y_top = page_h - MARGIN - HEADER - row * (cell_h + GAP)

        try:
            img = load_thumb(path)
            scale = min(cell_w / img.width, img_h / img.height)
            w, h = img.width * scale, img.height * scale
            c.drawImage(ImageReader(img), x + (cell_w - w) / 2, y_top - h, w, h)
        except Exception as e:  # bozuk PNG tüm sayfayı durdurmasın
            c.setFont("Helvetica", 7)
            c.drawString(x + 2, y_top - 12, f"Okunamadı: {e}"[:60])

        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.rect(x, y_top - cell_h, cell_w, cell_h, stroke=1, fill=0)

        sku, font = parse_name(path)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(x + cell_w / 2, y_top - img_h - 8, sku[:28])
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(x + cell_w / 2, y_top - img_h - 15, font[:34])

    c.save()
    print(f"{len(pngs)} görsel, {pages} sayfa → {output}")
    return len(pngs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, default=ROOT / "data" / "audit")
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()
    out = args.output or (args.input / "contact_sheet.pdf")
    build(args.input, out)


if __name__ == "__main__":
    main()
