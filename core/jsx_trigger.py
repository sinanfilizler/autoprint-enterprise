import os
import subprocess
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
    "GOLD":   (200, 160, 60),
    "SILVER": (180, 180, 180),
}

OSASCRIPT_TIMEOUT = int(os.getenv("OSASCRIPT_TIMEOUT", "3600"))


def detect_product_type(sku: str) -> str:
    if sku.startswith("ACRY2"):
        return "dog_round"

    # Template klasör kontrolü — ACRY snowglobe olabilir
    template_base = Path(TEMPLATE_BASE)
    for shape in ("snowglobe", "heart_ceramic", "round_ceramic"):
        folder = template_base / shape
        if (folder / f"{sku}.ai").exists():
            return shape
        if (folder / f"{sku}_template.ai").exists():
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


def resolve_font(product_type: str, font_option: str) -> str:
    if product_type == "dog_round":
        return "WelcomeChristmas"
    if product_type == "snowglobe":
        return "JosephSophia"
    if font_option == "WELCOME":
        return "WelcomeChristmas"
    return "MonotypeCorsiva"


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
        success, returncode, out, err = self._run_osascript()
        return {"success": success, "returncode": returncode, "output": out, "error": err}

    def trigger_single(self, order: dict) -> dict:
        return self.trigger_batch([order])

    def _run_osascript(self) -> tuple[bool, int | None, str, str]:
        script = (
            f'tell application "Adobe Illustrator" to '
            f'do javascript file "{self.jsx_path}"'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=OSASCRIPT_TIMEOUT,
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
