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

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── Base ── */
html, body, [class*="css"], .stApp {
    font-family: 'Inter', sans-serif !important;
    background-color: #0e1117 !important;
}
.block-container {
    padding-top: 1.8rem !important;
    padding-bottom: 2rem !important;
    max-width: 1200px;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] > div:first-child {
    background: linear-gradient(180deg, #111827 0%, #0e1117 100%) !important;
    border-right: 1px solid #1f2937 !important;
}
section[data-testid="stSidebar"] .stButton > button {
    background: #1f2937 !important;
    color: #d1d5db !important;
    border: 1px solid #374151 !important;
    border-radius: 8px !important;
    font-size: 0.85rem !important;
    padding: 0.45rem 1rem !important;
    transition: all 0.2s !important;
    width: 100% !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: #374151 !important;
    border-color: #4a90d9 !important;
    color: #fff !important;
}

/* ── Tab'lar ── */
.stTabs [data-baseweb="tab-list"] {
    background: #161b27 !important;
    border-radius: 10px !important;
    padding: 4px !important;
    gap: 2px !important;
    border: 1px solid #1f2937 !important;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px !important;
    font-weight: 500 !important;
    font-size: 0.88rem !important;
    color: #9ca3af !important;
    padding: 0.5rem 1.2rem !important;
    transition: all 0.2s !important;
    border: none !important;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #1d4ed8, #4a90d9) !important;
    color: #fff !important;
    box-shadow: 0 2px 8px rgba(74,144,217,0.4) !important;
}

/* ── Primary buton ── */
.stButton > button[kind="primary"],
button[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, #1d4ed8, #4a90d9) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    padding: 0.55rem 1.4rem !important;
    box-shadow: 0 2px 8px rgba(74,144,217,0.3) !important;
    transition: all 0.2s !important;
}
.stButton > button[kind="primary"]:hover,
button[data-testid="baseButton-primary"]:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 16px rgba(74,144,217,0.45) !important;
    background: linear-gradient(135deg, #2563eb, #60a5fa) !important;
}

/* ── Secondary buton ── */
.stButton > button[kind="secondary"],
button[data-testid="baseButton-secondary"] {
    background: #1f2937 !important;
    color: #d1d5db !important;
    border: 1px solid #374151 !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    transition: all 0.2s !important;
}
.stButton > button[kind="secondary"]:hover {
    background: #374151 !important;
    border-color: #6b7280 !important;
    color: #fff !important;
}

/* ── Metric kartları ── */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #161b27, #1a2035) !important;
    border: 1px solid #1f2937 !important;
    border-radius: 12px !important;
    padding: 1.2rem 1.4rem !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.3) !important;
    transition: transform 0.2s !important;
}
[data-testid="stMetric"]:hover { transform: translateY(-2px) !important; }
[data-testid="stMetricValue"] {
    font-size: 2.2rem !important;
    font-weight: 700 !important;
    background: linear-gradient(135deg, #60a5fa, #4a90d9);
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.75rem !important;
    color: #6b7280 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.8px !important;
    font-weight: 600 !important;
}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
    border-radius: 10px !important;
    overflow: hidden !important;
    border: 1px solid #1f2937 !important;
}

/* ── File uploader ── */
[data-testid="stFileUploader"] > div {
    border: 2px dashed #374151 !important;
    border-radius: 12px !important;
    background: #161b27 !important;
    transition: all 0.25s !important;
}
[data-testid="stFileUploader"] > div:hover {
    border-color: #4a90d9 !important;
    background: #1a2035 !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    border: 1px solid #1f2937 !important;
    border-radius: 10px !important;
    background: #161b27 !important;
    overflow: hidden !important;
}
[data-testid="stExpander"] summary {
    font-weight: 500 !important;
    color: #d1d5db !important;
}

/* ── Input alanları ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div {
    background: #1f2937 !important;
    border: 1px solid #374151 !important;
    border-radius: 8px !important;
    color: #f3f4f6 !important;
    transition: border-color 0.2s !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #4a90d9 !important;
    box-shadow: 0 0 0 2px rgba(74,144,217,0.2) !important;
}

/* ── Divider ── */
hr { border-color: #1f2937 !important; margin: 1rem 0 !important; }

/* ── Success/Error/Info ── */
[data-testid="stAlert"] { border-radius: 10px !important; border-left-width: 4px !important; }

/* ── Spinner ── */
.stSpinner > div { border-top-color: #4a90d9 !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0e1117; }
::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #4a90d9; }
</style>
""", unsafe_allow_html=True)


# ── Şifre kontrolü ───────────────────────────────────────────────────────────
def _check_auth() -> bool:
    return st.session_state.get("authenticated", False)


def _render_login_sidebar() -> None:
    st.sidebar.markdown("### 🔐 Giriş")
    pwd = st.sidebar.text_input("Şifre", type="password", key="pwd_input", label_visibility="collapsed", placeholder="Şifrenizi girin")
    if st.sidebar.button("Giriş Yap", use_container_width=True):
        if ADMIN_PASSWORD and pwd == ADMIN_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.sidebar.error("Hatalı şifre.")


def _render_login_page() -> None:
    """Giriş yapılmamışsa sayfa ortasında login kartı göster."""
    st.markdown("""
    <div style="
        max-width: 400px;
        margin: 6rem auto 0 auto;
        background: #1a1d2e;
        border: 1px solid #2d3147;
        border-radius: 14px;
        padding: 2.5rem 2rem;
        text-align: center;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    ">
        <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">🖨️</div>
        <div style="font-size: 1.4rem; font-weight: 700; color: #f0f2f6; margin-bottom: 0.3rem;">AutoPrint Enterprise</div>
        <div style="font-size: 0.85rem; color: #8b92a5; margin-bottom: 2rem;">Yönetim Paneli</div>
    </div>
    """, unsafe_allow_html=True)


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
            "Sipariş Tarihi": o.get("order_date", ""),
            "Hesap":       o.get("seller_name", ""),
            "Fiyat ($)":   o.get("item_price", 0.0),
            "Kargo ($)":   o.get("shipping_fee", 0.0),
            "Gift Box":    "✓" if o.get("gift_box") else "✗",
            "Manuel":      "✓" if o.get("is_manual") else "",
        })
    return pd.DataFrame(rows)


def _validate_manual(sku) -> list[str]:
    errors = []
    if not sku.strip(): errors.append("SKU zorunlu.")
    return errors


# ── Sidebar başlık ───────────────────────────────────────────────────────────
st.sidebar.markdown("""
<div style="padding: 0.8rem 0 1.2rem 0; border-bottom: 1px solid #2d3147; margin-bottom: 1rem;">
    <div style="font-size: 1.1rem; font-weight: 700; letter-spacing: 0.3px;">🖨️ AutoPrint</div>
    <div style="font-size: 0.72rem; color: #8b92a5; margin-top: 2px;">Enterprise Panel</div>
</div>
""", unsafe_allow_html=True)

authenticated = _check_auth()

if not authenticated:
    _render_login_page()
    _render_login_sidebar()
else:
    st.sidebar.markdown(f"""
    <div style="font-size: 0.78rem; color: #8b92a5; margin-bottom: 0.8rem;">
        Hoş geldin 👋
    </div>
    """, unsafe_allow_html=True)
    if st.sidebar.button("Çıkış Yap", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

st.sidebar.markdown("<div style='margin-top:1rem;border-top:1px solid #2d3147;padding-top:1rem;'></div>", unsafe_allow_html=True)

sc = _sheets()
if sc:
    st.sidebar.markdown("🟢 &nbsp;**Google Sheets bağlı**", unsafe_allow_html=True)
else:
    err = st.session_state.get("sheets_error", "Bilinmeyen hata")
    st.sidebar.error(f"Sheets bağlantısı yok:\n{err}")

# ── Sayfa başlığı (giriş yapılmışsa) ─────────────────────────────────────────
if authenticated:
    st.markdown("""
    <div style="display:flex; align-items:center; gap:0.8rem; margin-bottom:1rem;">
        <span style="font-size:1.8rem;">🖨️</span>
        <div>
            <div style="font-size:1.5rem; font-weight:700; line-height:1.2;">AutoPrint Enterprise</div>
            <div style="font-size:0.8rem; color:#8b92a5;">Sipariş Yönetim Paneli</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

if "last_result" in st.session_state:
    r = st.session_state["last_result"]
    if r.get("success"):
        msg = f"Son gönderim başarılı — {r.get('moved', 0)} sipariş işlendi."
        if r.get("not_found"):
            msg += f" Bulunamayan ID'ler: {', '.join(r['not_found'])}"
        st.info(msg)
    else:
        st.warning(f"Son gönderim başarısız: {r.get('error', '?')}")
    if r.get("returncode") is not None:
        st.caption(f"osascript return code: {r['returncode']}")
    if r.get("output"):
        with st.expander("osascript çıktısı"):
            st.code(r["output"], language=None)
    if r.get("stderr"):
        with st.expander("osascript stderr"):
            st.code(r["stderr"], language=None)

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

            col_add, col_backfill = st.columns(2)

            with col_backfill:
                if st.button("🔄 Log'u Güncelle (Backfill)", type="secondary", use_container_width=True):
                    if sc:
                        with st.spinner("Log satırları güncelleniyor..."):
                            result = sc.backfill_log_fields(
                                all_parsed,
                                fields=["order_date", "item_price", "shipping_fee", "gift_box", "seller_name"]
                            )
                        st.success(f"{result['updated']} satır güncellendi, {result['not_found']} bulunamadı.")
                    else:
                        st.error("Google Sheets bağlantısı yok.")

            with col_add:
                if st.button("✅ Kuyruğa Ekle", type="primary", use_container_width=True):
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
                m_order_id      = st.text_input("Order ID", placeholder="123-4567890-1234567")
                m_order_item_id = st.text_input("Order Item ID", placeholder="12345678901234")
                m_sku           = st.text_input("SKU *", placeholder="CRMC1246")
                m_qty           = st.number_input("Adet", min_value=1, max_value=99, value=1)
                m_year          = st.text_input("Yıl", placeholder="2024")
                m_message       = st.text_area("Mesaj", height=80)
            with col2:
                m_font  = st.selectbox("Font", ["SERIF", "SANS", "SCRIPT", "WELCOME"])
                m_color = st.selectbox("Renk", ["BLACK", "WHITE", "GOLD", "RED", "SILVER", "IVORY"])
                st.markdown("**İsimler**")
                m_names = []
                for n in range(1, 11):
                    label = "İsim" if n == 1 else f"İsim {n}"
                    m_names.append(st.text_input(label, key=f"m_name_{n}"))
            with col3:
                pass

            submitted = st.form_submit_button("Ekle")

        if submitted:
            errors = _validate_manual(m_sku)
            if errors:
                for e in errors:
                    st.error(e)
            elif not sc:
                st.error("Google Sheets bağlantısı yok.")
            else:
                order = {
                    "order_id":       m_order_id.strip() or f"MANUAL-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    "order_item_id":  m_order_item_id.strip() or f"M-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                    "sku":            m_sku.strip(),
                    "qty":            int(m_qty),
                    "name":           m_names[0].strip(),
                    "year":           m_year.strip(),
                    "message":        m_message.strip(),
                    "font_option":    m_font,
                    "color_option":   m_color,
                    "is_manual":      True,
                }
                for i, name_val in enumerate(m_names[1:], start=2):
                    if name_val.strip():
                        order[f"name{i}"] = name_val.strip()

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
            st.session_state["queue_orders"] = sc.get_queue()

        orders = st.session_state.get("queue_orders", [])

        if not orders:
            st.info("Kuyruk boş.")
        else:
            st.dataframe(_orders_to_df(orders), use_container_width=True)
            unknown = [o["sku"] for o in orders if detect_product_type(o.get("sku","")) == "unknown"]
            if unknown:
                st.warning(f"⚠️ Template bulunamayan SKU'lar (işlenmeyecek): {', '.join(set(unknown))}")
            st.divider()

            col_send, col_dry = st.columns(2)

            with col_send:
                if st.button("🖨️ Illustrator'a Gönder", type="primary", use_container_width=True):
                    orders = st.session_state.get("queue_orders", [])
                    # Watchdog'un okuması için lokal orders.json'u da güncelle
                    order_mgr.save_orders(orders)

                    jsx = JSXTrigger()
                    with st.spinner(f"{len(orders)} sipariş Illustrator'a gönderiliyor..."):
                        result = jsx.trigger_batch(orders)

                    if result["success"]:
                        with st.spinner("Sheets güncelleniyor..."):
                            item_ids = [str(o["order_item_id"]) for o in orders]
                            batch_result = sc.mark_processed_batch(item_ids)
                            for order in orders:
                                order_mgr.mark_processed(
                                    str(order["order_item_id"]),
                                    bool(order.get("is_manual", False)),
                                )
                        st.session_state["last_result"] = {
                            "success": True,
                            "moved": batch_result["moved"],
                            "not_found": batch_result["not_found"],
                            "returncode": result["returncode"],
                            "output": result["output"],
                            "stderr": result["error"],
                        }
                        st.session_state.pop("queue_orders", None)
                    else:
                        st.session_state["last_result"] = {
                            "success": False,
                            "error": result["error"],
                            "returncode": result["returncode"],
                            "output": result["output"],
                            "stderr": result["error"],
                        }
                    st.rerun()

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
            queue_orders = sc.get_queue()
            log_rows     = sc.get_log()
            costs_map    = sc.get_costs()

        # ── Tarih filtresi ───────────────────────────────────────────────────
        from datetime import date, timedelta
        filter_col, _ = st.columns([2, 4])
        with filter_col:
            date_filter = st.selectbox(
                "Dönem", ["Tüm Zamanlar", "Bu Ay", "Bu Hafta", "Bugün"],
                key="dash_date_filter", label_visibility="collapsed"
            )
        today = date.today()
        if date_filter == "Bu Hafta":
            cutoff = today - timedelta(days=today.weekday())
        elif date_filter == "Bu Ay":
            cutoff = today.replace(day=1)
        elif date_filter == "Bugün":
            cutoff = today
        else:
            cutoff = None

        def _in_range(row: dict) -> bool:
            if cutoff is None:
                return True
            proc = str(row.get("processed_at", "") or "")[:10]
            try:
                return date.fromisoformat(proc) >= cutoff
            except ValueError:
                return True

        filtered_log = [r for r in log_rows if _in_range(r)]

        # ── Üst metrikler ───────────────────────────────────────────────────
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Kuyrukta",        len(queue_orders))
        col2.metric("Toplam İşlenen",  len(filtered_log))

        total_revenue  = sum(float(r.get("item_price", 0) or 0) for r in filtered_log)
        total_shipping = sum(float(r.get("shipping_fee", 0) or 0) for r in filtered_log)
        col3.metric("Toplam Ciro",     f"${total_revenue:,.2f}")
        col4.metric("Toplam Kargo",    f"${total_shipping:,.2f}")

        col5, col6, col7, col8 = st.columns(4)
        gift_count = sum(1 for r in filtered_log if r.get("gift_box"))
        gift_pct   = (gift_count / len(filtered_log) * 100) if filtered_log else 0.0
        col5.metric("Gift Box",        f"{gift_count}  ({gift_pct:.0f}%)")
        col6.metric("Manuel Sipariş",  sum(1 for r in filtered_log if r.get("is_manual")))

        nonzero_prices = [float(r.get("item_price", 0) or 0) for r in filtered_log if float(r.get("item_price", 0) or 0) > 0]
        avg_price = sum(nonzero_prices) / len(nonzero_prices) if nonzero_prices else 0.0
        col7.metric("Ort. Sipariş Değeri", f"${avg_price:.2f}")
        col8.metric("Toplam Gelir",        f"${total_revenue + total_shipping:,.2f}")

        st.divider()

        # ── SKU Kârlılık Tablosu ────────────────────────────────────────────
        if filtered_log:
            st.markdown("#### SKU Satış & Kâr Analizi")

            sku_stats: dict[str, dict] = {}
            for r in filtered_log:
                sku = r.get("sku", "")
                if not sku:
                    continue
                if sku not in sku_stats:
                    sku_stats[sku] = {"qty": 0, "revenue": 0.0, "gift_count": 0}
                sku_stats[sku]["qty"]        += int(r.get("qty", 1) or 1)
                sku_stats[sku]["revenue"]    += float(r.get("item_price", 0) or 0)
                sku_stats[sku]["gift_count"] += 1 if r.get("gift_box") else 0

            profit_rows = []
            for sku, stat in sorted(sku_stats.items(), key=lambda x: -x[1]["revenue"]):
                cost      = costs_map.get(sku, None)
                revenue   = stat["revenue"]
                total_cost = cost * stat["qty"] if cost is not None else None
                profit    = revenue - total_cost if total_cost is not None else None
                margin    = (profit / revenue * 100) if (profit is not None and revenue > 0) else None
                profit_rows.append({
                    "SKU":          sku,
                    "Adet":         stat["qty"],
                    "Ciro ($)":     round(revenue, 2),
                    "Gift Box":     stat["gift_count"],
                    "Birim Maliyet": f"${cost:.2f}" if cost is not None else "—",
                    "Toplam Maliyet": f"${total_cost:.2f}" if total_cost is not None else "—",
                    "Kar ($)":      round(profit, 2) if profit is not None else "—",
                    "Margin (%)":   f"{margin:.1f}%" if margin is not None else "—",
                })

            st.dataframe(pd.DataFrame(profit_rows), use_container_width=True)

        st.divider()

        # ── Hesaba Göre Satış ───────────────────────────────────────────────
        if filtered_log:
            seller_stats: dict[str, dict] = {}
            for r in filtered_log:
                sn = r.get("seller_name", "") or "Bilinmiyor"
                if sn not in seller_stats:
                    seller_stats[sn] = {"qty": 0, "revenue": 0.0}
                seller_stats[sn]["qty"]     += int(r.get("qty", 1) or 1)
                seller_stats[sn]["revenue"] += float(r.get("item_price", 0) or 0)

            if any(v["revenue"] > 0 or v["qty"] > 0 for v in seller_stats.values()):
                st.markdown("#### Hesaba Göre Satış")
                seller_df = pd.DataFrame([
                    {"Hesap": k, "Sipariş Adedi": v["qty"], "Ciro ($)": round(v["revenue"], 2)}
                    for k, v in sorted(seller_stats.items(), key=lambda x: -x[1]["revenue"])
                ])
                st.dataframe(seller_df, use_container_width=True)
                st.divider()

        # ── Ürün Tipi & Günlük Üretim ───────────────────────────────────────
        col_chart, col_daily = st.columns(2)

        with col_chart:
            st.markdown("#### Ürün Tipi Dağılımı")
            if filtered_log:
                pt_counts: dict[str, int] = {}
                for r in filtered_log:
                    pt = detect_product_type(r.get("sku", ""))
                    pt_counts[pt] = pt_counts.get(pt, 0) + 1
                st.bar_chart(pt_counts)
            else:
                st.info("Veri yok.")

        with col_daily:
            st.markdown("#### Günlük Üretim (İşlenme Tarihi)")
            if filtered_log:
                daily: dict[str, int] = {}
                for r in filtered_log:
                    proc = str(r.get("processed_at", "") or "")
                    if proc and len(proc) >= 10:
                        daily[proc[:10]] = daily.get(proc[:10], 0) + 1
                if daily:
                    st.bar_chart(pd.DataFrame(
                        sorted(daily.items(), key=lambda x: x[0])[-30:],
                        columns=["Tarih", "Adet"],
                    ).set_index("Tarih"))
                else:
                    st.info("Tarih verisi yok.")
            else:
                st.info("Veri yok.")

        st.divider()

        # ── Günlük Sipariş (Amazon Sipariş Tarihi) ──────────────────────────
        st.markdown("#### Günlük Sipariş (Amazon Sipariş Tarihi)")
        if filtered_log:
            order_daily: dict[str, int] = {}
            for r in filtered_log:
                od = str(r.get("order_date", "") or "")
                if od and len(od) >= 10:
                    order_daily[od[:10]] = order_daily.get(od[:10], 0) + 1
            if order_daily:
                st.bar_chart(pd.DataFrame(
                    sorted(order_daily.items(), key=lambda x: x[0])[-30:],
                    columns=["Tarih", "Sipariş"],
                ).set_index("Tarih"))
            else:
                st.info("Sipariş tarihi verisi yok. Yeni yüklenen siparişlerde görünecek.")
        else:
            st.info("Veri yok.")

        st.divider()

        # ── Maliyet Güncelleme Formu ─────────────────────────────────────────
        with st.expander("💰 SKU Maliyet Güncelle"):
            with st.form("cost_form"):
                c1, c2 = st.columns(2)
                cost_sku   = c1.text_input("SKU", placeholder="CRMC1246")
                cost_value = c2.number_input("Birim Maliyet ($)", min_value=0.0, step=0.01, format="%.2f")
                if st.form_submit_button("Kaydet"):
                    if cost_sku.strip():
                        sc.upsert_cost(cost_sku.strip(), float(cost_value))
                        st.success(f"{cost_sku.strip()} → ${cost_value:.2f} kaydedildi.")
                        _get_sheets_client.clear()
                        st.rerun()
                    else:
                        st.error("SKU boş olamaz.")

            if costs_map:
                st.dataframe(
                    pd.DataFrame([{"SKU": k, "Maliyet ($)": v} for k, v in sorted(costs_map.items())]),
                    use_container_width=True,
                )

        st.divider()

        # ── Son İşlenen Siparişler ──────────────────────────────────────────
        st.markdown("#### Son İşlenen Siparişler")
        if filtered_log:
            recent = filtered_log[-20:][::-1]
            st.dataframe(
                pd.DataFrame([{
                    "Order Item ID": r.get("order_item_id", ""),
                    "SKU":           r.get("sku", ""),
                    "İsim":          r.get("name", ""),
                    "Fiyat ($)":     r.get("item_price", ""),
                    "Gift Box":      "✓" if r.get("gift_box") else "",
                    "İşlenme":       r.get("processed_at", ""),
                } for r in recent]),
                use_container_width=True,
            )
        else:
            st.info("Seçilen dönemde işlenmiş sipariş yok.")


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

    with st.expander("🔧 Sheet Header'larını Sıfırla"):
        st.warning("Queue ve Log verilerini siler, sütun sıralarını QUEUE_COLUMNS ile birebir eşitler. Eski hatalı veriler temizlenir.")
        if st.button("Header'ları Sıfırla", type="secondary", key="btn_reset_headers"):
            if sc:
                from analytics.sheets import QUEUE_COLUMNS, LOG_COLUMNS
                sc.clear_queue()
                sc.clear_log()
                sc._queue.update([QUEUE_COLUMNS], "1:1")
                sc._log.update([LOG_COLUMNS], "1:1")
                _get_sheets_client.clear()
                st.session_state.pop("queue_orders", None)
                st.success("Header'lar sıfırlandı. Siparişleri yeniden yükleyin.")
                st.rerun()
            else:
                st.error("Bağlantı yok.")

    with st.expander("⚠️ Queue'yu Temizle"):
        st.warning("Queue sheet'indeki TÜM aktif siparişleri siler. Geri alınamaz.")
        if st.button("Kuyruğu Temizle", type="secondary", key="btn_clear_queue"):
            if sc:
                n = sc.clear_queue()
                st.success(f"{n} satır silindi.")
                st.rerun()
            else:
                st.error("Bağlantı yok.")

    with st.expander("⚠️ Log'u Temizle"):
        st.warning("Log sheet'indeki TÜM işlenmiş sipariş geçmişini siler. Geri alınamaz.")
        if st.button("Log'u Temizle", type="secondary", key="btn_clear_log"):
            if sc:
                n = sc.clear_log()
                st.success(f"{n} satır silindi.")
                st.rerun()
            else:
                st.error("Bağlantı yok.")

    with st.expander("⚠️ Tüm Geçmişi Temizle"):
        st.warning("Queue + Log sheet'leri, processed_orders.txt ve batches klasörü silinir. Geri alınamaz.")
        if st.button("Tüm Geçmişi Temizle", type="secondary", key="btn_clear_all"):
            if sc:
                cleared = {}
                cleared["queue"] = sc.clear_queue()
                cleared["log"] = sc.clear_log()

                # processed_orders.txt'i boşalt
                proc_path = Path(os.getenv(
                    "PROCESSED_TXT_PATH",
                    str(Path.home() / "Desktop/autoprint-enterprise/data/processed_orders.txt")
                ))
                if proc_path.exists():
                    proc_path.write_text("", encoding="utf-8")
                    cleared["processed_txt"] = True

                # batches klasörünü temizle
                import shutil
                batches_path = Path(os.getenv(
                    "BATCH_LOG_BASE",
                    str(Path.home() / "Desktop/autoprint-enterprise/data/batches")
                ))
                batch_count = 0
                if batches_path.exists():
                    for item in batches_path.iterdir():
                        if item.is_dir():
                            shutil.rmtree(item)
                            batch_count += 1
                cleared["batches"] = batch_count

                # session_state temizle
                st.session_state.pop("queue_orders", None)
                st.session_state.pop("last_result", None)
                st.session_state.pop("last_upload", None)

                st.success(
                    f"Temizlendi — Queue: {cleared['queue']} satır, "
                    f"Log: {cleared['log']} satır, "
                    f"Batches: {cleared['batches']} klasör, "
                    f"processed_orders.txt: {'boşaltıldı' if cleared.get('processed_txt') else 'bulunamadı'}"
                )
                st.rerun()
            else:
                st.error("Bağlantı yok.")
