"""
web/replacement.py
==================
Replacement sekmesi UI.
  Add Replacement    : şifresiz (Türkiye kullanır)
  Pending Replacements: ADMIN_PASSWORD gerekli (Headquarter)
"""

import base64
import gzip
import io
import json
import uuid
from datetime import datetime

import streamlit as st


# ── PDF → PNG dönüşümü ───────────────────────────────────────────────────────

def _pdf_to_png(pdf_bytes: bytes, dpi: int = 150) -> bytes | None:
    """PDF'in ilk sayfasını PNG bytes'a çevirir. Hata durumunda None döner."""
    # pypdfium2 (poppler bağımlılığı yok)
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf_bytes)
        if len(doc) == 0:
            return None
        page = doc[0]
        bitmap = page.render(scale=dpi / 72)
        pil_img = bitmap.to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        pass
    # pdf2image (poppler gerekli — fallback)
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
    """# formatındaki metni {KEY: value} dict'e çevirir."""
    result: dict[str, str] = {}
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if line.startswith("#"):
            parts = line[1:].split(":", 1)
            if len(parts) == 2:
                result[parts[0].strip()] = parts[1].strip()
    return result


def _persona_to_text(persona_json: str) -> str:
    """JSON dict'i # formatına çevirir."""
    try:
        d = json.loads(persona_json)
        return "\n".join(f"#{k}: {v}" for k, v in d.items())
    except Exception:
        return ""


# ── Label PDF sıkıştırma / açma (Sheets hücre limiti için) ──────────────────

def _encode_pdf(pdf_bytes: bytes) -> str:
    """PDF'i gzip sıkıştır + base64 encode et."""
    return base64.b64encode(gzip.compress(pdf_bytes)).decode("utf-8")


def _decode_pdf(encoded: str) -> bytes:
    """_encode_pdf ile kodlanmış stringi geri çöz."""
    return gzip.decompress(base64.b64decode(encoded))


# ── Önbellek: A4 PDF oluşturma ───────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _cached_a4_pdf(
    sku: str,
    replacement_type: str,
    persona_json: str,
    created_at: str,
    encoded_pdf: str,
) -> bytes:
    """A4 landscape PDF oluştur (cached)."""
    from core.label_merger import build_a4_pdf

    try:
        pdf_bytes = _decode_pdf(encoded_pdf)
        png_bytes = _pdf_to_png(pdf_bytes, dpi=120)
    except Exception:
        png_bytes = None

    persona_text = _persona_to_text(persona_json)
    return build_a4_pdf(sku, replacement_type, persona_text, created_at, png_bytes)


# ── Bölüm 1: Add Replacement ────────────────────────────────────────────────

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
        if errors:
            for e in errors:
                st.error(e)
            return

        pdf_bytes = label_file.read()
        png_bytes = _pdf_to_png(pdf_bytes)

        # Preview
        st.markdown("---")
        st.markdown("**Önizleme**")
        prev_left, prev_right = st.columns(2)
        with prev_left:
            persona = _parse_persona(persona_text)
            st.markdown(f"**SKU:** {sku.strip()}")
            st.markdown(f"**Tip:** {repl_type}")
            if persona:
                for k, v in persona.items():
                    st.markdown(f"**{k}:** {v}")
            else:
                st.caption("Personalization girilmedi.")
        with prev_right:
            if png_bytes:
                st.image(png_bytes, caption="Label", use_container_width=True)
            else:
                st.info("Label önizleme mevcut değil.")

        # Sheets'e kaydet
        if not sc:
            st.error("Google Sheets bağlantısı yok — kaydedilemedi.")
            return

        encoded = _encode_pdf(pdf_bytes)
        char_count = len(encoded)
        if char_count > 49_000:
            st.warning(
                f"PDF sıkıştırıldıktan sonra {char_count:,} karakter. "
                "Google Sheets hücre limiti (~50K) aşılıyor — kayıt başarısız olabilir."
            )

        data = {
            "replacement_id": str(uuid.uuid4()),
            "sku": sku.strip(),
            "personalization": json.dumps(_parse_persona(persona_text), ensure_ascii=False),
            "replacement_type": repl_type,
            "status": "pending",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label_pdf": encoded,
        }

        try:
            sc.add_replacement(data)
            st.success("Gönderildi. Headquarter onayı bekleniyor.")
        except Exception as exc:
            st.error(f"Sheets'e yazılamadı: {exc}")


# ── Bölüm 2: Pending Replacements (HQ şifreli) ──────────────────────────────

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

    col_title, col_logout, col_refresh = st.columns([4, 1, 1])
    with col_logout:
        if st.button("Çıkış", key="repl_hq_logout"):
            st.session_state["repl_hq_auth"] = False
            st.rerun()
    with col_refresh:
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
        rid = item.get("replacement_id", "?")
        sku = item.get("sku", "?")
        rtype = item.get("replacement_type", "?")
        created = item.get("created_at", "?")
        persona_json = item.get("personalization", "{}")
        encoded_pdf = item.get("label_pdf", "")

        label = f"**{sku}** — {rtype} — {created}"
        with st.expander(label, expanded=False):
            col_info, col_label = st.columns([1, 1])

            with col_info:
                st.markdown(f"**ID:** `{rid}`")
                st.markdown(f"**SKU:** {sku}")
                st.markdown(f"**Tip:** {rtype}")
                st.markdown(f"**Tarih:** {created}")
                st.markdown("**Personalization:**")
                try:
                    persona = json.loads(persona_json)
                    for k, v in persona.items():
                        st.markdown(f"- **{k}:** {v}")
                except Exception:
                    st.code(persona_json)

            with col_label:
                if encoded_pdf:
                    try:
                        png = _pdf_to_png(_decode_pdf(encoded_pdf), dpi=80)
                        if png:
                            st.image(png, caption="Label", use_container_width=True)
                        else:
                            st.caption("Önizleme yok")
                    except Exception:
                        st.caption("Label yüklenemedi")

            btn1, btn2 = st.columns(2)

            with btn1:
                if st.button("✅ Kuyruğa Ekle", key=f"repl_queue_{rid}"):
                    _action_queue(sc, item)

            with btn2:
                if encoded_pdf:
                    try:
                        a4_bytes = _cached_a4_pdf(sku, rtype, persona_json, created, encoded_pdf)
                        fname = f"replacement_{sku}_{created[:10]}.pdf"
                        st.download_button(
                            "⬇️ Label İndir",
                            data=a4_bytes,
                            file_name=fname,
                            mime="application/pdf",
                            key=f"repl_dl_{rid}",
                        )
                    except Exception as exc:
                        st.error(f"PDF oluşturulamadı: {exc}")
                else:
                    st.button("⬇️ Label İndir", key=f"repl_dl_{rid}", disabled=True)


def _action_queue(sc, item: dict) -> None:
    """Replacement'ı orders.json'a yazar, Illustrator'ı tetikler, status='queued' yapar."""
    from core.jsx_trigger import JSXTrigger, detect_product_type
    from core.order_manager import OrderManager

    sku = item.get("sku", "")
    rid = item.get("replacement_id", "")
    persona_json = item.get("personalization", "{}")

    try:
        persona = json.loads(persona_json)
    except Exception:
        persona = {}

    # Orders dict oluştur
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
    # Ek isim alanları
    name_keys = [("NAME_DAD", 2), ("NAME_2", 3), ("NAME_3", 4), ("NAME_4", 5)]
    for pkey, n in name_keys:
        if pkey in persona:
            order[f"name{n}"] = persona[pkey]

    # orders.json'a yaz
    try:
        mgr = OrderManager()
        mgr.add_orders([order])
    except Exception as exc:
        st.error(f"orders.json yazılamadı: {exc}")
        return

    # Illustrator tetikle (SKU tanımlıysa)
    pt = detect_product_type(sku)
    if pt == "unknown":
        st.warning(f"SKU '{sku}' tanımlı değil — Illustrator tetiklenmedi.")
    else:
        try:
            jsx = JSXTrigger()
            result = jsx.trigger_batch([order])
            if result["success"]:
                st.success("Illustrator'a gönderildi.")
            else:
                st.warning(f"Illustrator hatası: {result.get('error', '?')}")
        except Exception as exc:
            st.warning(f"JSX tetiklenemedi: {exc}")

    # Status güncelle
    try:
        sc.update_replacement_status(rid, "queued")
        st.success("Status 'queued' olarak güncellendi.")
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

    # Ana admin zaten girişyapmışsa HQ bölümü direkt açılır
    hq_auth = authenticated or st.session_state.get("repl_hq_auth", False)
    _render_pending(sc, hq_auth, admin_password)
