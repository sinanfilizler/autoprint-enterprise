import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.order_manager import OrderManager
from core.parser import AmazonParser, ParseError
from core.jsx_trigger import detect_product_type, resolve_font

st.set_page_config(
    page_title="AutoPrint Enterprise",
    page_icon="🖨️",
    layout="wide",
)


def _orders_to_df(orders: list[dict]) -> pd.DataFrame:
    rows = []
    for o in orders:
        pt = detect_product_type(o.get("sku", ""))
        font = resolve_font(pt, o.get("font_option", "SERIF"))
        rows.append(
            {
                "Order ID": o.get("order_id", ""),
                "Item ID": o.get("order_item_id", ""),
                "SKU": o.get("sku", ""),
                "Adet": o.get("qty", 1),
                "İsim": o.get("name", ""),
                "Yıl": o.get("year", ""),
                "Mesaj": o.get("message", ""),
                "Ürün Tipi": pt,
                "Font (JSX)": font,
                "Renk": o.get("color_option", ""),
                "Manuel": "✓" if o.get("is_manual") else "",
            }
        )
    return pd.DataFrame(rows)


def _validate_manual(order_id, order_item_id, sku, name) -> list[str]:
    errors = []
    if not order_id.strip():
        errors.append("Order ID zorunlu.")
    if not order_item_id.strip():
        errors.append("Order Item ID zorunlu.")
    if not sku.strip():
        errors.append("SKU zorunlu.")
    if not name.strip():
        errors.append("İsim (name) zorunlu.")
    return errors


st.title("AutoPrint Enterprise")

order_mgr = OrderManager()

tab_upload, tab_queue, tab_dashboard = st.tabs(["📤 Yükle", "📋 Kuyruk", "📊 Dashboard"])


# ──────────────────────────────────────────────
# TAB 1: UPLOAD
# ──────────────────────────────────────────────
with tab_upload:
    st.subheader("Packing Slip Yükle")

    uploaded_files = st.file_uploader(
        "HTML veya TXT packing slip dosyası seçin",
        type=["html", "htm", "txt"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        all_parsed, all_warnings = [], []

        for uf in uploaded_files:
            suffix = Path(uf.name).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uf.read())
                tmp_path = tmp.name

            st.write(f"Dosya yolu: {tmp_path}, Boyut: {os.path.getsize(tmp_path)}")

            import re
            with open(tmp_path, 'r', encoding='utf-8', errors='replace') as f:
                raw = f.read()
            sku_test = re.findall(r'SKU:\s*</span>\s*(?:\s*<[^>]+>\s*)*\s*<span>\s*([\w\-]+)\s*</span>', raw)
            st.write(f"Direkt regex test: {len(sku_test)} SKU bulundu → {sku_test[:3]}")

            try:
                parser = AmazonParser(tmp_path)
                parsed, warnings = parser.parse()
                all_parsed.extend(parsed)
                all_warnings.extend([f"[{uf.name}] {w}" for w in warnings])
            except (FileNotFoundError, ParseError) as e:
                all_warnings.append(f"[{uf.name}] {e}")
            except Exception as e:
                st.error(f"[{uf.name}] Beklenmeyen hata: {type(e).__name__}: {e}")

        if all_warnings:
            with st.expander(f"⚠️ {len(all_warnings)} uyarı"):
                for w in all_warnings:
                    st.warning(w)

        if all_parsed:
            st.success(f"{len(all_parsed)} sipariş parse edildi. Aşağıyı kontrol edin:")
            preview_df = _orders_to_df(all_parsed)
            st.dataframe(preview_df, use_container_width=True)

            if st.button("✅ Kuyruğa Ekle", type="primary"):
                result = order_mgr.add_orders(all_parsed)
                st.success(
                    f"{result['added']} sipariş eklendi, "
                    f"{result['skipped_duplicates']} duplicate atlandı."
                )
                if result["skipped_ids"]:
                    st.info(f"Atlanan ID'ler: {', '.join(result['skipped_ids'])}")
        else:
            st.warning("Parse edilebilir sipariş bulunamadı.")

    st.divider()

    with st.expander("✏️ Manuel Sipariş Ekle"):
        with st.form("manual_order_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                m_order_id = st.text_input("Order ID *", placeholder="123-4567890-1234567")
                m_order_item_id = st.text_input("Order Item ID *", placeholder="12345678901234")
                m_sku = st.text_input("SKU *", placeholder="CRMC1246")
                m_qty = st.number_input("Adet", min_value=1, max_value=99, value=1)
            with col2:
                m_name = st.text_input("İsim (name) *")
                m_name2 = st.text_input("İsim 2 (name2)")
                m_name3 = st.text_input("İsim 3 (name3)")
                m_year = st.text_input("Yıl", placeholder="2024")
            with col3:
                m_message = st.text_area("Mesaj", height=80)
                m_font = st.selectbox("Font", ["SERIF", "SANS", "SCRIPT", "WELCOME"])
                m_color = st.selectbox("Renk", ["BLACK", "WHITE", "GOLD", "RED", "SILVER", "IVORY"])

            submitted = st.form_submit_button("Ekle")

        if submitted:
            errors = _validate_manual(m_order_id, m_order_item_id, m_sku, m_name)
            if errors:
                for e in errors:
                    st.error(e)
            else:
                order = {
                    "order_id": m_order_id.strip(),
                    "order_item_id": m_order_item_id.strip(),
                    "sku": m_sku.strip(),
                    "qty": int(m_qty),
                    "name": m_name.strip(),
                    "year": m_year.strip(),
                    "message": m_message.strip(),
                    "font_option": m_font,
                    "color_option": m_color,
                }
                if m_name2.strip():
                    order["name2"] = m_name2.strip()
                if m_name3.strip():
                    order["name3"] = m_name3.strip()

                result = order_mgr.add_manual_order(order)
                if result["added"]:
                    st.success("Manuel sipariş eklendi.")
                else:
                    st.warning("Bu sipariş zaten kuyrukta veya işlendi.")


# ──────────────────────────────────────────────
# TAB 2: QUEUE
# ──────────────────────────────────────────────
with tab_queue:
    col_title, col_refresh = st.columns([4, 1])
    with col_title:
        st.subheader("Sipariş Kuyruğu")
    with col_refresh:
        if st.button("🔄 Yenile"):
            st.rerun()

    orders = order_mgr.load_orders()

    if not orders:
        st.info("Kuyruk boş.")
    else:
        df = _orders_to_df(orders)
        st.dataframe(df, use_container_width=True)

        st.divider()
        st.write("**Sipariş Sil:**")
        del_id = st.text_input("Order Item ID girin", key="del_id")
        if st.button("🗑️ Sil", type="secondary"):
            if del_id.strip():
                if order_mgr.remove_order(del_id.strip()):
                    st.success(f"{del_id} silindi.")
                    st.rerun()
                else:
                    st.error("Bu ID kuyrukta bulunamadı.")
            else:
                st.warning("Bir ID girin.")


# ──────────────────────────────────────────────
# TAB 3: DASHBOARD
# ──────────────────────────────────────────────
with tab_dashboard:
    st.subheader("Dashboard")

    orders = order_mgr.load_orders()
    processed_ids = order_mgr.get_processed_ids()

    col1, col2, col3 = st.columns(3)
    col1.metric("Kuyrukta", len(orders))
    col2.metric("Toplam İşlenen", len(processed_ids))
    col3.metric("Manuel Sipariş", sum(1 for o in orders if o.get("is_manual")))

    if orders:
        st.divider()

        # Ürün tipi dağılımı
        product_counts: dict[str, int] = {}
        for o in orders:
            pt = detect_product_type(o["sku"])
            product_counts[pt] = product_counts.get(pt, 0) + 1

        col_chart, col_sku = st.columns(2)
        with col_chart:
            st.write("**Ürün Tipi Dağılımı (Kuyruk)**")
            st.bar_chart(product_counts)

        with col_sku:
            st.write("**SKU Dağılımı (Kuyruk)**")
            sku_counts: dict[str, int] = {}
            for o in orders:
                sku_counts[o["sku"]] = sku_counts.get(o["sku"], 0) + 1
            st.dataframe(
                pd.DataFrame(
                    [{"SKU": k, "Adet": v} for k, v in sorted(sku_counts.items(), key=lambda x: -x[1])]
                ),
                use_container_width=True,
            )

    # Son işlenenler
    st.divider()
    st.write("**Son İşlenen Siparişler (processed_orders.txt)**")
    processed_path = Path(order_mgr.processed_path)
    if processed_path.exists():
        lines = processed_path.read_text(encoding="utf-8").splitlines()
        recent = [l.strip() for l in lines if l.strip()][-20:]
        if recent:
            st.dataframe(
                pd.DataFrame({"Order Item ID": list(reversed(recent))}),
                use_container_width=True,
            )
        else:
            st.info("Henüz işlenmiş sipariş yok.")
    else:
        st.info("processed_orders.txt bulunamadı.")


