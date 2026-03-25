import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ORDERS_JSON_PATH = os.getenv(
    "ORDERS_JSON_PATH",
    str(Path.home() / "Desktop/AutoPrint/input/parsed_orders/orders.json"),
)
PROCESSED_TXT_PATH = os.getenv(
    "PROCESSED_TXT_PATH",
    str(Path.home() / "Desktop/AutoPrint/processed_orders.txt"),
)


class OrderManager:
    def __init__(self):
        self.orders_path = Path(ORDERS_JSON_PATH)
        self.processed_path = Path(PROCESSED_TXT_PATH)

    def load_orders(self) -> list[dict]:
        if not self.orders_path.exists():
            return []
        try:
            return json.loads(self.orders_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def save_orders(self, orders: list[dict]) -> None:
        self.orders_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.orders_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(orders, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp_path.replace(self.orders_path)

    def get_processed_ids(self) -> set[str]:
        if not self.processed_path.exists():
            return set()
        lines = self.processed_path.read_text(encoding="utf-8").splitlines()
        return {line.strip() for line in lines if line.strip()}

    def _is_duplicate(self, order: dict, existing_ids: set[str], processed_ids: set[str]) -> bool:
        oid = str(order.get("order_item_id", ""))
        return oid in existing_ids or oid in processed_ids

    def add_orders(self, new_orders: list[dict]) -> dict:
        current = self.load_orders()
        existing_ids = {str(o.get("order_item_id", "")) for o in current}
        processed_ids = self.get_processed_ids()

        added, skipped_ids = 0, []
        for order in new_orders:
            if self._is_duplicate(order, existing_ids, processed_ids):
                skipped_ids.append(str(order.get("order_item_id", "")))
            else:
                current.append(order)
                existing_ids.add(str(order.get("order_item_id", "")))
                added += 1

        if added:
            self.save_orders(current)

        return {"added": added, "skipped_duplicates": len(skipped_ids), "skipped_ids": skipped_ids}

    def add_manual_order(self, order_dict: dict) -> dict:
        order_dict["is_manual"] = True
        return self.add_orders([order_dict])

    def mark_processed(self, order_item_id: str, is_manual: bool) -> None:
        if is_manual:
            return
        self.processed_path.parent.mkdir(parents=True, exist_ok=True)
        with self.processed_path.open("a", encoding="utf-8") as f:
            f.write(order_item_id.strip() + "\n")

    def remove_order(self, order_item_id: str) -> bool:
        orders = self.load_orders()
        new_orders = [o for o in orders if str(o.get("order_item_id", "")) != str(order_item_id)]
        if len(new_orders) == len(orders):
            return False
        self.save_orders(new_orders)
        return True
