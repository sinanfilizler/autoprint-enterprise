"""
core/crmc_packages.py
=====================
Workstation'dan inen CRMC paket ZIP'lerini (/Volumes/CRMC_Inbox) okur, slips.pdf'leri
sipariş bloklarına ayırır, SKU'ya göre sıralar ve damgalı tek PDF (100 blokta bir dosya) üretir.

Inbox'a sadece okuma yapılır: hiçbir dosya silinmez, taşınmaz, yazılmaz.
Illustrator / sheet akışıyla ve Google Sheets ile ilgisi yoktur.
"""

from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_INBOX = "/Volumes/CRMC_Inbox"
DEFAULT_PREFIXES = "crm,acry"
PRINTED_FILE = Path(__file__).parent.parent / "data" / "crmc_printed.json"
SHAPES_FILE = Path(__file__).parent.parent / "data" / "crmc_shapes.json"   # elle atanan SKU şekilleri

SKIP_SUFFIXES = (".crdownload", ".tmp", ".part")
MIN_AGE_SEC = 10            # son 10 sn'de değişen ZIP henüz yazılıyor olabilir
STALE_MIN = 30              # en yeni ZIP bundan eskiyse "indirme duruyor olabilir"
BLOCKS_PER_FILE = 100
OTHER_LABEL = "DİĞER SKU'LU BLOKLAR"

_ORDER_RE = re.compile(r"\b\d{3}-\d{7}-\d{7}\b")
_ITEM_RE = re.compile(r"^\s*(\S+)\s*-\s*\(\s*QTY\s*:\s*(\d+)\s*\)\s*-?\s*(.*)$", re.IGNORECASE)
# "N. ANAHTAR: değer"; aynı satırda birden çok alan olabilir: "1. NAME: Quin 2. YEAR: 2026"
_FIELD_RE = re.compile(r"(?:^|(?<=\s))(\d+)\.\s*([A-Z][A-Z0-9 /&'()-]*?)\s*:\s*")
_CHROME_SUFFIX_RE = re.compile(r"\s*\(\d+\)$")
_ZIP_DATE_RE = re.compile(r"^(\d{2})---(\d{2})\.(\d{2})---(\d{2})\.(\d{2})")
_NUM_SPLIT_RE = re.compile(r"(\d+)")


# ── Ayarlar ───────────────────────────────────────────────────────────────────

def inbox_path() -> Path:
    return Path(os.getenv("CRMC_INBOX_PATH") or DEFAULT_INBOX)


def sku_prefixes() -> tuple[str, ...]:
    raw = os.getenv("CRMC_SKU_PREFIXES") or DEFAULT_PREFIXES
    return tuple(p.strip().lower() for p in raw.split(",") if p.strip())


def is_listed_sku(sku: str, prefixes: tuple[str, ...]) -> bool:
    return str(sku).strip().lower().startswith(prefixes) if prefixes else False


def natural_key(text: str) -> tuple:
    """'crmc1246' → ('crmc', 1246, ''): sayısal kısımlar sayı olarak karşılaştırılır."""
    parts = _NUM_SPLIT_RE.split(str(text).lower())
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p != "")


def package_id_from_name(filename: str) -> str:
    """'26---11.11---03.05---abc (1).zip' → '26---11.11---03.05---abc'"""
    stem = filename[:-4] if filename.lower().endswith(".zip") else filename
    return _CHROME_SUFFIX_RE.sub("", stem).strip()


def zip_datetime(filename: str) -> datetime | None:
    """ZIP adındaki 'YY---MM.DD---HH.MM' tarih-saatini okur."""
    m = _ZIP_DATE_RE.match(filename)
    if not m:
        return None
    yy, mo, dd, hh, mi = (int(g) for g in m.groups())
    try:
        return datetime(2000 + yy, mo, dd, hh, mi)
    except ValueError:
        return None


# ── Veri yapıları ─────────────────────────────────────────────────────────────

@dataclass
class Item:
    sku: str
    qty: int
    title: str = ""
    fields: dict = field(default_factory=dict)   # {"NAME": "Emily", "GIFT BOX": "Yes, ..."}

    @property
    def gift_box(self) -> bool:
        return str(self.fields.get("GIFT BOX", "")).strip().lower().startswith("yes")

    @property
    def personalization(self) -> dict:
        return {k: v for k, v in self.fields.items() if k != "GIFT BOX" and str(v).strip()}


@dataclass
class Block:
    package_id: str
    zip_name: str
    order_id: str | None
    pages: list[int]                 # slips.pdf içindeki 0 tabanlı sayfa indeksleri (bitişik)
    items: list[Item] = field(default_factory=list)
    ambiguous: bool = False          # label'sız sayfadan başlayan blok
    is_other: bool = False           # listede olmayan SKU içeriyor
    shape: str | None = None         # ROUND/HEART/MIXED/UNKNOWN; None = şekil atanmadı / sadece yabancı SKU
    shape_skus: dict = field(default_factory=dict)   # {"ROUND": [...], "HEART": [...], "UNKNOWN": [...]}

    @property
    def key(self) -> str:
        oid = self.order_id or f"?p{self.pages[0] + 1}"
        return f"{oid}|{self.package_id}"

    @property
    def skus(self) -> list[str]:
        return [i.sku for i in self.items]

    @property
    def first_sku(self) -> str:
        return self.items[0].sku if self.items else ""

    @property
    def has_personalization(self) -> bool:
        return any(i.personalization for i in self.items)

    @property
    def gift_box(self) -> bool:
        return any(i.gift_box for i in self.items)

    @property
    def page_count(self) -> int:
        return len(self.pages)


@dataclass
class Package:
    package_id: str
    zip_name: str
    mtime: float
    slips: bytes
    blocks: list[Block] = field(default_factory=list)

    @property
    def dt(self) -> datetime:
        return zip_datetime(self.zip_name) or datetime.fromtimestamp(self.mtime)


@dataclass
class ScanResult:
    reachable: bool
    packages: list[Package] = field(default_factory=list)
    retry: list[dict] = field(default_factory=list)          # {"zip", "neden"}
    skipped: list[dict] = field(default_factory=list)        # bilgi: atlanan paketler
    warnings: list[dict] = field(default_factory=list)       # {"tür", "paket", "order_id", "detay"}
    newest_mtime: float | None = None
    error: str = ""

    @property
    def blocks(self) -> list[Block]:
        return [b for p in self.packages for b in p.blocks]


def _warn(kind: str, package: str = "", order_id: str | None = "", detail: str = "") -> dict:
    return {"tür": kind, "paket": package, "order_id": order_id or "", "detay": detail}


# ── slips.pdf ayrıştırma ──────────────────────────────────────────────────────

def _has_label(page) -> bool:
    """Sağ yarıda kargo label görseli var mı (gerçekte x0 ~411, genişlik ~340)."""
    half = float(page.width) / 2
    for img in page.images:
        x0 = float(img.get("x0", 0))
        width = float(img.get("x1", x0)) - x0
        if x0 >= half - 20 and width >= float(page.width) * 0.25:
            return True
    return False


def _left_lines(page) -> list[dict]:
    left = page.crop((0, 0, float(page.width) / 2, float(page.height)))
    return [ln for ln in left.extract_text_lines(strip=True, return_chars=False) if ln["text"]]


def _parse_items(pages_lines: list[list[dict]]) -> list[Item]:
    """
    Kalem satırlarını ve 'N. ANAHTAR: değer' satırlarını sayfalar boyunca okur.
    Satıra kayan başlık/değer, hemen altındaki (araya boşluk girmeyen) satırlardan eklenir.
    """
    items: list[Item] = []
    for lines in pages_lines:
        target = None          # ("title", item) | ("field", item, key) — devam satırı nereye
        prev = None
        for ln in lines:
            text = ln["text"]
            close = prev is not None and (ln["top"] - prev["bottom"]) <= max(6.0, (prev["bottom"] - prev["top"]) * 0.9)
            prev = ln
            m = _ITEM_RE.match(text)
            if m:
                item = Item(sku=m.group(1).strip(), qty=int(m.group(2)), title=m.group(3).strip())
                items.append(item)
                target = ("title", item)
                continue
            fields = list(_FIELD_RE.finditer(text))
            if fields and fields[0].start() == 0 and items:
                for f, nxt in zip(fields, fields[1:] + [None]):
                    key = f.group(2).strip()
                    items[-1].fields[key] = text[f.end():nxt.start() if nxt else None].strip()
                target = ("field", items[-1], key)
                continue
            if target and close:
                if target[0] == "title":
                    target[1].title = f"{target[1].title} {text}".strip()
                else:
                    _, it, key = target
                    it.fields[key] = f"{it.fields[key]} {text}".strip()
            else:
                target = None
    return items


def parse_slips(pdf_bytes: bytes, package_id: str, zip_name: str) -> tuple[list[Block], list[dict]]:
    """slips.pdf → bloklar. Label'lı sayfa blok başlatır, label'sız aynı order ID'li sayfa devamdır."""
    import pdfplumber

    blocks: list[Block] = []
    warnings: list[dict] = []
    block_lines: dict[int, list[list[dict]]] = {}

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages):
            lines = _left_lines(page)
            ids = list(dict.fromkeys(_ORDER_RE.findall("\n".join(ln["text"] for ln in lines))))
            oid = ids[0] if ids else None
            pno = f"sayfa {idx + 1}"
            if len(ids) > 1:
                warnings.append(_warn("Birden fazla order ID", package_id, oid, f"{pno}: {', '.join(ids)}"))
            if oid is None:
                warnings.append(_warn("Okunamayan order ID", package_id, "", pno))

            if _has_label(page):
                blocks.append(Block(package_id, zip_name, oid, [idx]))
            else:
                last = blocks[-1] if blocks else None
                if last and last.pages[-1] == idx - 1 and oid and last.order_id == oid:
                    last.pages.append(idx)
                else:
                    why = ("ilk sayfa label'sız" if not last
                           else f"label'sız, order ID önceki bloktan farklı ({last.order_id or '?'})")
                    warnings.append(_warn("Belirsiz sayfa", package_id, oid, f"{pno}: {why}; ayrı blok yapıldı"))
                    blocks.append(Block(package_id, zip_name, oid, [idx], ambiguous=True))
            block_lines.setdefault(id(blocks[-1]), []).append(lines)

    for b in blocks:
        b.items = _parse_items(block_lines.get(id(b), []))
        if not b.items:
            warnings.append(_warn("SKU okunamadı", package_id, b.order_id, f"sayfa {b.pages[0] + 1}"))
    return blocks, warnings


def _read_slips(raw: bytes) -> bytes | None:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for name in zf.namelist():
            if Path(name).name.lower() == "slips.pdf":
                return zf.read(name)
    return None


# ── Inbox tarama ──────────────────────────────────────────────────────────────

def scan_inbox(path: Path | str | None = None, prefixes: tuple[str, ...] | None = None,
               now: float | None = None) -> ScanResult:
    """Inbox'ı okur (sadece okuma). Paketleri ayrıştırır, kopya order ID'lerde ilkini tutar."""
    path = Path(path) if path else inbox_path()
    prefixes = sku_prefixes() if prefixes is None else prefixes
    now = time.time() if now is None else now

    try:
        if not path.is_dir():
            return ScanResult(False, error=f"Inbox bulunamadı: {path}")
        # Orijinal 'x.zip', Chrome kopyası 'x (1).zip'den önce gelsin
        entries = sorted(path.iterdir(), key=lambda p: (package_id_from_name(p.name), len(p.name), p.name))
    except OSError as e:
        return ScanResult(False, error=f"Inbox okunamadı: {path} ({e})")

    res = ScanResult(True)
    seen_pkg: set[str] = set()
    seen_orders: dict[str, str] = {}

    for p in entries:
        name = p.name
        low = name.lower()
        if name.startswith(".") or low.endswith(SKIP_SUFFIXES) or not low.endswith(".zip"):
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError as e:
            res.retry.append({"zip": name, "neden": f"okunamadı ({e})"})
            continue
        res.newest_mtime = max(res.newest_mtime or mtime, mtime)
        if now - mtime < MIN_AGE_SEC:
            res.retry.append({"zip": name, "neden": "henüz yazılıyor olabilir"})
            continue

        pkg_id = package_id_from_name(name)
        if pkg_id in seen_pkg:
            res.skipped.append({"zip": name, "neden": "aynı paketin kopya indirmesi"})
            continue

        try:
            slips = _read_slips(p.read_bytes())
        except (zipfile.BadZipFile, OSError, EOFError) as e:
            res.retry.append({"zip": name, "neden": f"ZIP açılamadı ({type(e).__name__})"})
            continue
        if slips is None:
            res.retry.append({"zip": name, "neden": "slips.pdf yok"})
            continue

        try:
            blocks, warns = parse_slips(slips, pkg_id, name)
        except Exception as e:  # bozuk / yarım PDF
            res.retry.append({"zip": name, "neden": f"slips.pdf okunamadı ({type(e).__name__})"})
            continue

        all_skus = [s for b in blocks for s in b.skus]
        if not any(is_listed_sku(s, prefixes) for s in all_skus):
            res.skipped.append({"zip": name, "neden": "listede SKU yok"})
            continue

        seen_pkg.add(pkg_id)
        res.warnings.extend(warns)
        pkg = Package(pkg_id, name, mtime, slips)
        for b in blocks:
            b.is_other = not b.items or not all(is_listed_sku(s, prefixes) for s in b.skus)
            if b.order_id:
                if b.order_id in seen_orders:
                    res.warnings.append(_warn("Kopya order ID", pkg_id, b.order_id,
                                              f"ilk görüldüğü paket: {seen_orders[b.order_id]}; bu blok atlandı"))
                    continue
                seen_orders[b.order_id] = pkg_id
            pkg.blocks.append(b)
        res.packages.append(pkg)

    if res.newest_mtime and now - res.newest_mtime > STALE_MIN * 60:
        mins = int((now - res.newest_mtime) // 60)
        res.warnings.append(_warn("İndirme duruyor olabilir", "", "",
                                  f"en yeni ZIP {mins} dk önce geldi"))
    return res


# ── Şekil (ROUND / HEART) ─────────────────────────────────────────────────────
# Kaynak: AutoPrint template klasörleri (sadece okunur). <SKU>_template.ai veya <SKU>.ai.

ROUND, HEART, MIXED, UNKNOWN = "ROUND", "HEART", "MIXED", "UNKNOWN"
SHAPE_FOLDERS = {"round_ceramic": ROUND, "heart_ceramic": HEART}
SHAPE_ORDER = {ROUND: 0, HEART: 1, MIXED: 2, UNKNOWN: 3, None: 4}
SHAPE_LABEL = {ROUND: "R", HEART: "H", MIXED: "MIX", UNKNOWN: "?"}
SCOPES = {"all": "Hepsi", ROUND: "Sadece ROUND", HEART: "Sadece HEART"}
_TEMPLATE_SUFFIX_RE = re.compile(r"_template.*$", re.IGNORECASE)


def template_base() -> Path:
    """Sheet akışının kullandığı template kökü (TEMPLATE_BASE, core/jsx_trigger.py)."""
    from core.jsx_trigger import TEMPLATE_BASE
    return Path(TEMPLATE_BASE)


def template_sku(filename: str) -> str:
    """'CRMC1714 _template.ai' → 'crmc1714' (uzantısız, büyük/küçük harf duyarsız)."""
    stem = filename[:-3] if filename.lower().endswith(".ai") else filename
    return _TEMPLATE_SUFFIX_RE.sub("", stem).strip().lower()


def build_template_index(base: Path | str | None = None) -> dict[str, set[str]] | None:
    """{sku: {klasör adı, ...}}. Template kökü yoksa None (şekil özelliği kapalı)."""
    base = Path(base) if base else template_base()
    try:
        if not base.is_dir():
            return None
        index: dict[str, set[str]] = {}
        for folder in base.iterdir():
            if not folder.is_dir():
                continue
            for f in folder.iterdir():
                if f.suffix.lower() == ".ai" and not f.name.startswith("."):
                    index.setdefault(template_sku(f.name), set()).add(folder.name)
        return index
    except OSError:
        return None


@dataclass
class SkuShape:
    shape: str        # ROUND / HEART / UNKNOWN
    source: str       # klasör / elle / başlık / çakışma / yok
    detail: str = ""


def resolve_sku_shape(sku: str, title: str, index: dict[str, set[str]], manual: dict[str, str]) -> SkuShape:
    """Elle atama > template klasörü > slip başlığı ('başlıktan tahmin'). İki klasörde birden = çakışma."""
    key = sku.strip().lower()
    if manual.get(key) in (ROUND, HEART):
        return SkuShape(manual[key], "elle")
    folders = index.get(key, set())
    shapes = sorted({SHAPE_FOLDERS[f] for f in folders if f in SHAPE_FOLDERS})
    if len(shapes) > 1:
        return SkuShape(UNKNOWN, "çakışma", " + ".join(sorted(f for f in folders if f in SHAPE_FOLDERS)))
    if shapes:
        return SkuShape(shapes[0], "klasör")
    t = (title or "").lower()
    guesses = [sh for sh, word in ((ROUND, "round"), (HEART, "heart")) if re.search(rf"\b{word}\b", t)]
    if len(guesses) == 1:
        return SkuShape(guesses[0], "başlık", title)
    other = ", ".join(sorted(folders))
    return SkuShape(UNKNOWN, "yok", f"{other} klasöründe" if other else "template yok")


def assign_shapes(blocks: list[Block], prefixes: tuple[str, ...], index: dict[str, set[str]],
                  manual: dict[str, str]) -> dict[str, SkuShape]:
    """
    Her bloğa şekil sınıfı atar (sadece listedeki SKU'lar bakılır, yabancılar sınıfı etkilemez):
    UNKNOWN (en az biri belirsiz) > MIXED (round + heart) > ROUND / HEART.
    Dönüş: {sku: SkuShape} (sekmedeki şekil kaynakları tablosu için).
    """
    seen: dict[str, SkuShape] = {}
    for b in blocks:
        groups: dict[str, list[str]] = {}
        for it in b.items:
            if not is_listed_sku(it.sku, prefixes):
                continue
            key = it.sku.lower()
            if key not in seen:
                seen[key] = resolve_sku_shape(it.sku, it.title, index, manual)
            lst = groups.setdefault(seen[key].shape, [])
            if key not in lst:
                lst.append(key)
        b.shape_skus = groups
        if not groups:
            b.shape = None
        elif UNKNOWN in groups:
            b.shape = UNKNOWN
        elif len(groups) > 1:
            b.shape = MIXED
        else:
            b.shape = next(iter(groups))
    return seen


def select_blocks(blocks: list[Block], scope: str) -> list[Block]:
    """'Sadece ROUND/HEART': karşı şekil dışarıda kalır; MIXED, UNKNOWN ve şekilsiz bloklar her zaman girer."""
    if scope not in (ROUND, HEART):
        return list(blocks)
    return [b for b in blocks if b.shape not in (ROUND, HEART) or b.shape == scope]


def load_manual_shapes(path: Path | None = None) -> dict[str, str]:
    try:
        data = json.loads(Path(path or SHAPES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k).lower(): v for k, v in data.items() if v in (ROUND, HEART)}


def save_manual_shapes(shapes: dict[str, str], path: Path | None = None) -> None:
    path = Path(path or SHAPES_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k.lower(): v for k, v in sorted(shapes.items()) if v in (ROUND, HEART)}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ── Sıralama ve uyarılar ──────────────────────────────────────────────────────

def sort_blocks(blocks: list[Block]) -> list[Block]:
    """
    Normal bloklar şekil bölümüne göre (ROUND, HEART, MIXED, UNKNOWN), bölüm içinde SKU (doğal)
    + order_id; 'diğer' bloklar aynı SKU kuralıyla en sonda. Şekil atanmadıysa sadece SKU sırası.
    """
    def k(b: Block):
        section = 0 if b.is_other else SHAPE_ORDER.get(b.shape, 4) if b.shape else 0
        return (b.is_other, section, natural_key(b.first_sku), b.order_id or "", b.package_id, b.pages[0])
    return sorted(blocks, key=k)


def queue_warnings(scan_blocks: list[Block], candidate_blocks: list[Block],
                   queue: list[dict], prefixes: tuple[str, ...]) -> list[dict]:
    """
    - Kuyrukta olup hiçbir ZIP'te görünmeyen (listedeki SKU'lu) sipariş.
    - ZIP'te olup kuyrukta olmayan, kişiselleştirmeli blok (sadece basılacak adaylar).
    """
    warns = []
    zip_orders = {b.order_id for b in scan_blocks if b.order_id}
    queue_orders = {str(r.get("order_id", "")).strip() for r in queue}
    missing: dict[str, set] = {}
    for r in queue:
        oid = str(r.get("order_id", "")).strip()
        sku = str(r.get("sku", "")).strip()
        if oid and is_listed_sku(sku, prefixes) and oid not in zip_orders:
            missing.setdefault(oid, set()).add(sku)
    for oid, skus in sorted(missing.items()):
        warns.append(_warn("Kuyrukta var, ZIP yok", "", oid,
                           f"{', '.join(sorted(skus))}: bekliyor veya elle indirilecek olabilir"))
    for b in candidate_blocks:
        if b.order_id and b.has_personalization and b.order_id not in queue_orders:
            warns.append(_warn("ZIP'te var, kuyrukta yok", b.package_id, b.order_id,
                               f"{', '.join(b.skus)}: slip henüz yüklenmemiş olabilir"))
    return warns


# ── Basıldı kaydı ─────────────────────────────────────────────────────────────

def load_printed(path: Path | None = None) -> dict:
    try:
        return json.loads(Path(path or PRINTED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def mark_printed(keys: list[str], run_id: str, path: Path | None = None) -> int:
    path = Path(path or PRINTED_FILE)
    data = load_printed(path)
    stamp = datetime.now().isoformat(timespec="seconds")
    for k in keys:
        data[k] = {"printed_at": stamp, "run_id": run_id}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return len(keys)


# ── PDF üretimi ───────────────────────────────────────────────────────────────

_FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
_fonts: tuple[str, str, bool] | None = None
_TR_ASCII = str.maketrans("İıĞğŞşÇçÖöÜü·", "IiGgSsCcOoUu-")


def _font() -> tuple[str, str, bool]:
    """(normal, bold, unicode_ok). Türkçe karakter için TTF; yoksa Helvetica + ASCII."""
    global _fonts
    if _fonts:
        return _fonts
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for reg, bold in _FONT_CANDIDATES:
        if os.path.exists(reg):
            try:
                pdfmetrics.registerFont(TTFont("CRMC", reg))
                pdfmetrics.registerFont(TTFont("CRMC-Bold", bold if os.path.exists(bold) else reg))
                _fonts = ("CRMC", "CRMC-Bold", True)
                return _fonts
            except Exception:
                continue
    _fonts = ("Helvetica", "Helvetica-Bold", False)
    return _fonts


def _t(text: str) -> str:
    return text if _font()[2] else text.translate(_TR_ASCII)


def stamp_text(run_id: str, num: int, page_no: int, block: Block) -> str:
    """'<run> · #037 · 1/2 · R' ; MIXED: '... · MIX R: crmc1320 | H: crm1228' ; yabancı: '... · DİĞER'"""
    text = f"{run_id} · #{num:03d} · {page_no}/{block.page_count}"
    if block.shape:
        text += f" · {SHAPE_LABEL[block.shape]}"
        if block.shape == MIXED:
            text += " " + " | ".join(f"{SHAPE_LABEL[sh]}: {', '.join(block.shape_skus[sh])}"
                                     for sh in (ROUND, HEART) if block.shape_skus.get(sh))
    if block.is_other:
        text += " · DİĞER"
    return text


def _stamp_overlay(text: str, llx: float, lly: float, urx: float, ury: float):
    from pypdf import PdfReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(urx, ury))
    # Uzun MIX damgası sayfa genişliğine sığsın diye küçülür (en az 5.5pt)
    size, room = 8.0, (urx - llx) - 28
    while size > 5.5 and stringWidth(_t(text), _font()[0], size) > room:
        size -= 0.5
    c.setFont(_font()[0], size)
    c.setFillGray(0.25)
    c.drawString(llx + 14, lly + 8, _t(text))
    c.save()
    return PdfReader(io.BytesIO(buf.getvalue())).pages[0]


def summary_rows(blocks: list[Block]) -> list[dict]:
    """SKU bazlı özet: blok sayısı, toplam adet, gift box adedi."""
    rows: dict[str, dict] = {}
    for b in blocks:
        shape_of = {sku: sh for sh, skus in b.shape_skus.items() for sku in skus}
        for sku in dict.fromkeys(s.lower() for s in b.skus):
            rows.setdefault(sku, {"sku": sku, "blok": 0, "adet": 0, "gift_box": 0, "diğer": b.is_other,
                                  "şekil": SHAPE_LABEL.get(shape_of.get(sku), "")})
            rows[sku]["blok"] += 1
        for it in b.items:
            r = rows[it.sku.lower()]
            r["adet"] += it.qty
            if it.gift_box:
                r["gift_box"] += it.qty
    return sorted(rows.values(), key=lambda r: (r["diğer"], natural_key(r["sku"])))


def _section_ranges(blocks: list[Block]) -> list[str]:
    """Sıralı bloklarda bölüm aralıkları: 'ROUND 12 blok (#001-#012)'."""
    out, start, cur = [], 0, None
    names = {ROUND: "ROUND", HEART: "HEART", MIXED: "MIXED", UNKNOWN: "ŞEKLİ BELİRSİZ (?)"}
    def label(b):
        return OTHER_LABEL if b.is_other else names.get(b.shape)
    for i, b in enumerate(blocks + [None]):
        lab = label(b) if b else "__end__"
        if lab != cur:
            if cur is not None and cur and i > start:
                out.append(f"{cur}: {i - start} blok (#{start + 1:03d}-#{i:03d})")
            cur, start = lab, i
    return out


def _summary_pages(blocks: list[Block], run_id: str, warn_counts: dict[str, int], n_files: int,
                   scope_label: str = "") -> bytes:
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.pdfgen import canvas

    reg, bold, _ = _font()
    W, H = landscape(letter)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    others = [b for b in blocks if b.is_other]
    other_skus = sorted({s for b in others for s in b.skus}, key=natural_key)
    y = H - 50

    def line(text, size=10, font=reg, dx=0):
        nonlocal y
        if y < 50:
            c.showPage()
            y = H - 50
        c.setFont(font, size)
        c.drawString(40 + dx, y, _t(text))
        y -= size + 5

    line(f"CRMC Paket Özeti  ·  {run_id}", 16, bold)
    line(f"Oluşturma: {datetime.now():%Y-%m-%d %H:%M}  ·  {n_files} dosya"
         + (f"  ·  Kapsam: {scope_label}" if scope_label else ""), 9)
    y -= 6
    line(f"Toplam blok: {len(blocks)}    Toplam sayfa: {sum(b.page_count for b in blocks)}    "
         f"Paket: {len({b.package_id for b in blocks})}", 11, bold)
    line(f"{OTHER_LABEL}: {len(others)} blok" + (f"  ({', '.join(other_skus)})" if other_skus else ""), 10)
    if any(b.shape for b in blocks):
        for r in _section_ranges(blocks):
            line(r, 10)
    if warn_counts:
        line("Uyarılar: " + ", ".join(f"{k} {v}" for k, v in warn_counts.items()), 10)
    else:
        line("Uyarı yok.", 10)
    y -= 8
    cols = [("SKU", 0), ("Blok", 160), ("Adet", 220), ("Gift box", 280), ("Şekil", 350), ("", 410)]
    c.setFont(bold, 10)
    for title, dx in cols:
        c.drawString(40 + dx, y, _t(title))
    y -= 15
    for r in summary_rows(blocks):
        if y < 50:
            c.showPage()
            y = H - 50
        c.setFont(reg, 10)
        for val, (_, dx) in zip([r["sku"], r["blok"], r["adet"], r["gift_box"], r["şekil"], "DİĞER" if r["diğer"] else ""], cols):
            c.drawString(40 + dx, y, _t(str(val)))
        y -= 14
    c.save()
    return buf.getvalue()


def _divider_page(run_id: str, count: int) -> bytes:
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.pdfgen import canvas
    reg, bold, _ = _font()
    W, H = landscape(letter)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setFont(bold, 48)
    c.drawCentredString(W / 2, H / 2 + 10, _t("DİĞER SKU'LAR"))
    c.setFont(reg, 14)
    c.drawCentredString(W / 2, H / 2 - 30, _t(f"{count} blok  ·  {run_id}"))
    c.save()
    return buf.getvalue()


def build_pdfs(blocks: list[Block], slips_by_package: dict[str, bytes], run_id: str,
               warn_counts: dict[str, int] | None = None,
               per_file: int = BLOCKS_PER_FILE, scope_label: str = "") -> list[tuple[str, bytes]]:
    """
    Sıralı bloklardan damgalı PDF'ler üretir (bellekte). İlk dosyanın başında özet sayfası,
    'diğer' bölümünün önünde ayraç sayfası. Dönüş: [(dosya_adı, bytes), ...]
    """
    from pypdf import PdfReader, PdfWriter

    blocks = sort_blocks(blocks)
    readers = {pid: PdfReader(io.BytesIO(data)) for pid, data in slips_by_package.items()}
    chunks = [blocks[i:i + per_file] for i in range(0, len(blocks), per_file)] or [[]]
    n_others = sum(1 for b in blocks if b.is_other)
    out = []
    num = 0
    divider_done = False

    for ci, chunk in enumerate(chunks, 1):
        w = PdfWriter()
        if ci == 1:
            for pg in PdfReader(io.BytesIO(_summary_pages(blocks, run_id, warn_counts or {}, len(chunks), scope_label))).pages:
                w.add_page(pg)
        for b in chunk:
            num += 1
            if b.is_other and not divider_done:
                w.add_page(PdfReader(io.BytesIO(_divider_page(run_id, n_others))).pages[0])
                divider_done = True
            src = readers[b.package_id]
            for j, pidx in enumerate(b.pages, 1):
                page = w.add_page(src.pages[pidx])
                if page.get("/Rotate"):
                    page.transfer_rotation_to_content()
                box = page.mediabox
                text = stamp_text(run_id, num, j, b)
                page.merge_page(_stamp_overlay(text, float(box.left), float(box.bottom),
                                               float(box.right), float(box.top)))
        buf = io.BytesIO()
        w.write(buf)
        out.append((f"CRMC_{run_id}_{ci:03d}.pdf", buf.getvalue()))
    return out


def new_run_id() -> str:
    return datetime.now().strftime("%y%m%d-%H%M")
