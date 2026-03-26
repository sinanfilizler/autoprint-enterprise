import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from core.order_manager import OrderManager
from core.parser import AmazonParser, ParseError
from core.jsx_trigger import JSXTrigger, detect_product_type, resolve_font

st.set_page_config(
    page_title="AutoPrint Enterprise",
    page_icon="🖨️",
    layout="wide",
)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


# ── Şifre kontrolü ───────────────────────────────────────────────────────────
def _check_auth() -> bool:
    return st.session_state.get("authenticated", False)


def _render_login_sidebar() -> None:
    st.sidebar.markdown("### Giriş")
    pwd = st.sidebar.text_input("Şifre", type="password", key="pwd_input")
    if st.sidebar.button("Giriş Yap"):
        if ADMIN_PASSWORD and pwd == ADMIN_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.sidebar.error("Hatalı şifre.")


# ── Google Sheets bağlantısı (uygulama ömrü boyunca tek instance) ────────────
@st.cache_resource
def _get_sheets_client():
    from analytics.sheets import SheetsClient
    return SheetsClient()


def _sheets() -> "SheetsClient | None":
    """SheetsClient döner. Bağlantı yoksa None + sidebar uyarısı."""
    try:
        return _get_sheets_client()
    except Exception as e:
        st.session_state["sheets_error"] = str(e)
        return None


# ── Yardımcı fonksiyonlar ────────────────────────────────────────────────────
order_mgr = OrderManager()


def _orders_to_df(orders: list[dict]) -> pd.DataFrame:
    rows = []
    for o in orders:
        pt = detect_product_type(o.get("sku", ""))
        font = resolve_font(pt, o.get("font_option", "SERIF"))
        rows.append({
            "Order ID":    o.get("order_id", ""),
            "Item ID":     o.get("order_item_id", ""),
            "SKU":         o.get("sku", ""),
            "Adet":        o.get("qty", 1),
            "İsim":        o.get("name", ""),
            "Yıl":         o.get("year", ""),
            "Mesaj":       o.get("message", ""),
            "Ürün Tipi":   pt,
            "Font (JSX)":  font,
            "Renk":        o.get("color_option", ""),
            "Manuel":      "✓" if o.get("is_manual") else "",
        })
    return pd.DataFrame(rows)


def _validate_manual(order_id, order_item_id, sku, name) -> list[str]:
    errors = []
    if not order_id.strip():     errors.append("Order ID zorunlu.")
    if not order_item_id.strip(): errors.append("Order Item ID zorunlu.")
    if not sku.strip():          errors.append("SKU zorunlu.")
    if not name.strip():         errors.append("İsim (name) zorunlu.")
    return errors


# ── Başlık + auth ────────────────────────────────────────────────────────────
st.title("AutoPrint Enterprise")

authenticated = _check_auth()

if not authenticated:
    _render_login_sidebar()
else:
    if st.sidebar.button("Çıkış Yap"):
        st.session_state["authenticated"] = False
        st.rerun()

sc = _sheets()
if sc:
    st.sidebar.success("Google Sheets bağlı")
else:
    err = st.session_state.get("sheets_error", "Bilinmeyen hata")
    st.sidebar.error(f"Sheets bağlantısı yok:\n{err}")

if authenticated:
    tab_upload, tab_queue, tab_dashboard, tab_admin = st.tabs(
        ["📤 Yükle", "📋 Kuyruk", "📊 Dashboard", "⚙️ Admin"]
    )
else:
    (tab_upload,) = st.tabs(["📤 Yükle"])


# ──────────────────────────────────────────────────────────────────────────────
# TAB 1: UPLOAD
# ──────────────────────────────────────────────────────────────────────────────
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

            try:
                parsed, warnings = AmazonParser(tmp_path).parse()
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
            st.dataframe(_orders_to_df(all_parsed), use_container_width=True)

            if st.button("✅ Kuyruğa Ekle", type="primary"):
                if sc:
                    with st.spinner("Google Sheets'e yazılıyor..."):
                        result = sc.append_queue(all_parsed)
                    st.session_state["last_upload"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    st.success(
                        f"{result['added']} sipariş eklendi, "
                        f"{result['skipped_duplicates']} duplicate atlandı."
                    )
                    if result["skipped_ids"]:
                        st.info(f"Atlanan ID'ler: {', '.join(result['skipped_ids'])}")
                else:
                    st.error("Google Sheets bağlantısı yok — sipariş eklenemiyor.")
        else:
            st.warning("Parse edilebilir sipariş bulunamadı.")

    st.divider()

    with st.expander("✏️ Manuel Sipariş Ekle"):
        with st.form("manual_order_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                m_order_id      = st.text_input("Order ID *", placeholder="123-4567890-1234567")
                m_order_item_id = st.text_input("Order Item ID *", placeholder="12345678901234")
                m_sku           = st.text_input("SKU *", placeholder="CRMC1246")
                m_qty           = st.number_input("Adet", min_value=1, max_value=99, value=1)
            with col2:
                m_name  = st.text_input("İsim (name) *")
                m_name2 = st.text_input("İsim 2 (name2)")
                m_name3 = st.text_input("İsim 3 (name3)")
                m_year  = st.text_input("Yıl", placeholder="2024")
            with col3:
                m_message = st.text_area("Mesaj", height=80)
                m_font    = st.selectbox("Font", ["SERIF", "SANS", "SCRIPT", "WELCOME"])
                m_color   = st.selectbox("Renk", ["BLACK", "WHITE", "GOLD", "RED", "SILVER", "IVORY"])

            submitted = st.form_submit_button("Ekle")

        if submitted:
            errors = _validate_manual(m_order_id, m_order_item_id, m_sku, m_name)
            if errors:
                for e in errors:
                    st.error(e)
            elif not sc:
                st.error("Google Sheets bağlantısı yok.")
            else:
                order = {
                    "order_id":       m_order_id.strip(),
                    "order_item_id":  m_order_item_id.strip(),
                    "sku":            m_sku.strip(),
                    "qty":            int(m_qty),
                    "name":           m_name.strip(),
                    "year":           m_year.strip(),
                    "message":        m_message.strip(),
                    "font_option":    m_font,
                    "color_option":   m_color,
                    "is_manual":      True,
                }
                if m_name2.strip(): order["name2"] = m_name2.strip()
                if m_name3.strip(): order["name3"] = m_name3.strip()

                result = sc.append_queue([order])
                if result["added"]:
                    st.session_state["last_upload"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    st.success("Manuel sipariş eklendi.")
                else:
                    st.warning("Bu sipariş zaten kuyrukta veya işlendi.")


# ──────────────────────────────────────────────────────────────────────────────
# TAB 2: QUEUE  (sadece giriş yapılmışsa)
# ──────────────────────────────────────────────────────────────────────────────
if not authenticated:
    st.stop()

with tab_queue:
    col_title, col_refresh = st.columns([4, 1])
    with col_title:
        st.subheader("Sipariş Kuyruğu")
    with col_refresh:
        if st.button("🔄 Yenile"):
            st.rerun()

    if not sc:
        st.error("Google Sheets bağlantısı yok.")
    else:
        with st.spinner("Kuyruk yükleniyor..."):
            orders = sc.get_queue()

        if not orders:
            st.info("Kuyruk boş.")
        else:
            st.dataframe(_orders_to_df(orders), use_container_width=True)
            st.divider()

            col_send, col_dry = st.columns(2)

            with col_send:
                if st.button("🖨️ Illustrator'a Gönder", type="primary", use_container_width=True):
                    # Watchdog'un okuması için lokal orders.json'u da güncelle
                    order_mgr.save_orders(orders)

                    jsx = JSXTrigger()
                    with st.spinner(f"{len(orders)} sipariş Illustrator'a gönderiliyor..."):
                        result = jsx.trigger_batch(orders)

                    if result["success"]:
                        with st.spinner("Sheets güncelleniyor..."):
                            for order in orders:
                                sc.mark_processed(str(order["order_item_id"]))
                                # Manuel olmayanları lokal processed_orders.txt'e de yaz
                                order_mgr.mark_processed(
                                    str(order["order_item_id"]),
                                    bool(order.get("is_manual", False)),
                                )
                        st.success(
                            f"{len(orders)} sipariş Illustrator'a gönderildi "
                            "ve kuyruktan çıkarıldı."
                        )
                        if result["output"]:
                            st.code(result["output"])
                        st.rerun()
                    else:
                        st.error(f"Gönderim başarısız: {result['error']}")
                        if result["output"]:
                            st.code(result["output"])

            with col_dry:
                if st.button("🧪 Test Et (Dry-Run)", type="secondary", use_container_width=True):
                    lines = []
                    for order in orders:
                        pt   = detect_product_type(order["sku"])
                        font = resolve_font(pt, order.get("font_option", "SERIF"))
                        lines.append(
                            f"• [{order['order_item_id']}] SKU={order['sku']} "
                            f"→ tip={pt} font={font} renk={order.get('color_option','?')} "
                            f"isim={order.get('name','?')} "
                            f"{'[MANUEL]' if order.get('is_manual') else ''}"
                        )
                    jsx = JSXTrigger()
                    lines.append(f"\nJSX script: {jsx.jsx_path}")
                    st.info("**Dry-Run — JSX tetiklenmedi:**\n\n" + "\n".join(lines))

            st.divider()
            st.write("**Sipariş Sil:**")
            del_id = st.text_input("Order Item ID girin", key="del_id")
            if st.button("🗑️ Sil", type="secondary"):
                if del_id.strip():
                    if sc.remove_from_queue(del_id.strip()):
                        st.success(f"{del_id} kuyruktan silindi.")
                        st.rerun()
                    else:
                        st.error("Bu ID kuyrukta bulunamadı.")
                else:
                    st.warning("Bir ID girin.")


# ──────────────────────────────────────────────────────────────────────────────
# TAB 3: DASHBOARD
# ──────────────────────────────────────────────────────────────────────────────
with tab_dashboard:
    st.subheader("Dashboard")

    if not sc:
        st.error("Google Sheets bağlantısı yok.")
    else:
        with st.spinner("Veriler yükleniyor..."):
            orders  = sc.get_queue()
            counts  = sc.row_counts()

        col1, col2, col3 = st.columns(3)
        col1.metric("Kuyrukta",       counts["queue"])
        col2.metric("Toplam İşlenen", counts["log"])
        col3.metric("Manuel Sipariş", sum(1 for o in orders if o.get("is_manual")))

        if orders:
            st.divider()
            product_counts: dict[str, int] = {}
            sku_counts: dict[str, int] = {}
            for o in orders:
                pt = detect_product_type(o["sku"])
                product_counts[pt] = product_counts.get(pt, 0) + 1
                sku_counts[o["sku"]] = sku_counts.get(o["sku"], 0) + 1

            col_chart, col_sku = st.columns(2)
            with col_chart:
                st.write("**Ürün Tipi Dağılımı (Kuyruk)**")
                st.bar_chart(product_counts)
            with col_sku:
                st.write("**SKU Dağılımı (Kuyruk)**")
                st.dataframe(
                    pd.DataFrame([
                        {"SKU": k, "Adet": v}
                        for k, v in sorted(sku_counts.items(), key=lambda x: -x[1])
                    ]),
                    use_container_width=True,
                )

        st.divider()
        st.write("**Son İşlenen Siparişler (Log sheet)**")
        with st.spinner("Log yükleniyor..."):
            log_rows = sc.get_log()
        if log_rows:
            recent = log_rows[-20:][::-1]
            st.dataframe(
                pd.DataFrame([{
                    "Order Item ID": r.get("order_item_id", ""),
                    "SKU":           r.get("sku", ""),
                    "İsim":          r.get("name", ""),
                    "İşlenme":       r.get("processed_at", ""),
                } for r in recent]),
                use_container_width=True,
            )
        else:
            st.info("Henüz işlenmiş sipariş yok.")


# ──────────────────────────────────────────────────────────────────────────────
# TAB 4: ADMIN
# ──────────────────────────────────────────────────────────────────────────────
with tab_admin:
    st.subheader("Admin Paneli")

    # ── Secrets debug ──────────────────────────────────────────────────────
    with st.expander("🔍 Secrets Debug", expanded=True):
        st.write("Secrets keys:", list(st.secrets.keys()))
        if "gcp_service_account" in st.secrets:
            st.write("gcp_service_account found")
        else:
            st.warning("gcp_service_account bulunamadı")
        if "GOOGLE_SHEETS_SPREADSHEET_ID" in st.secrets:
            st.write("SPREADSHEET_ID found:", st.secrets["GOOGLE_SHEETS_SPREADSHEET_ID"])
        else:
            st.warning("GOOGLE_SHEETS_SPREADSHEET_ID bulunamadı")
    # ── /Secrets debug ─────────────────────────────────────────────────────

    # Bağlantı durumu
    st.write("### Bağlantı Durumu")
    if sc:
        st.success("Google Sheets bağlantısı aktif")
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "—")
        st.write(f"**Spreadsheet ID:** `{spreadsheet_id}`")
        st.write(f"**Queue sheet:** `{os.getenv('GOOGLE_SHEETS_QUEUE_SHEET', 'Queue')}`")
        st.write(f"**Log sheet:** `{os.getenv('GOOGLE_SHEETS_LOG_SHEET', 'Log')}`")
    else:
        err = st.session_state.get("sheets_error", "Bilinmeyen hata")
        st.error(f"Bağlantı hatası: {err}")
        st.write("Kontrol et:")
        st.code(
            "GOOGLE_SHEETS_CREDENTIALS=credentials.json\n"
            "GOOGLE_SHEETS_SPREADSHEET_ID=<id>\n"
            "GOOGLE_SHEETS_QUEUE_SHEET=Queue\n"
            "GOOGLE_SHEETS_LOG_SHEET=Log"
        )

    st.divider()

    # İstatistikler
    st.write("### Sheet İstatistikleri")
    if sc:
        col1, col2, col3 = st.columns(3)
        with st.spinner("Sayılar alınıyor..."):
            counts = sc.row_counts()
        col1.metric("Queue Satır Sayısı", counts["queue"])
        col2.metric("Log Satır Sayısı",   counts["log"])
        col3.metric(
            "Son Yükleme",
            st.session_state.get("last_upload", "—"),
        )

    st.divider()

    # Bağlantı testi
    st.write("### Bağlantı Testi")
    if st.button("🔌 Bağlantıyı Yeniden Test Et"):
        _get_sheets_client.clear()
        st.session_state.pop("sheets_error", None)
        st.rerun()

    # Tehlikeli işlemler
    st.divider()
    st.write("### Tehlikeli İşlemler")
    with st.expander("⚠️ Queue'yu Temizle"):
        st.warning("Bu işlem Queue sheet'indeki TÜM aktif siparişleri siler. Geri alınamaz.")
        if st.button("Kuyruğu Temizle", type="secondary"):
            if sc:
                n = sc.clear_queue()
                st.success(f"{n} satır silindi.")
                st.rerun()
            else:
                st.error("Bağlantı yok.")
