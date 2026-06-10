"""
web/listing_approval.py
=======================
Two-role listing approval system backed by Supabase.

Staff  — submit listings, view own history.
Admin  — PIN-protected review panel (approve / request revision).
"""

import os
import time
import uuid
from datetime import datetime

import streamlit as st
from supabase import create_client, Client

# ── Supabase client ───────────────────────────────────────────────────────────

SUPABASE_URL = "https://xauewoxqtytposeytelb.supabase.co"
SUPABASE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhhdWV3b3hxdHl0cG9zZXl0ZWxiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODExMDU2NDQsImV4cCI6MjA5NjY4MTY0NH0"
    ".-rm9Nd62fcXyKy5rtm26mQXpgzAZAVNnrqaGMUsQR-c"
)
STORAGE_BUCKET = "listing-images"
ADMIN_PIN = "1234"

STAFF_ACCOUNTS = {
    "Staff1": "Staff1.2025",
    "Staff2": "Staff2.2025",
    "Staff3": "Staff3.2025",
}


@st.cache_resource
def _get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL", SUPABASE_URL)
    key = os.getenv("SUPABASE_ANON_KEY", SUPABASE_KEY)
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_ANON_KEY"]
    except Exception:
        pass
    return create_client(url, key)


def _sb() -> Client:
    return _get_supabase()


# ── Helpers ───────────────────────────────────────────────────────────────────

STATUS_COLORS = {
    "pending":  ("#f59e0b", "⏳"),
    "approved": ("#10b981", "✅"),
    "revision": ("#ef4444", "🔄"),
}


def _badge(status: str) -> str:
    color, icon = STATUS_COLORS.get(status, ("#6b7280", "❓"))
    label = status.capitalize()
    return (
        f'<span style="background:{color}22;color:{color};border:1px solid {color}55;'
        f'border-radius:6px;padding:2px 10px;font-size:0.78rem;font-weight:600;">'
        f"{icon} {label}</span>"
    )


def _upload_image(file) -> str | None:
    """Upload image to Supabase Storage, return public URL."""
    ext = file.name.rsplit(".", 1)[-1].lower()
    path = f"{uuid.uuid4()}.{ext}"
    try:
        _sb().storage.from_(STORAGE_BUCKET).upload(
            path, file.read(), {"content-type": file.type}
        )
        res = _sb().storage.from_(STORAGE_BUCKET).get_public_url(path)
        return res
    except Exception as e:
        st.error(f"Image upload failed: {e}")
        return None


def _fetch_listings(status_filter: str | None = None) -> list[dict]:
    try:
        q = _sb().table("listings").select("*").order("created_at", desc=True)
        if status_filter:
            q = q.eq("status", status_filter)
        return q.execute().data or []
    except Exception as e:
        st.error(f"Failed to load listings: {e}")
        return []


def _fetch_my_listings(submitted_by: str) -> list[dict]:
    try:
        return (
            _sb().table("listings")
            .select("*")
            .eq("submitted_by", submitted_by)
            .order("created_at", desc=True)
            .execute()
            .data or []
        )
    except Exception as e:
        st.error(f"Failed to load your listings: {e}")
        return []


# ── Staff login ───────────────────────────────────────────────────────────────

def _render_staff_login() -> None:
    st.markdown("#### Staff Girişi")
    username = st.selectbox("Kullanıcı", list(STAFF_ACCOUNTS.keys()), key="staff_login_user")
    password = st.text_input("Şifre", type="password", key="staff_login_pwd")
    if st.button("Giriş Yap", type="primary"):
        if STAFF_ACCOUNTS.get(username) == password:
            st.session_state["listing_staff_user"] = username
            st.session_state.pop(f"my_listings_{username}", None)
            st.rerun()
        else:
            st.error("Hatalı şifre.")


# ── Staff view ────────────────────────────────────────────────────────────────

def _render_staff() -> None:
    # ── Giriş kontrolü ────────────────────────────────────────────────────────
    if not st.session_state.get("listing_staff_user"):
        _render_staff_login()
        return

    username = st.session_state["listing_staff_user"]

    col_title, col_logout = st.columns([5, 1])
    with col_title:
        st.markdown(f"#### Hoş geldin, **{username}** 👋")
    with col_logout:
        if st.button("Çıkış", key="staff_logout"):
            st.session_state.pop("listing_staff_user", None)
            st.rerun()

    st.markdown("#### Submit a New Listing")

    with st.form("listing_form", clear_on_submit=True):
        title = st.text_input("Title *", placeholder="Max 200 characters", max_chars=200)
        image_file = st.file_uploader("Product Image", type=["jpg", "jpeg", "png", "webp"])

        st.markdown("**Bullet Points**")
        bullets = []
        for i in range(1, 6):
            bullets.append(st.text_input(f"Bullet {i}", key=f"bullet_{i}"))

        description = st.text_area("Description", placeholder="Max 2000 characters", max_chars=2000, height=150)
        keywords = st.text_input("Keywords", placeholder="Max 500 characters", max_chars=500)

        submitted = st.form_submit_button("📤 Submit for Review", type="primary", use_container_width=True)

    if submitted:
        if not title.strip():
            st.error("Title is required.")
            return

        image_url = None
        if image_file:
            with st.spinner("Uploading image…"):
                image_url = _upload_image(image_file)
            if image_file and not image_url:
                return  # upload error already shown

        row = {
            "submitted_by": username,
            "title":        title.strip(),
            "bullet_1":     bullets[0].strip(),
            "bullet_2":     bullets[1].strip(),
            "bullet_3":     bullets[2].strip(),
            "bullet_4":     bullets[3].strip(),
            "bullet_5":     bullets[4].strip(),
            "description":  description.strip(),
            "keywords":     keywords.strip(),
            "image_url":    image_url or "",
            "status":       "pending",
            "admin_note":   "",
        }
        try:
            _sb().table("listings").insert(row).execute()
            st.success("✅ Listing submitted successfully!")
            st.session_state.pop(f"my_listings_{username}", None)
        except Exception as e:
            st.error(f"Submission failed: {e}")
            return

    # ── Submission history ────────────────────────────────────────────────────
    st.divider()
    st.markdown("#### My Submission History")

    cache_key = f"my_listings_{username}"
    if st.button("🔄 Refresh", key="refresh_staff"):
        st.session_state.pop(cache_key, None)

    if cache_key not in st.session_state:
        st.session_state[cache_key] = _fetch_my_listings(username)

    listings = st.session_state[cache_key]
    if not listings:
        st.info("No submissions found.")
        return

    for lst in listings:
        lid = lst["id"]
        with st.container():
            col_info, col_badge, col_del = st.columns([5, 1, 1])
            with col_info:
                st.markdown(f"**{lst.get('title', '—')}**")
                date_str = str(lst.get("created_at", ""))[:10]
                st.caption(f"Submitted {date_str}")
            with col_badge:
                st.markdown(_badge(lst.get("status", "pending")), unsafe_allow_html=True)
            with col_del:
                if st.button("🗑️", key=f"del_{lid}", help="Bu kaydı sil"):
                    try:
                        res = _sb().table("listings").delete().eq("id", lid).execute()
                        if res.data is not None:
                            st.session_state.pop(cache_key, None)
                            st.rerun()
                        else:
                            st.error("Silme başarısız — Supabase izin vermedi.")
                    except Exception as e:
                        st.error(f"Silinemedi: {e}")

            if lst.get("admin_note"):
                st.warning(f"📝 Admin note: {lst['admin_note']}")

            with st.expander("View details"):
                if lst.get("image_url"):
                    st.image(lst["image_url"], width=200)
                for i in range(1, 6):
                    b = lst.get(f"bullet_{i}", "")
                    if b:
                        st.markdown(f"• {b}")
                if lst.get("description"):
                    st.markdown(lst["description"])
                if lst.get("keywords"):
                    st.caption(f"Keywords: {lst['keywords']}")
            st.markdown("---")


# ── Admin view ────────────────────────────────────────────────────────────────

def _render_admin() -> None:
    # PIN check
    if not st.session_state.get("listing_admin_auth"):
        st.markdown("#### Admin Access")
        pin = st.text_input("Enter Admin PIN", type="password", key="listing_pin")
        if st.button("Unlock", type="primary"):
            if pin == ADMIN_PIN:
                st.session_state["listing_admin_auth"] = True
                st.rerun()
            else:
                st.error("Incorrect PIN.")
        return

    col_title, col_logout = st.columns([5, 1])
    with col_title:
        st.markdown("#### Listing Review Panel")
    with col_logout:
        if st.button("Lock", key="listing_lock"):
            st.session_state["listing_admin_auth"] = False
            st.rerun()

    # Filter
    filter_cols = st.columns(4)
    filters = ["All", "Pending", "Approved", "Revision"]
    for i, f in enumerate(filters):
        if filter_cols[i].button(f, use_container_width=True, key=f"filter_{f}"):
            st.session_state["listing_filter"] = f.lower() if f != "All" else None
            st.session_state.pop("admin_listings_cache", None)

    active_filter = st.session_state.get("listing_filter", None)

    col_r, _ = st.columns([1, 5])
    with col_r:
        if st.button("🔄 Refresh", key="refresh_admin"):
            st.session_state.pop("admin_listings_cache", None)

    if "admin_listings_cache" not in st.session_state:
        st.session_state["admin_listings_cache"] = _fetch_listings(active_filter)

    listings = st.session_state["admin_listings_cache"]

    if not listings:
        st.info("No listings found.")
        return

    # Current filter label
    label = active_filter.capitalize() if active_filter else "All"
    st.caption(f"Showing: **{label}** — {len(listings)} listing(s)")
    st.divider()

    for lst in listings:
        lid = lst["id"]
        status = lst.get("status", "pending")

        with st.container():
            h_col, b_col = st.columns([5, 1])
            with h_col:
                st.markdown(f"**{lst.get('title', '—')}**")
                st.caption(
                    f"By {lst.get('submitted_by', '?')}  ·  "
                    f"{str(lst.get('created_at', ''))[:10]}"
                )
            with b_col:
                st.markdown(_badge(status), unsafe_allow_html=True)

            detail_cols = st.columns([1, 2])
            with detail_cols[0]:
                if lst.get("image_url"):
                    st.image(lst["image_url"], use_container_width=True)
                else:
                    st.caption("No image")

            with detail_cols[1]:
                for i in range(1, 6):
                    b = lst.get(f"bullet_{i}", "")
                    if b:
                        st.markdown(f"• {b}")
                if lst.get("description"):
                    with st.expander("Description"):
                        st.write(lst["description"])
                if lst.get("keywords"):
                    st.caption(f"🔑 {lst['keywords']}")
                if lst.get("admin_note"):
                    st.info(f"Previous note: {lst['admin_note']}")

            # Actions
            act_cols = st.columns([1, 2, 1])
            with act_cols[0]:
                if st.button("✅ Approve", key=f"approve_{lid}", type="primary", use_container_width=True):
                    try:
                        _sb().table("listings").update({
                            "status": "approved",
                            "admin_note": "",
                            "reviewed_at": datetime.utcnow().isoformat(),
                        }).eq("id", lid).execute()
                        st.session_state.pop("admin_listings_cache", None)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

            with act_cols[1]:
                with st.expander("🔄 Request Revision"):
                    note = st.text_area("Revision note *", key=f"note_{lid}", height=80)
                    if st.button("Send", key=f"send_rev_{lid}", type="secondary", use_container_width=True):
                        if not note.strip():
                            st.error("Note is required.")
                        else:
                            try:
                                _sb().table("listings").update({
                                    "status": "revision",
                                    "admin_note": note.strip(),
                                    "reviewed_at": datetime.utcnow().isoformat(),
                                }).eq("id", lid).execute()
                                st.session_state.pop("admin_listings_cache", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

        st.markdown("---")


# ── Entry point ───────────────────────────────────────────────────────────────

def render_listing_approval() -> None:
    """Call this from app.py inside the Listing Approval tab."""
    st.markdown("""
    <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:1rem;">
        <span style="font-size:1.4rem;">📝</span>
        <div>
            <div style="font-size:1.1rem;font-weight:700;">Listing Approval</div>
            <div style="font-size:0.75rem;color:#8b92a5;">Submit & review Amazon product listings</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    mode = st.radio(
        "Mode", ["Staff — Submit Listing", "Admin — Review Listings"],
        horizontal=True, label_visibility="collapsed",
        key="listing_mode"
    )

    st.divider()

    if mode == "Staff — Submit Listing":
        _render_staff()
    else:
        _render_admin()
