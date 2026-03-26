"""
AutoPrint Watchdog Agent

Kullanım:
    python -m agent.watchdog
    python -m agent.watchdog --interval 60
    python -m agent.watchdog --dry-run
"""
import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from analytics.sheets import SheetsClient
from core.jsx_trigger import JSXTrigger

BATCH_LOG_BASE = os.getenv(
    "BATCH_LOG_BASE",
    str(Path.home() / "Desktop/AutoPrint/batches"),
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("autoprint.watchdog")


class AutoPrintWatchdog:
    def __init__(self, poll_interval: int = 30, dry_run: bool = False):
        self.poll_interval = poll_interval
        self.dry_run = dry_run
        self._running = False
        self.sc = SheetsClient()
        self.jsx = None if dry_run else JSXTrigger()

        signal.signal(signal.SIGINT, self._graceful_shutdown)
        signal.signal(signal.SIGTERM, self._graceful_shutdown)

    def run(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "CANLI"
        log.info(f"AutoPrint Watchdog başlatıldı — mod: {mode}, interval: {self.poll_interval}s")
        self._running = True

        while self._running:
            try:
                self._poll()
            except Exception as e:
                log.error(f"Poll hatası: {e}")
            if self._running:
                time.sleep(self.poll_interval)

        log.info("Watchdog durduruldu.")

    def _poll(self) -> None:
        orders = self.sc.get_queue()

        if not orders:
            log.info("Kuyruk boş, bekleniyor...")
            return

        log.info(f"{len(orders)} sipariş bulundu, batch başlatılıyor...")
        self._process_batch(orders)

    def _process_batch(self, orders: list[dict]) -> None:
        batch_id = datetime.now().strftime("%Y-%m-%d_%H%M")
        self._save_batch_log(orders, batch_id)

        if self.dry_run:
            log.info(f"[DRY-RUN] {len(orders)} sipariş işlenecekti (JSX tetiklenmedi):")
            for o in orders:
                log.info(f"  → {o.get('order_item_id')} | SKU: {o.get('sku')} | {o.get('name')}")
            return

        log.info("Adobe Illustrator JSX tetikleniyor...")
        result = self.jsx.trigger_batch(orders)

        if result["success"]:
            log.info(f"Batch başarılı: {batch_id}")
            for order in orders:
                order_item_id = str(order.get("order_item_id", ""))
                ok = self.sc.mark_processed(order_item_id)
                if ok:
                    log.debug(f"  ✓ {order_item_id} Log'a taşındı.")
                else:
                    log.warning(f"  ✗ {order_item_id} mark_processed başarısız.")
            log.info(f"{len(orders)} sipariş işlendi ve kuyruktan çıkarıldı.")
        else:
            log.error(f"JSX başarısız — siparişler kuyrukta bırakıldı. Hata: {result['error']}")
            if result["output"]:
                log.debug(f"JSX çıktı: {result['output']}")

    def _save_batch_log(self, orders: list[dict], batch_id: str) -> None:
        log_dir = Path(BATCH_LOG_BASE) / batch_id
        log_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = log_dir / "orders_snapshot.json"
        snapshot_path.write_text(
            json.dumps(orders, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info(f"Batch log kaydedildi: {snapshot_path}")

    def _graceful_shutdown(self, signum, frame) -> None:
        log.info("Durdurma sinyali alındı, watchdog kapatılıyor...")
        self._running = False


def main():
    parser = argparse.ArgumentParser(description="AutoPrint Watchdog Agent")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("POLL_INTERVAL", "30")),
        help="Polling aralığı (saniye), varsayılan: 30",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="JSX tetiklemeden test modunda çalış",
    )
    args = parser.parse_args()

    watchdog = AutoPrintWatchdog(poll_interval=args.interval, dry_run=args.dry_run)
    watchdog.run()


if __name__ == "__main__":
    main()
