"""
core/parse_utils.py
===================
Platform bağımsız ortak parse yardımcısı.
Hem Yükle sekmesi hem Partner Upload sekmesi kullanır.
"""

import tempfile
from pathlib import Path


def parse_uploaded_files(files, source_platform: str) -> tuple[list[dict], list[str]]:
    """
    Streamlit UploadedFile listesini platform'a göre parse eder.
    source_platform: "amazon" veya "etsy"
    Returns: (orders, warnings)
    """
    all_orders: list[dict] = []
    all_warnings: list[str] = []

    for uf in (files or []):
        suffix = Path(uf.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uf.read())
            tmp_path = tmp.name

        try:
            if source_platform == "amazon":
                from core.parser import AmazonParser, ParseError
                parsed, warns = AmazonParser(tmp_path).parse()
            elif source_platform == "etsy":
                from core.etsy_parser import EtsyParser
                parsed, warns = EtsyParser(tmp_path).parse()
            else:
                all_warnings.append(f"[{uf.name}] Bilinmeyen platform: {source_platform}")
                continue

            for o in parsed:
                o.setdefault("platform", source_platform)

            all_orders.extend(parsed)
            all_warnings.extend([f"[{uf.name}] {w}" for w in warns])

        except FileNotFoundError as e:
            all_warnings.append(f"[{uf.name}] {e}")
        except Exception as e:
            all_warnings.append(f"[{uf.name}] Beklenmeyen hata: {type(e).__name__}: {e}")

    return all_orders, all_warnings
