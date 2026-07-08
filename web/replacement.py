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
        line = line.strip().lstrip("#")
        if ":" in line:
            key, _, val = line.partition(":")
            if key.strip():
                result[key.strip()] = val.strip()
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

    if "repl_items" not in st.session_state:
        st.session_state["repl_items"] = []

    label_file = st.file_uploader(
        "Label PDF (tek sayfa)", type=["pdf"], key="repl_label_pdf"
    )
    repl_type = st.selectbox(
        "Replacement Tipi",
        ["Broken", "Defective", "Misspelling", "Missing Product", "Missing Shipment", "Wrong Item", "Other"],
        key="repl_type",
    )

    st.markdown("**Ürünler**")

    # ── Mevcut ürün listesi ──────────────────────────────────────────────────
    for i, it in enumerate(st.session_state["repl_items"]):
        col_info, col_del = st.columns([6, 1])
        with col_info:
            preview = "  ·  ".join(f"{k}: {v}" for k, v in _parse_persona(it["personalization"]).items())[:70]
            st.markdown(f"**{i+1}.** `{it['sku']}`  —  {preview or '—'}")
        with col_del:
            if st.button("✕", key=f"repl_del_{i}"):
                st.session_state["repl_items"].pop(i)
                st.rerun()

    # ── Yeni ürün ekle ───────────────────────────────────────────────────────
    new_sku = st.text_input("SKU", key="repl_new_sku", placeholder="CRMC1246")
    new_persona = st.text_area(
        "Personalization",
        placeholder=(
            "NAME: Alex\n"
            "NAME_DAD: Michael\n"
            "YEAR: 2026\n"
            "MESSAGE: Merry Christmas\n"
            "NOTE: gift box gönderilmemiş"
        ),
        height=130,
        key="repl_new_persona",
    )
    if st.button("➕ Ürün Ekle", key="repl_add_item"):
        if new_sku.strip():
            st.session_state["repl_items"].append(
                {"sku": new_sku.strip(), "personalization": new_persona.strip()}
            )
            st.session_state["repl_new_sku"] = ""
            st.session_state["repl_new_persona"] = ""
            st.rerun()
        else:
            st.warning("SKU zorunludur.")

    if st.button("Gönder", type="primary", key="repl_submit"):
        items = st.session_state["repl_items"]
        errors = []
        if not items:
            errors.append("En az bir ürün ekleyin (➕ Ürün Ekle).")
        if not label_file:
            errors.append("Label PDF zorunludur.")
        if not sc:
            errors.append("Google Sheets bağlantısı yok.")
        for e in errors:
            st.error(e)
        if errors:
            return

        pdf_bytes = label_file.read()

        # Label önizleme
        png_bytes = _pdf_to_png(pdf_bytes)
        if png_bytes:
            st.image(png_bytes, caption="Label", use_container_width=True)

        # Personalization verisi: tek item → dict, birden fazla → list
        if len(items) == 1:
            sku_display  = items[0]["sku"]
            persona_data = _parse_persona(items[0]["personalization"])
        else:
            sku_display  = f"{items[0]['sku']} +{len(items) - 1}"
            persona_data = [
                {"sku": it["sku"], "personalization": _parse_persona(it["personalization"])}
                for it in items
            ]

        data = {
            "replacement_id":   str(uuid.uuid4()),
            "sku":              sku_display,
            "personalization":  json.dumps(persona_data, ensure_ascii=False),
            "replacement_type": repl_type,
            "status":           "pending",
            "created_at":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        with st.spinner("Sheets'e kaydediliyor..."):
            try:
                sc.add_replacement(data, pdf_bytes)
                st.success(f"{len(items)} ürün gönderildi. Headquarter onayı bekleniyor.")
                st.session_state["repl_items"] = []
                st.rerun()
            except Exception as exc:
                st.error(f"Kaydedilemedi: {exc}")


# ── Bölüm 2: Pending Replacements ────────────────────────────────────────────

def _render_pending(sc) -> None:
    st.markdown("---")
    st.markdown("#### Pending Replacements")

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
            st.markdown(f"**Tip:** {rtype}  |  **Tarih:** {created}")
            try:
                p_data = json.loads(p_json)
                if isinstance(p_data, list):
                    for idx, it in enumerate(p_data):
                        it_sku = it.get("sku", "?")
                        it_persona = it.get("personalization", {})
                        persona_str = "  ·  ".join(f"{k}: {v}" for k, v in it_persona.items())
                        st.markdown(f"**{idx+1}.** `{it_sku}` — {persona_str or '—'}")
                else:
                    st.markdown(f"**SKU:** {sku}")
                    cols = st.columns(min(len(p_data), 3) or 1)
                    for ci, (k, v) in enumerate(p_data.items()):
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


def _persona_to_order(rid: str, item_sku: str, persona: dict, idx: int = 0) -> dict:
    order: dict = {
        "order_id":      f"REPL-{rid[:8]}",
        "order_item_id": f"REPL-{rid}-{idx}",
        "sku":           item_sku,
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
    return order


def _action_queue(sc, item: dict) -> None:
    """Replacement'ı orders.json'a yazar, Illustrator'ı tetikler,
    chunk'ları siler, status='queued' yapar."""
    from core.jsx_trigger import JSXTrigger, detect_product_type
    from core.order_manager import OrderManager

    rid = item.get("replacement_id", "")
    try:
        p_data = json.loads(item.get("personalization", "{}"))
    except Exception:
        p_data = {}

    # Tek item (dict) veya çok item (list) formatını normalize et
    if isinstance(p_data, list):
        items_list = p_data  # [{"sku": "...", "personalization": {...}}, ...]
    else:
        items_list = [{"sku": item.get("sku", ""), "personalization": p_data}]

    orders = []
    for idx, it in enumerate(items_list):
        orders.append(_persona_to_order(rid, it.get("sku", ""), it.get("personalization", {}), idx))

    try:
        OrderManager().add_orders(orders)
    except Exception as exc:
        st.error(f"orders.json yazılamadı: {exc}")
        return

    known   = [o for o in orders if detect_product_type(o["sku"]) != "unknown"]
    unknown = [o["sku"] for o in orders if detect_product_type(o["sku"]) == "unknown"]
    if unknown:
        st.warning(f"Tanımlı template yok (tetiklenmedi): {', '.join(set(unknown))}")
    if known:
        try:
            result = JSXTrigger().trigger_batch(known)
            if result["success"]:
                st.success(f"{len(known)} sipariş Illustrator'a gönderildi.")
            else:
                st.warning(f"Illustrator hatası: {result.get('error', '?')}")
        except Exception as exc:
            st.warning(f"JSX tetiklenemedi: {exc}")

    sc.delete_replacement_label_chunks(rid)
    sc.update_replacement_status(rid, "queued")
    st.success("Kuyruğa eklendi.")
    st.rerun()


# ── Ana render fonksiyonu ─────────────────────────────────────────────────────

def render_replacement(sc) -> None:
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
    _render_pending(sc)
