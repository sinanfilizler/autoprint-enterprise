"""
web/crmc_package.py
===================
CRMC Paket sekmesi (sadece local Streamlit / ana Mac).
Inbox'taki workstation ZIP'lerini tarar, basılmamış blokları listeler, SKU'ya göre sıralı
damgalı PDF üretir. Inbox'a yazmaz; Illustrator'ı ve Google Sheets'i tetiklemez.
"""

from collections import Counter
from datetime import date

import pandas as pd
import streamlit as st

from core import crmc_packages as cp


_SOURCE_LABEL = {"elle": "elle atandı", "başlık": "başlıktan tahmin", "çakışma": "çakışma (iki klasörde)",
                 "yok": "bulunamadı", "klasör": "klasör"}


def _block_rows(blocks, selected, printed) -> pd.DataFrame:
    pdf_no = {id(b): n for n, b in enumerate(cp.sort_blocks(selected), 1)}
    rows = []
    for b in cp.sort_blocks(blocks):
        rows.append({
            "#": f"{pdf_no[id(b)]:03d}" if id(b) in pdf_no else "—",
            "Şekil": cp.SHAPE_LABEL.get(b.shape, ""),
            "Bölüm": "DİĞER" if b.is_other else "",
            "SKU": ", ".join(b.skus) or "?",
            "Adet": sum(i.qty for i in b.items),
            "Gift box": "✓" if b.gift_box else "",
            "Kişisel": "✓" if b.has_personalization else "",
            "Order ID": b.order_id or "?",
            "Sayfa": b.page_count,
            "Paket": b.package_id,
            "Basıldı": printed.get(b.key, {}).get("printed_at", ""),
        })
    return pd.DataFrame(rows)


def render_crmc_package(sc) -> None:
    st.subheader("CRMC Paket")
    path, prefixes = cp.inbox_path(), cp.sku_prefixes()
    st.caption(f"Inbox: `{path}` · SKU önekleri: {', '.join(prefixes)} · Inbox'taki dosyalara dokunulmaz.")

    if st.button("🔄 Inbox'ı Tara", key="crmc_scan_btn") or "crmc_scan" not in st.session_state:
        with st.spinner("Inbox taranıyor..."):
            st.session_state["crmc_scan"] = cp.scan_inbox(path, prefixes)
            # Template klasörü sadece okunur; ROUND/HEART ayrımı buradan gelir
            st.session_state["crmc_tpl_index"] = cp.build_template_index()
        st.session_state.pop("crmc_outputs", None)
    res: cp.ScanResult = st.session_state["crmc_scan"]

    if not res.reachable:
        st.error(f"⚠️ {res.error}\n\nWindows paylaşımı (CRMC_Inbox) bu Mac'e bağlı mı? "
                 "Finder'dan bağlayıp tekrar tarayın.")
        return

    printed = cp.load_printed()
    pkg_dt = {p.package_id: p.dt for p in res.packages}

    c1, c2, c3 = st.columns([1, 1, 1])
    use_date = c1.checkbox("ZIP tarihine göre filtrele", key="crmc_use_date")
    day = c2.date_input("Tarih", value=date.today(), key="crmc_day", disabled=not use_date)
    reprint = c3.checkbox("Tekrar bas (basılmışları da göster)", key="crmc_reprint")

    candidates = [
        b for b in res.blocks
        if (reprint or b.key not in printed)
        and (not use_date or pkg_dt[b.package_id].date() == day)
    ]
    shown_pkgs = {b.package_id for b in candidates}

    queue, queue_note = [], ""
    if sc is None:
        queue_note = "Google Sheets bağlantısı yok, kuyruk karşılaştırması yapılmadı."
    else:
        try:
            queue = sc.get_queue()
        except Exception as e:
            queue_note = f"Kuyruk okunamadı, karşılaştırma yapılmadı: {e}"

    warnings = [w for w in res.warnings if not w["paket"] or w["paket"] in shown_pkgs]
    if not queue_note:
        warnings += cp.queue_warnings(res.blocks, candidates, queue, prefixes)

    # ── ROUND / HEART ──
    index = st.session_state.get("crmc_tpl_index")
    sku_shapes = {}
    if index is None:
        for b in res.blocks:
            b.shape, b.shape_skus = None, {}
        st.warning(f"Template klasörü okunamadı ({cp.template_base()}), ROUND/HEART ayrımı kapalı. "
                   "Sadece SKU sırası kullanılıyor.")
    else:
        sku_shapes = cp.assign_shapes(res.blocks, prefixes, index, cp.load_manual_shapes())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Blok", len(candidates))
    m2.metric("Sayfa", sum(b.page_count for b in candidates))
    m3.metric("Diğer SKU'lu blok", sum(b.is_other for b in candidates))
    m4.metric("Uyarı", len(warnings))
    if index is not None:
        cnt = Counter(b.shape for b in candidates)
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("ROUND", cnt[cp.ROUND])
        s2.metric("HEART", cnt[cp.HEART])
        s3.metric("MIXED", cnt[cp.MIXED])
        s4.metric("? (belirsiz)", cnt[cp.UNKNOWN])
        _render_shape_sources(candidates, sku_shapes)

    if queue_note:
        st.info(queue_note)
    if warnings:
        st.markdown("**⚠️ Uyarılar**")
        st.dataframe(pd.DataFrame(warnings), use_container_width=True, hide_index=True)
    if res.retry:
        with st.expander(f"🔁 Tekrar denenecek ZIP'ler ({len(res.retry)})"):
            st.dataframe(pd.DataFrame(res.retry), use_container_width=True, hide_index=True)
    if res.skipped:
        with st.expander(f"Atlanan ZIP'ler ({len(res.skipped)})"):
            st.dataframe(pd.DataFrame(res.skipped), use_container_width=True, hide_index=True)

    if not candidates:
        st.info("Basılacak yeni blok yok." if res.blocks else "Inbox'ta işlenecek paket yok.")
        return

    scope = "all"
    if index is not None:
        scope = st.radio("Kapsam", list(cp.SCOPES), format_func=cp.SCOPES.get, horizontal=True,
                         key="crmc_scope",
                         help="MIXED, şekli belirsiz ve sadece yabancı SKU'lu bloklar her seçimde PDF'e girer.")
    selected = cp.select_blocks(candidates, scope)

    st.markdown(f"**Bloklar** (# = PDF sırası, — = bu kapsamda PDF'e girmez; {len(selected)}/{len(candidates)} blok)")
    st.dataframe(_block_rows(candidates, selected, printed), use_container_width=True, hide_index=True)

    if st.button("📄 PDF Oluştur", type="primary", key="crmc_build", disabled=not selected):
        run_id = cp.new_run_id()
        slips = {p.package_id: p.slips for p in res.packages if p.package_id in shown_pkgs}
        with st.spinner("PDF hazırlanıyor..."):
            files = cp.build_pdfs(selected, slips, run_id, dict(Counter(w["tür"] for w in warnings)),
                                  scope_label=cp.SCOPES[scope] if index is not None else "")
        # "Basıldı" işareti sadece bu PDF'e giren bloklar için
        st.session_state["crmc_outputs"] = {
            "run_id": run_id, "files": files, "keys": [b.key for b in selected], "scope": cp.SCOPES[scope],
        }

    out = st.session_state.get("crmc_outputs")
    if out:
        st.success(f"Çalıştırma {out['run_id']} ({out.get('scope', 'Hepsi')}): "
                   f"{len(out['keys'])} blok, {len(out['files'])} dosya.")
        for name, data in out["files"]:
            st.download_button(f"⬇️ {name}", data, file_name=name, mime="application/pdf",
                               key=f"crmc_dl_{name}")
        st.divider()
        confirm = st.checkbox("Bu PDF'leri bastım", key="crmc_confirm")
        if st.button("✅ Basıldı olarak işaretle", disabled=not confirm, key="crmc_mark"):
            n = cp.mark_printed(out["keys"], out["run_id"])
            st.session_state.pop("crmc_outputs", None)
            st.session_state.pop("crmc_confirm", None)
            st.success(f"{n} blok basıldı olarak kaydedildi.")
            st.rerun()


def _render_shape_sources(candidates, sku_shapes) -> None:
    """Klasörden gelmeyen şekiller: başlıktan tahmin, elle atanan, çakışma, bulunamayan. Elle atama formu."""
    in_scan = {i.sku.lower() for b in candidates for i in b.items}
    rows = [(sku, sh) for sku, sh in sorted(sku_shapes.items(), key=lambda x: cp.natural_key(x[0]))
            if sku in in_scan and sh.source != "klasör"]
    unresolved = [sku for sku, sh in rows if sh.shape == cp.UNKNOWN]
    if unresolved:
        st.warning(f"Şekli belirsiz SKU'lar ({len(unresolved)}): {', '.join(unresolved)}")
    if not rows:
        return
    with st.expander(f"Şekil kaynakları: klasör dışı ({len(rows)} SKU)", expanded=bool(unresolved)):
        st.dataframe(pd.DataFrame([{
            "SKU": sku, "Şekil": cp.SHAPE_LABEL.get(sh.shape, ""),
            "Kaynak": _SOURCE_LABEL.get(sh.source, sh.source), "Ayrıntı": sh.detail,
        } for sku, sh in rows]), use_container_width=True, hide_index=True)
        st.caption("Elle atama data/crmc_shapes.json'a yazılır ve klasör sonucunu ezer. "
                   "'—' seçmek elle atamayı kaldırır.")
        manual = cp.load_manual_shapes()
        options = ["—", cp.ROUND, cp.HEART]
        with st.form("crmc_shape_form"):
            picks = {}
            cols = st.columns(3)
            for i, (sku, sh) in enumerate(rows):
                cur = manual.get(sku, "—")
                picks[sku] = cols[i % 3].selectbox(sku, options, index=options.index(cur), key=f"crmc_shape_{sku}")
            if st.form_submit_button("💾 Şekilleri kaydet"):
                for sku, val in picks.items():
                    if val == "—":
                        manual.pop(sku, None)
                    else:
                        manual[sku] = val
                cp.save_manual_shapes(manual)
                st.rerun()
