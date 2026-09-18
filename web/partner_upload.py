"""
web/partner_upload.py
=====================
Partner Upload sekmesi — şifresiz, herkese açık.
Packing slip (HTML/TXT) + label PDF (çok sayfalı) yükle,
eşleştir, Queue'ya ekle, birleşik PDF indir.
"""

import sys
from collections import defaultdict
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.parse_utils import parse_uploaded_files




def _parse_labels_amazon(uploaded_pdfs) -> tuple[dict[str, bytes | None], list[str]]:
    """Amazon: son sayfa(lar) order ID listesi, önceki sayfalar label."""
    from core.label_merger import split_label_pdf
    label_map: dict[str, bytes | None] = {}
    warnings: list[str] = []

    for pdf_file in uploaded_pdfs:
        pdf_bytes = pdf_file.read()
        try:
            label_pngs, order_ids = split_label_pdf(pdf_bytes)
        except Exception as e:
            warnings.append(f"[{pdf_file.name}] PDF parse hatası: {e}")
            continue

        if not order_ids:
            warnings.append(
                f"[{pdf_file.name}] Order ID bulunamadı. "
                "Son sayfa(lar)da 3+ order ID içeren sipariş listesi olmalı."
            )
            continue

        if len(label_pngs) != len(order_ids):
            warnings.append(
                f"[{pdf_file.name}] Label sayısı ({len(label_pngs)}) ile "
                f"order ID sayısı ({len(order_ids)}) farklı — pozisyonel eşleştirme."
            )

        for i, oid in enumerate(order_ids):
            label_map[oid.strip()] = label_pngs[i] if i < len(label_pngs) else None

    return label_map, warnings


def _parse_labels_etsy(uploaded_pdfs) -> tuple[dict[str, int], dict[str, bytes], list[str]]:
    """
    Etsy: her sayfa kendi order ID'sini taşır ('Order #: <ID>').
    Returns: (oid_to_page, oid_to_pdf_bytes, warnings)
    """
    from core.label_merger import extract_etsy_label_order_ids
    oid_to_page: dict[str, int] = {}
    oid_to_pdf: dict[str, bytes] = {}
    warnings: list[str] = []

    for pdf_file in uploaded_pdfs:
        pdf_bytes = pdf_file.read()
        try:
            page_map = extract_etsy_label_order_ids(pdf_bytes)
        except Exception as e:
            warnings.append(f"[{pdf_file.name}] PDF parse hatası: {e}")
            continue

        if not page_map:
            warnings.append(
                f"[{pdf_file.name}] 'Order #:' pattern bulunamadı. "
                "Etsy label formatını kontrol edin."
            )
            continue

        for oid, page_idx in page_map.items():
            oid_to_page[oid] = page_idx
            oid_to_pdf[oid] = pdf_bytes

    return oid_to_page, oid_to_pdf, warnings


def render_partner_upload(sc) -> None:
    st.markdown("""
    <div style="display:flex; align-items:center; gap:0.6rem; margin-bottom:1.2rem;">
        <span style="font-size:1.4rem;">🤝</span>
        <div>
            <div style="font-size:1.1rem; font-weight:700;">Partner Upload</div>
            <div style="font-size:0.75rem; color:#8b92a5;">
                Packing slip + label yükle · Ana kuyruğa ekle · PDF indir
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not sc:
        st.error("Google Sheets bağlantısı yok.")
        return

    try:
        partners = sc.get_partners()
    except Exception as e:
        st.error(f"Partner listesi alınamadı: {e}")
        return

    if not partners:
        st.warning("Tanımlı aktif partner yok. Admin sekmesinden partner ekleyin.")
        return

    partner_options = {p["partner_name"]: p["partner_id"] for p in partners}
    selected_name = st.selectbox("Partner Seç *", list(partner_options.keys()), key="pu_partner")
    selected_id = partner_options[selected_name]

    st.divider()

    platform = st.radio(
        "Kaynak Platform", ["Amazon", "Etsy"],
        horizontal=True, key="pu_platform"
    )
    platform_key = platform.lower()

    col_slip, col_label = st.columns(2)
    with col_slip:
        if platform_key == "amazon":
            slip_files = st.file_uploader(
                "Packing Slip (.html, .htm, .txt)",
                type=["html", "htm", "txt"],
                accept_multiple_files=True,
                key="pu_slips",
            )
        else:
            slip_files = st.file_uploader(
                "Etsy Packing Slip PDF",
                type=["pdf"],
                accept_multiple_files=True,
                key="pu_slips",
            )
    with col_label:
        label_files = st.file_uploader(
            "Label PDF — son sayfa(lar) order listesi içermeli",
            type=["pdf"],
            accept_multiple_files=True,
            key="pu_labels",
        )

    if not slip_files and not label_files:
        st.info("Packing slip ve label PDF yükleyip İşle butonuna basın.")
        return

    if st.button("⚙️ İşle", type="primary", key="pu_process"):
        # ── Adım 1: Packing Slip Parse ──────────────────────────────────────
        with st.spinner("Packing slip'ler parse ediliyor..."):
            orders, slip_warns = parse_uploaded_files(slip_files or [], platform_key)

        # ── Adım 2: Label Parse ─────────────────────────────────────────────
        with st.spinner("Label PDF'ler işleniyor..."):
            if platform_key == "etsy":
                etsy_oid_to_page, etsy_oid_to_pdf, label_warns = _parse_labels_etsy(label_files or [])
                label_map = etsy_oid_to_page  # {oid: page_idx} — eşleştirme için
            else:
                label_map, label_warns = _parse_labels_amazon(label_files or [])

        all_warns = slip_warns + label_warns
        if all_warns:
            with st.expander(f"⚠️ {len(all_warns)} uyarı"):
                for w in all_warns:
                    st.warning(w)

        # ── Adım 3: Eşleştirme ──────────────────────────────────────────────
        orders_by_oid: dict[str, list[dict]] = defaultdict(list)
        for o in orders:
            oid = str(o.get("order_id", "")).strip()
            if oid:
                orders_by_oid[oid].append(o)

        matched_oids   = set(orders_by_oid.keys()) & set(label_map.keys())
        slip_only_oids = set(orders_by_oid.keys()) - set(label_map.keys())
        label_only_oids = set(label_map.keys()) - set(orders_by_oid.keys())

        st.markdown("### İşleme Özeti")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Parse Edilen Sipariş", len(orders))
        c2.metric("Label'daki Order", len(label_map))
        c3.metric("Eşleşen", len(matched_oids))
        c4.metric("Eşleşmeyen", len(slip_only_oids) + len(label_only_oids))

        if slip_only_oids:
            st.warning(
                f"Packing slip'te var, label'da yok ({len(slip_only_oids)}): "
                f"{', '.join(sorted(slip_only_oids)[:8])}"
                + ("..." if len(slip_only_oids) > 8 else "")
            )
        if label_only_oids:
            st.warning(
                f"Label'da var, packing slip'te yok ({len(label_only_oids)}): "
                f"{', '.join(sorted(label_only_oids)[:8])}"
                + ("..." if len(label_only_oids) > 8 else "")
            )

        if not matched_oids:
            st.error("Eşleşen sipariş bulunamadı. Dosyaları kontrol edin.")
            return

        total_items = sum(len(orders_by_oid[oid]) for oid in matched_oids)
        st.success(f"{len(matched_oids)} order ID eşleşti ({total_items} sipariş kalemi).")

        # ── Adım 4a: Queue'ya Ekle ───────────────────────────────────────────
        orders_to_queue = []
        for oid in matched_oids:
            for o in orders_by_oid[oid]:
                o_copy = dict(o)
                o_copy["source"] = selected_id
                o_copy.setdefault("platform", platform_key)
                orders_to_queue.append(o_copy)

        with st.spinner("Ana kuyruğa ekleniyor..."):
            try:
                result = sc.append_queue(orders_to_queue)
                st.success(
                    f"✅ {result['added']} sipariş kuyruğa eklendi"
                    + (f", {result['skipped_duplicates']} duplicate atlandı." if result["skipped_duplicates"] else ".")
                )
            except Exception as e:
                st.error(f"Kuyruğa eklenemedi: {e}")

        # ── Adım 4b: Yazdırma PDF'i ────────────────────────────────────────────
        st.markdown("### Yazdırma PDF'i")
        with st.spinner("PDF hazırlanıyor..."):
            try:
                if platform_key == "etsy":
                    # Etsy: kırpılmış + döndürülmüş label + sol metin bloğu (A4 landscape)
                    from core.label_merger import build_etsy_batch_pdf
                    oid_source_map = {
                        oid: (etsy_oid_to_pdf[oid], etsy_oid_to_page[oid])
                        for oid in matched_oids
                        if oid in etsy_oid_to_pdf
                    }
                    pdf_bytes = build_etsy_batch_pdf(
                        oid_source_map,
                        {oid: orders_by_oid[oid] for oid in matched_oids},
                    )
                else:
                    # Amazon: A4 landscape, sol=order bilgisi, sağ=label PNG
                    from core.label_merger import build_partner_batch_pdf
                    pdf_items = []
                    for oid in sorted(matched_oids):
                        oid_orders = orders_by_oid[oid]
                        skus = list({o.get("sku", "") for o in oid_orders if o.get("sku")})
                        item_ids = [str(o.get("order_item_id", "")) for o in oid_orders]
                        summary_lines = []
                        for o in oid_orders:
                            names = [o.get(k, "") for k in ["name", "name2", "name3"] if o.get(k)]
                            if names:
                                summary_lines.append(f"İsim: {', '.join(names)}")
                            if o.get("year"):
                                summary_lines.append(f"Yıl: {o['year']}")
                            if o.get("message"):
                                summary_lines.append(f"Mesaj: {o['message']}")
                            if o.get("font_option"):
                                summary_lines.append(f"Font: {o['font_option']}")
                            if o.get("color_option"):
                                summary_lines.append(f"Renk: {o['color_option']}")
                        pdf_items.append({
                            "order_id":       oid,
                            "order_item_ids": item_ids,
                            "skus":           skus,
                            "summary":        "\n".join(summary_lines),
                            "label_png":      label_map.get(oid),
                        })
                    pdf_bytes = build_partner_batch_pdf(pdf_items)

                st.download_button(
                    "⬇️ PDF İndir",
                    data=pdf_bytes,
                    file_name=f"partner_{selected_id}_{len(matched_oids)}siparis.pdf",
                    mime="application/pdf",
                    key="pu_download",
                )
            except Exception as e:
                st.error(f"PDF oluşturulamadı: {e}")
