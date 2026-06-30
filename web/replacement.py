"""
web/replacement.py
==================
Replacement sekmesi UI.
  Add Replacement      : şifresiz (Türkiye kullanır)
  Pending Replacements : ADMIN_PASSWORD gerekli (Headquarter)

Label PDF'ler Google Drive'da "AutoPrint Replacements" klasörüne kaydedilir.
"""

import io
import json
import re
import uuid
from datetime import datetime

import requests
import streamlit as st


# ── PDF → PNG dönüşümü ───────────────────────────────────────────────────────

def _pdf_to_png(pdf_bytes: bytes, dpi: int = 150) -> bytes | None:
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf_bytes)
        if len(doc) == 0:
            return None
        bitmap = doc[0].render(scale=dpi / 72)
        buf = io.BytesIO()
        bitmap.to_pil().save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        pass
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(pdf_bytes, dpi=dpi, first_page=1, last_page=1)
        if pages:
            buf = io.BytesIO()
            pages[0].save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        pass
    return None


# ── Personalization yardımcıları ─────────────────────────────────────────────

def _parse_persona(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if line.startswith("#"):
            parts = line[1:].split(":", 1)
            if len(parts) == 2:
                result[parts[0].strip()] = parts[1].strip()
    return result


def _persona_to_text(persona_json: str) -> str:
    try:
        return "\n".join(f"#{k}: {v}" for k, v in json.loads(persona_json).items())
    except Exception:
        return ""


# ── Drive URL'den PDF indir ───────────────────────────────────────────────────

@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_pdf_from_drive(drive_url: str) -> bytes | None:
    """Drive view URL'den PDF bytes indir (public file)."""
    match = re.search(r"/file/d/([^/]+)/", drive_url)
    if not match:
        return None
    file_id = match.group(1)
    try:
        resp = requests.get(
            f"https://drive.google.com/uc?export=download&id={file_id}",
            timeout=30,
            allow_redirects=True,
        )
        if resp.status_code == 200 and resp.content[:4] == b"%PDF":
            return resp.content
    except Exception:
        pass
    return None


# ── A4 PDF (cached) ───────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _cached_a4_pdf(
    sku: str,
    replacement_type: str,
    persona_json: str,
    created_at: str,
    drive_url: str,
) -> bytes:
    from core.label_merger import build_a4_pdf

    pdf_bytes = _fetch_pdf_from_drive(drive_url) if drive_url else None
    png_bytes = _pdf_to_png(pdf_bytes, dpi=120) if pdf_bytes else None
    return build_a4_pdf(sku, replacement_type, _persona_to_text(persona_json), created_at, png_bytes)


# ── Bölüm 1: Add Replacement ─────────────────────────────────────────────────

def _render_add(sc) -> None:
    st.markdown("#### Replacement Talebi Oluştur")

    label_file = st.file_uploader(
        "Label PDF (tek sayfa)", type=["pdf"], key="repl_label_pdf"
    )
    sku = st.text_input("SKU", key="repl_sku", placeholder="CRMC1246")
    persona_text = st.text_area(
        "Personalization",
        placeholder=(
            "#NAME: Alex\n"
            "#NAME_DAD: Michael\n"
            "#YEAR: 2026\n"
            "#MESSAGE: Merry Christmas\n"
            "#NOTE: gift box gönderilmemiş"
        ),
        height=170,
        key="repl_persona",
    )
    repl_type = st.selectbox(
        "Replacement Tipi",
        ["Tam Replacement", "Düzeltme", "Eksik Ürün", "Gift Box"],
        key="repl_type",
    )

    if st.button("Gönder", type="primary", key="repl_submit"):
        errors = []
        if not sku.strip():
            errors.append("SKU zorunludur.")
        if not label_file:
            errors.append("Label PDF zorunludur.")
        if not sc:
            errors.append("Google Sheets bağlantısı yok.")
        for e in errors:
            st.error(e)
        if errors:
            return

        pdf_bytes = label_file.read()
        png_bytes = _pdf_to_png(pdf_bytes)

        # Önizleme
        st.markdown("---")
        st.markdown("**Önizleme**")
        prev_l, prev_r = st.columns(2)
        with prev_l:
            st.markdown(f"**SKU:** {sku.strip()}")
            st.markdown(f"**Tip:** {repl_type}")
            persona = _parse_persona(persona_text)
            for k, v in persona.items():
                st.markdown(f"**{k}:** {v}")
        with prev_r:
            if png_bytes:
                st.image(png_bytes, caption="Label", use_container_width=True)
            else:
                st.info("Label önizleme yok.")

        # Drive'a yükle
        with st.spinner("Label Drive'a yükleniyor..."):
            try:
                filename = f"{sku.strip()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                drive_url = sc.upload_label_to_drive(pdf_bytes, filename)
            except Exception as exc:
                st.error(f"Drive yüklemesi başarısız: {exc}")
                return

        # Sheets'e yaz
        data = {
            "replacement_id":  str(uuid.uuid4()),
            "sku":             sku.strip(),
            "personalization": json.dumps(_parse_persona(persona_text), ensure_ascii=False),
            "replacement_type": repl_type,
            "status":          "pending",
            "created_at":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label_drive_url": drive_url,
        }
        try:
            sc.add_replacement(data)
            st.success(f"Gönderildi. Headquarter onayı bekleniyor.  \n🔗 [Label Drive'da]({drive_url})")
        except Exception as exc:
            st.error(f"Sheets'e yazılamadı: {exc}")


# ── Bölüm 2: Pending Replacements ────────────────────────────────────────────

def _render_pending(sc, hq_auth: bool, admin_password: str) -> None:
    st.markdown("---")
    st.markdown("#### Pending Replacements")

    if not hq_auth:
        pwd = st.text_input(
            "HQ Şifresi", type="password", key="repl_hq_pwd",
            placeholder="Headquarter şifresini girin",
            label_visibility="collapsed",
        )
        if st.button("Giriş", key="repl_hq_login"):
            if admin_password and pwd == admin_password:
                st.session_state["repl_hq_auth"] = True
                st.rerun()
            else:
                st.error("Hatalı şifre.")
        return

    col_title, col_out, col_ref = st.columns([4, 1, 1])
    with col_out:
        if st.button("Çıkış", key="repl_hq_logout"):
            st.session_state["repl_hq_auth"] = False
            st.rerun()
    with col_ref:
        if st.button("🔄", key="repl_refresh"):
            st.rerun()

    if not sc:
        st.error("Google Sheets bağlantısı yok.")
        return

    try:
        pending = sc.get_pending_replacements()
    except Exception as exc:
        st.error(f"Veri alınamadı: {exc}")
        return

    if not pending:
        st.info("Bekleyen replacement yok.")
        return

    for item in pending:
        rid        = item.get("replacement_id", "?")
        sku        = item.get("sku", "?")
        rtype      = item.get("replacement_type", "?")
        created    = item.get("created_at", "?")
        p_json     = item.get("personalization", "{}")
        drive_url  = item.get("label_drive_url", "")

        with st.expander(f"**{sku}** — {rtype} — {created}", expanded=False):
            col_info, col_label = st.columns([1, 1])

            with col_info:
                st.markdown(f"**ID:** `{rid}`")
                st.markdown(f"**SKU:** {sku}")
                st.markdown(f"**Tip:** {rtype}")
                st.markdown(f"**Tarih:** {created}")
                if drive_url:
                    st.markdown(f"🔗 [Label PDF (Drive)]({drive_url})")
                st.markdown("**Personalization:**")
                try:
                    for k, v in json.loads(p_json).items():
                        st.markdown(f"- **{k}:** {v}")
                except Exception:
                    st.code(p_json)

            with col_label:
                if drive_url:
                    pdf_bytes = _fetch_pdf_from_drive(drive_url)
                    if pdf_bytes:
                        png = _pdf_to_png(pdf_bytes, dpi=80)
                        if png:
                            st.image(png, caption="Label", use_container_width=True)
                        else:
                            st.caption("Önizleme oluşturulamadı")
                    else:
                        st.caption("Drive'dan indirilemedi")

            btn1, btn2 = st.columns(2)
            with btn1:
                if st.button("✅ Kuyruğa Ekle", key=f"repl_queue_{rid}"):
                    _action_queue(sc, item)
            with btn2:
                if drive_url:
                    try:
                        a4 = _cached_a4_pdf(sku, rtype, p_json, created, drive_url)
                        st.download_button(
                            "⬇️ Label İndir",
                            data=a4,
                            file_name=f"replacement_{sku}_{created[:10]}.pdf",
                            mime="application/pdf",
                            key=f"repl_dl_{rid}",
                        )
                    except Exception as exc:
                        st.error(f"PDF oluşturulamadı: {exc}")
                else:
                    st.button("⬇️ Label İndir", key=f"repl_dl_{rid}", disabled=True)


def _action_queue(sc, item: dict) -> None:
    from core.jsx_trigger import JSXTrigger, detect_product_type
    from core.order_manager import OrderManager

    sku = item.get("sku", "")
    rid = item.get("replacement_id", "")
    try:
        persona = json.loads(item.get("personalization", "{}"))
    except Exception:
        persona = {}

    order: dict = {
        "order_id":      f"REPL-{rid[:8]}",
        "order_item_id": f"REPL-{rid}",
        "sku":           sku,
        "qty":           1,
        "name":          persona.get("NAME", persona.get("NAME_1", "")),
        "year":          persona.get("YEAR", ""),
        "message":       persona.get("MESSAGE", ""),
        "font_option":   "SERIF",
        "color_option":  "BLACK",
        "is_manual":     True,
    }
    for pkey, n in [("NAME_DAD", 2), ("NAME_2", 3), ("NAME_3", 4)]:
        if pkey in persona:
            order[f"name{n}"] = persona[pkey]

    try:
        OrderManager().add_orders([order])
    except Exception as exc:
        st.error(f"orders.json yazılamadı: {exc}")
        return

    pt = detect_product_type(sku)
    if pt == "unknown":
        st.warning(f"SKU '{sku}' tanımlı değil — Illustrator tetiklenmedi.")
    else:
        try:
            result = JSXTrigger().trigger_batch([order])
            if result["success"]:
                st.success("Illustrator'a gönderildi.")
            else:
                st.warning(f"Illustrator hatası: {result.get('error', '?')}")
        except Exception as exc:
            st.warning(f"JSX tetiklenemedi: {exc}")

    try:
        sc.update_replacement_status(rid, "queued")
        st.success("Status 'queued' güncellendi.")
        st.rerun()
    except Exception as exc:
        st.error(f"Status güncellenemedi: {exc}")


# ── Ana render fonksiyonu ─────────────────────────────────────────────────────

def render_replacement(sc, authenticated: bool, admin_password: str) -> None:
    st.markdown("""
    <div style="display:flex; align-items:center; gap:0.6rem; margin-bottom:1.2rem;">
        <span style="font-size:1.4rem;">🔄</span>
        <div>
            <div style="font-size:1.1rem; font-weight:700;">Replacement</div>
            <div style="font-size:0.75rem; color:#8b92a5;">Talep oluştur · Headquarter onayı</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    _render_add(sc)
    hq_auth = authenticated or st.session_state.get("repl_hq_auth", False)
    _render_pending(sc, hq_auth, admin_password)
