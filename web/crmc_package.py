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


def _block_rows(blocks, printed) -> pd.DataFrame:
    rows = []
    for n, b in enumerate(cp.sort_blocks(blocks), 1):
        rows.append({
            "#": n,
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

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Blok", len(candidates))
    m2.metric("Sayfa", sum(b.page_count for b in candidates))
    m3.metric("Diğer SKU'lu blok", sum(b.is_other for b in candidates))
    m4.metric("Uyarı", len(warnings))

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

    st.markdown("**Bloklar** (PDF sırası; DİĞER bölümü en sonda)")
    st.dataframe(_block_rows(candidates, printed), use_container_width=True, hide_index=True)

    if st.button("📄 PDF Oluştur", type="primary", key="crmc_build"):
        run_id = cp.new_run_id()
        slips = {p.package_id: p.slips for p in res.packages if p.package_id in shown_pkgs}
        with st.spinner("PDF hazırlanıyor..."):
            files = cp.build_pdfs(candidates, slips, run_id, dict(Counter(w["tür"] for w in warnings)))
        st.session_state["crmc_outputs"] = {
            "run_id": run_id, "files": files, "keys": [b.key for b in candidates],
        }

    out = st.session_state.get("crmc_outputs")
    if out:
        st.success(f"Çalıştırma {out['run_id']}: {len(out['keys'])} blok, {len(out['files'])} dosya.")
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
