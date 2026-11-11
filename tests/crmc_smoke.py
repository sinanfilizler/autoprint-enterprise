"""
Gerçek ZIP smoke testi: tests/local_samples/*.zip (gitignore'lu) dosyalarını okuyup bloklama
özetini basar. Gerçek müşteri ZIP'lerini repoya koyma.

    python3 tests/crmc_smoke.py [klasör] [--pdf]

--pdf verilirse damgalı çıktıyı tests/local_samples/out/ altına yazar (o da gitignore'lu).
"""

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import crmc_packages as cp


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = Path(args[0]) if args else Path(__file__).parent / "local_samples"
    prefixes = cp.sku_prefixes()
    # Yeni kopyalanan örnekler "henüz yazılıyor" sayılmasın
    res = cp.scan_inbox(folder, prefixes, now=time.time() + cp.MIN_AGE_SEC)
    if not res.reachable:
        print(res.error)
        return 1

    print(f"Klasör: {folder}   Önekler: {', '.join(prefixes)}")
    for pkg in res.packages:
        print(f"\n== {pkg.zip_name}  ({len(pkg.blocks)} blok)")
        for b in pkg.blocks:
            flags = " ".join(f for f, on in [("DİĞER", b.is_other), ("BELİRSİZ", b.ambiguous),
                                             ("GIFT", b.gift_box), ("KİŞİSEL", b.has_personalization)] if on)
            items = ", ".join(f"{i.sku}x{i.qty}" for i in b.items) or "-"
            print(f"  {b.order_id or '?':<20} sayfa {','.join(str(p + 1) for p in b.pages):<8} {items:<40} {flags}")
    for r in res.retry:
        print(f"[tekrar denenecek] {r['zip']}: {r['neden']}")
    for s in res.skipped:
        print(f"[atlandı] {s['zip']}: {s['neden']}")
    print("\nUyarılar:", dict(Counter(w["tür"] for w in res.warnings)) or "yok")
    for w in res.warnings:
        print(f"  - {w['tür']}: {w['paket']} {w['order_id']} {w['detay']}")

    blocks = cp.sort_blocks(res.blocks)
    print(f"\nToplam: {len(blocks)} blok, {sum(b.page_count for b in blocks)} sayfa, "
          f"{sum(b.is_other for b in blocks)} diğer SKU'lu blok")

    if "--pdf" in sys.argv:
        out = folder / "out"
        out.mkdir(exist_ok=True)
        files = cp.build_pdfs(blocks, {p.package_id: p.slips for p in res.packages}, cp.new_run_id(),
                              dict(Counter(w["tür"] for w in res.warnings)))
        for name, data in files:
            (out / name).write_bytes(data)
            print(f"yazıldı: {out / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
