"""
web/replacement.py
==================
Replacement sekmesi UI.
  Add Replacement      : şifresiz (Türkiye kullanır)
  Pending Replacements : ADMIN_PASSWORD gerekli (Headquarter)

Label PDF'ler Google Sheets ReplacementLabels sheet'inde chunk'lar halinde tutulur.
İndir / Kuyruğa Ekle sonrası chunk'lar silinir (label_chunk_count = 0 olur).
"""

import io
import json
import uuid
from datetime import datetime

import streamlit as st


# ── PDF → PNG ────────────────────────────────────────────────────────────────

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


# ── Personalization ───────────────────────────────────────────────────────────

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


# ── A4 PDF oluştur ───────────────────────────────────────────────────────────

def _build_a4(sku: str, rtype: str, p_json: str, created: str, pdf_bytes: bytes | None) -> bytes:
    from core.label_merger import build_a4_pdf
    png = _pdf_to_png(pdf_bytes, dpi=120) if pdf_bytes else None
    return build_a4_pdf(sku, rtype, _persona_to_text(p_json), created, png)


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
        height=160,
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
        cl, cr = st.columns(2)
        with cl:
            st.markdown(f"**SKU:** {sku.strip()}")
            st.markdown(f"**Tip:** {repl_type}")
            for k, v in _parse_persona(persona_text).items():
                st.markdown(f"**{k}:** {v}")
        with cr:
            if png_bytes:
                st.image(png_bytes, caption="Label", use_container_width=True)
            else:
                st.info("Label önizleme yok.")

        # Sheets'e yaz
        data = {
            "replacement_id":   str(uuid.uuid4()),
            "sku":              sku.strip(),
            "personalization":  json.dumps(_parse_persona(persona_text), ensure_ascii=False),
            "replacement_type": repl_type,
            "status":           "pending",
            "created_at":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        with st.spinner("Sheets'e kaydediliyor..."):
            try:
                sc.add_replacement(data, pdf_bytes)
                st.success("Gönderildi. Headquarter onayı bekleniyor.")
            except Exception as exc:
                st.error(f"Kaydedilemedi: {exc}")


# ── Bölüm 2: Pending Replacements ────────────────────────────────────────────

def _render_pending(sc, hq_auth: bool, admin_password: str) -> None:
    st.markdown("---")
    st.markdown("#### Pending Replacements")

    if not hq_auth:
        st.markdown(
            "<div style='background:#1a1d2e;border:1px solid #2d3147;border-radius:10px;"
            "padding:1.2rem 1.4rem;margin-bottom:1rem;'>"
            "<div style='font-size:1rem;font-weight:600;color:#f0f2f6;margin-bottom:0.3rem;'>"
            "🔐 Headquarter Girişi</div>"
            "<div style='font-size:0.8rem;color:#8b92a5;'>Bekleyen replacement'ları görmek için şifre gereklidir.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        with st.form("hq_login_form"):
            pwd = st.text_input("Admin Şifresi", type="password", placeholder="Yönetici şifresini girin")
            submitted = st.form_submit_button("Giriş Yap", type="primary", use_container_width=True)
            if submitted:
                if not admin_password:
                    st.error("Sunucuda ADMIN_PASSWORD yapılandırılmamış.")
                elif pwd == admin_password:
                    st.session_state["repl_hq_auth"] = True
                    st.rerun()
                else:
                    st.error("Hatalı şifre.")
        return

    col_out, col_ref = st.columns([1, 1])
    with col_out:
        if st.button("Çıkış", key="repl_hq_logout"):
            st.session_state["repl_hq_auth"] = False
            st.rerun()
    with col_ref:
        if st.button("🔄 Yenile", key="repl_refresh"):
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
        rid     = item.get("replacement_id", "?")
        sku     = item.get("sku", "?")
        rtype   = item.get("replacement_type", "?")
        created = item.get("created_at", "?")
        p_json  = item.get("personalization", "{}")

        try:
            chunk_count = int(item.get("label_chunk_count", 0) or 0)
        except (ValueError, TypeError):
            chunk_count = 0

        # Session state anahtarları
        view_key = f"repl_png_{rid}"
        pdf_key  = f"repl_pdf_{rid}"

        label = f"**{sku}** — {rtype} — {created}"
        with st.expander(label, expanded=False):

            # ── Bilgi ──────────────────────────────────────────────────────
            st.markdown(f"**ID:** `{rid}`")
            st.markdown(f"**SKU:** {sku}  |  **Tip:** {rtype}  |  **Tarih:** {created}")
            try:
                persona = json.loads(p_json)
                cols = st.columns(min(len(persona), 3) or 1)
                for ci, (k, v) in enumerate(persona.items()):
                    cols[ci % len(cols)].markdown(f"**{k}:** {v}")
            except Exception:
                st.code(p_json)

            st.markdown("---")

            # ── Label yok notu ─────────────────────────────────────────────
            if chunk_count == 0:
                st.caption("🗑️ Label silindi (işlendi)")

            # ── Butonlar ───────────────────────────────────────────────────
            btn_cols = st.columns(3)

            # 1) Label Görüntüle
            with btn_cols[0]:
                if chunk_count > 0:
                    if st.button("👁️ Görüntüle", key=f"repl_view_{rid}"):
                        with st.spinner("Label indiriliyor..."):
                            raw = sc.get_replacement_label(rid)
                        if raw:
                            st.session_state[view_key] = _pdf_to_png(raw, dpi=100)
                        else:
                            st.error("Label okunamadı.")

            # 2) Kuyruğa Ekle
            with btn_cols[1]:
                if st.button("✅ Kuyruğa Ekle", key=f"repl_queue_{rid}"):
                    _action_queue(sc, item)

            # 3) Label İndir (iki adım)
            with btn_cols[2]:
                if pdf_key not in st.session_state:
                    btn_label = "⬇️ Hazırla PDF" if chunk_count > 0 else "⬇️ PDF Yok"
                    if st.button(btn_label, key=f"repl_prep_{rid}", disabled=(chunk_count == 0)):
                        with st.spinner("A4 PDF hazırlanıyor..."):
                            raw = sc.get_replacement_label(rid)
                            a4  = _build_a4(sku, rtype, p_json, created, raw)
                            st.session_state[pdf_key] = a4
                        sc.delete_replacement_label_chunks(rid)
                        st.rerun()
                else:
                    fname = f"replacement_{sku}_{created[:10]}.pdf"
                    if st.download_button(
                        "⬇️ PDF İndir",
                        data=st.session_state[pdf_key],
                        file_name=fname,
                        mime="application/pdf",
                        key=f"repl_dl_{rid}",
                    ):
                        sc.update_replacement_status(rid, "downloaded")
                        del st.session_state[pdf_key]
                        st.rerun()

            # ── Preview göster ─────────────────────────────────────────────
            if view_key in st.session_state and st.session_state[view_key]:
                st.image(
                    st.session_state[view_key],
                    caption="Label Preview",
                    use_container_width=True,
                )
                if st.button("Kapat", key=f"repl_close_{rid}"):
                    del st.session_state[view_key]
                    st.rerun()


def _action_queue(sc, item: dict) -> None:
    """Replacement'ı orders.json'a yazar, Illustrator'ı tetikler,
    chunk'ları siler, status='queued' yapar."""
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

    sc.delete_replacement_label_chunks(rid)
    sc.update_replacement_status(rid, "queued")
    st.success("Kuyruğa eklendi, label chunk'ları silindi.")
    st.rerun()


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
