import os
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

JSX_SCRIPT_PATH = os.getenv(
    "JSX_SCRIPT_PATH",
    str(Path.home() / "Desktop/autoprint-enterprise/data/Render_Sheet.jsx"),
)

ORDERS_JSON_PATH = os.getenv(
    "ORDERS_JSON_PATH",
    str(Path.home() / "Desktop/autoprint-enterprise/data/orders.json"),
)

TEMPLATE_BASE = os.getenv(
    "TEMPLATE_BASE",
    str(Path.home() / "Desktop/AutoPrint/templates"),
)

COLOR_RGB = {
    "BLACK":  (0, 0, 0),
    "WHITE":  (240, 240, 240),
    "IVORY":  (255, 255, 240),
    "RED":    (180, 30, 40),
    "GOLD":   (198, 141, 37),
    "SILVER": (180, 180, 180),
}

OSASCRIPT_TIMEOUT = int(os.getenv("OSASCRIPT_TIMEOUT", "3600"))

# AppleEvent'in kendi varsayılan ~120s timeout'u yerine OSASCRIPT_TIMEOUT'u
# kullanması için lock dosyası. "do javascript" süresi bu değeri aşarsa
# macOS -1712 (AppleEvent timed out) hatası döner — script Illustrator'da
# ARKA PLANDA ÇALIŞMAYA DEVAM EDER. Lock, bu durumda yeni bir tetiklemenin
# (watchdog veya Streamlit butonu üzerinden) üst üste binip aynı siparişleri
# ikinci kez işlemesini (duplicate sheet) engeller.
LOCK_FILE = Path(
    os.getenv(
        "JSX_LOCK_FILE",
        str(Path.home() / "Desktop/autoprint-enterprise/data/.illustrator_busy.lock"),
    )
)
LOCK_STALE_SECONDS = OSASCRIPT_TIMEOUT + 300


def detect_product_type(sku: str) -> str:
    if sku.startswith("ACRY2"):
        return "dog_round"

    # Template klasör kontrolü — glob ile: boşluk/büyük-küçük harf farkları sorun çıkarmaz
    template_base = Path(TEMPLATE_BASE)
    for shape in ("snowglobe", "heart_ceramic", "round_ceramic"):
        folder = template_base / shape
        if any(folder.glob(f"{sku}.ai")) or any(folder.glob(f"{sku}_template*.ai")):
            return shape

    # Template yok — prefix'e göre etiketle
    if sku.startswith("ACRY"):
        return "acrylic"

    if sku.startswith(("OR", "PO-", "RM", "RO-")):
        return "polarx"

    if sku.startswith("EX"):
        return "initial"

    if sku.startswith("CRMC"):
        return "round_ceramic"

    return "unknown"


_FONT_MAP: dict[str, str] = {
    # Kodlar → Illustrator
    "serif":              "MonotypeCorsiva",
    "sans":               "MonotypeCorsiva",
    "script":             "MonotypeCorsiva",
    "welcome":            "WelcomeChristmas",
    "dancing_script":     "DancingScript-Regular",
    "dancing script":     "DancingScript-Regular",
    # Sipariş font adları → Illustrator (case-insensitive arama için küçük harf)
    "cookie":             "Cookie-Regular",
    "chewy":              "Chewy-Regular",
    "cormorant garamond": "CormorantGaramond-Light",
    "josephsophia":       "josephsophia",
    "playfairdisplay":    "PlayfairDisplay-Regular",
    "playfair display":   "PlayfairDisplay-Regular",
    "all star resort":    "Allstar-Regular",
    "allstar":            "Allstar-Regular",
    "grinched":           "Grinched",
    "allura":             "Allura-Regular",
    "bad script":         "BadScript-Regular",
    "great vibes":        "GreatVibes-Regular",
}


def resolve_font(
    product_type: str,
    font_option: str,
    font_map: dict[str, str] | None = None,
) -> str:
    if product_type == "dog_round":
        return "WelcomeChristmas"
    if product_type == "snowglobe":
        return "JosephSophia"
    if not font_option:
        return "MonotypeCorsiva"
    key = font_option.strip().lower()
    # Önce ek mapping (varsa), sonra yerleşik tablo
    if font_map:
        result = font_map.get(font_option) or font_map.get(key)
        if result:
            return result
    return _FONT_MAP.get(key, font_option.strip())


def resolve_color_rgb(product_type: str, color_option: str) -> tuple[int, int, int]:
    if product_type == "dog_round":
        return COLOR_RGB["IVORY"]
    return COLOR_RGB.get(color_option, COLOR_RGB["BLACK"])


class JSXTrigger:
    def __init__(self):
        self.jsx_path = Path(JSX_SCRIPT_PATH)
        self._check_osascript()

    def _check_osascript(self) -> None:
        result = subprocess.run(["which", "osascript"], capture_output=True)
        if result.returncode != 0:
            print("[UYARI] osascript bulunamadı — macOS dışında çalışıyor olabilirsiniz.")

    def trigger_batch(self, orders: list[dict]) -> dict:
        if not self.jsx_path.exists():
            return {
                "success": False,
                "returncode": None,
                "output": "",
                "error": f"JSX script bulunamadı: {self.jsx_path}",
            }
        if not self._acquire_lock():
            return {
                "success": False,
                "returncode": None,
                "output": "",
                "error": (
                    "Illustrator şu anda başka bir batch işliyor gibi görünüyor "
                    f"(lock: {LOCK_FILE}). Önceki işlem bitmeden tekrar tetiklemek "
                    "duplicate sayfalara yol açar — lütfen bekleyin. Eğer önceki "
                    "işlem gerçekten çökmüşse ve 10 dakikadan eskiyse lock otomatik "
                    "temizlenir, ya da dosyayı elle silebilirsiniz."
                ),
            }
        try:
            success, returncode, out, err = self._run_osascript()
        finally:
            self._release_lock()
        return {"success": success, "returncode": returncode, "output": out, "error": err}

    def trigger_single(self, order: dict) -> dict:
        return self.trigger_batch([order])

    def _acquire_lock(self) -> bool:
        if LOCK_FILE.exists():
            age = time.time() - LOCK_FILE.stat().st_mtime
            if age < LOCK_STALE_SECONDS:
                return False
            LOCK_FILE.unlink(missing_ok=True)
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True

    def _release_lock(self) -> None:
        LOCK_FILE.unlink(missing_ok=True)

    def _run_osascript(self) -> tuple[bool, int | None, str, str]:
        # "with timeout of" olmadan AppleEvent'ler macOS'un varsayılan ~120s
        # limitinde -1712 ile zaman aşımına uğrar — Illustrator script'i
        # arka planda bitirmeye devam ederken Python tarafı "başarısız" sanır.
        script = (
            f"with timeout of {OSASCRIPT_TIMEOUT} seconds\n"
            f'    tell application "Adobe Illustrator" to do javascript file "{self.jsx_path}"\n'
            f"end timeout"
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=OSASCRIPT_TIMEOUT + 30,
            )
            return (
                result.returncode == 0,
                result.returncode,
                result.stdout.strip(),
                result.stderr.strip(),
            )
        except subprocess.TimeoutExpired:
            return False, None, "", f"osascript timeout ({OSASCRIPT_TIMEOUT}s) aşıldı"
        except FileNotFoundError:
            return False, None, "", "osascript bulunamadı — sadece macOS'ta çalışır"
