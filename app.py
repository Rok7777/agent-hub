"""
Agent Hub — Avtomatska dodelitev lotov za maloprodajne dokumente v Minimaxu.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import traceback

from minimax_client import (
    MinimaxClient, LOCATIONS,
    parse_stock_to_engine_format, parse_entry_to_lines,
)
from lot_engine import assign_lots, assign_lots_with_virtual, check_old_lots

# ── Nastavitve strani ─────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Agent Hub | Lot dodelitev",
    page_icon="🐟",
    layout="wide",
)

st.title("🐟 Agent Hub — Dodelitev lotov")
st.caption("Avtomatska FIFO dodelitev serij za maloprodajne dokumente v Minimaxu")

# ── Stranska vrstica: nastavitve ──────────────────────────────────────────────

# ── Branje iz Streamlit Secrets (ali privzetih vrednosti) ──────────────────
def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return default

with st.sidebar:
    st.header("⚙️ Nastavitve API")

    with st.expander("Minimax dostop", expanded=True):
        st.caption("Podatki odjemalca (iz emaila Minimax podpore):")
        client_id     = st.text_input("Client ID",        value=_secret("MINIMAX_CLIENT_ID", "OltreCon"))
        client_secret = st.text_input("Client Secret",    value=_secret("MINIMAX_CLIENT_SECRET", ""), type="password")
        st.caption("Podatki uporabnika:")
        username      = st.text_input("Uporabniško ime",  value=_secret("MINIMAX_USERNAME", "Agent-hub"))
        password      = st.text_input("Geslo aplikacije", value=_secret("MINIMAX_PASSWORD", ""), type="password")
        st.caption("Organizacija:")
        org_id        = st.text_input("ID organizacije",  value=_secret("MINIMAX_ORG_ID", "171038"))

    st.divider()

    with st.expander("Kode skladišč", expanded=True):
        wh_mpk1 = st.text_input("MPK1 — Potujoča 1",  value=_secret("WH_MPK1", "MP-K1"))
        wh_mpk2 = st.text_input("MPK2 — Potujoča 2",  value=_secret("WH_MPK2", "MP-K2"))
        wh_mpk3 = st.text_input("MPK3 — Potujoča 3",  value=_secret("WH_MPK3", "MP-K3"))
        wh_mpoc = st.text_input("MPOC — Rib. Domžale", value=_secret("WH_MPOC", "MP-RD"))

    st.divider()

    with st.expander("Kode analitik", expanded=True):
        an_mpk1 = st.text_input("Analytic koda MPK1", value=_secret("AN_MPK1", "MPK1"))
        an_mpk2 = st.text_input("Analytic koda MPK2", value=_secret("AN_MPK2", "MPK2"))
        an_mpk3 = st.text_input("Analytic koda MPK3", value=_secret("AN_MPK3", "MPK3"))
        an_mpoc = st.text_input("Analytic koda MPOC", value=_secret("AN_MPOC", "MPOC"))

    st.divider()
    if st.button("🔍 Poišči ID-je analitik avtomatsko"):
        st.session_state["auto_find_analytics"] = True
    if st.button("🔍 Poišči ID-je skladišč avtomatsko"):
        st.session_state["auto_find_warehouses"] = True
    if st.button("🔧 Diagnostika lotov (MPK2)"):
        st.session_state["diagnose_lots"] = True



# ── Preverjanje nastavitev ────────────────────────────────────────────────────

def _check_config() -> bool:
    if not all([username, password, client_id, client_secret, org_id]):
        st.warning("⚠️ Izpolnite vse nastavitve API v stranski vrstici.")
        return False
    return True

def _make_client() -> MinimaxClient:
    return MinimaxClient(
        username      = username,
        password      = password,
        client_id     = client_id,
        client_secret = client_secret,
        org_id        = int(org_id),
    )

# Kode ki jih je vnesel uporabnik — numerične ID-je poiščemo dinamično
WH_CODES = {"MPK1": wh_mpk1, "MPK2": wh_mpk2, "MPK3": wh_mpk3, "MPOC": wh_mpoc}
AN_CODES = {"MPK1": an_mpk1, "MPK2": an_mpk2, "MPK3": an_mpk3, "MPOC": an_mpoc}

@st.cache_data(ttl=3600, show_spinner=False)
def _resolve_ids(_username, _password, _client_id, _client_secret, _org_id):
    """Poišče numerične ID-je skladišč in analitik iz kod. Cache 1h."""
    cli = MinimaxClient(
        username=_username, password=_password,
        client_id=_client_id, client_secret=_client_secret,
        org_id=int(_org_id),
    )
    wh_map, an_map = {}, {}
    try:
        for row in cli.get_warehouses():
            code = (row.get("Code") or "").strip().upper()
            wid  = row.get("WarehouseId") or row.get("ID")
            if code and wid:
                wh_map[code] = int(wid)
    except Exception:
        pass
    try:
        for row in cli.get_analytics():
            code = (row.get("Code") or "").strip().upper()
            aid  = row.get("AnalyticId")
            if code and aid:
                an_map[code] = int(aid)
    except Exception:
        pass
    return wh_map, an_map

def _get_wh_id(loc_key: str) -> int:
    code = WH_CODES.get(loc_key, "").strip().upper()
    if not code:
        return 0
    if all([username, password, client_id, client_secret, org_id]):
        wh_map, _ = _resolve_ids(username, password, client_id, client_secret, org_id)
        return wh_map.get(code, 0)
    return 0

def _get_an_id(loc_key: str) -> int:
    code = AN_CODES.get(loc_key, "").strip().upper()
    if not code:
        return 0
    if all([username, password, client_id, client_secret, org_id]):
        _, an_map = _resolve_ids(username, password, client_id, client_secret, org_id)
        return an_map.get(code, 0)
    return 0

# ── Auto-iskanje analitik ─────────────────────────────────────────────────────

if st.session_state.get("auto_find_analytics") and _check_config():
    st.session_state.pop("auto_find_analytics")
    with st.spinner("Iščem analitike v Minimaxu ..."):
        try:
            cli  = _make_client()
            rows = cli.get_analytics()
            df   = pd.DataFrame([{
                "Koda":       r.get("Code",""),
                "Naziv":      r.get("Name",""),
                "Analytic ID": r.get("AnalyticId",""),
            } for r in rows])
            st.sidebar.success("✅ Analitike najdene!")
            st.sidebar.dataframe(df, use_container_width=True)
            st.sidebar.caption("Prekopirajte ID-je v polja zgoraj.")
        except Exception as e:
            st.sidebar.error(f"Napaka: {e}")

# ── Diagnostika lotov ────────────────────────────────────────────────────────

if st.session_state.get("diagnose_lots") and _check_config():
    st.session_state.pop("diagnose_lots")
    with st.spinner("Iščem dokumente z loti za MPK2 ..."):
        try:
            cli  = _make_client()
            wh   = _get_wh_id("MPK2")
            diag = cli.diagnose_lots(wh)
            st.sidebar.success("✅ Diagnostika:")
            st.sidebar.write(f"Warehouse ID: {diag['warehouse_id']}")
            if diag['found']:
                for f in diag['found']:
                    st.sidebar.write(f"Tip {f['type']}: lot={f['batch']}, wh_from={f['wh_from']}, wh_to={f['wh_to']}")
            else:
                st.sidebar.warning("Ni dokumentov z loti v zadnjih 14 dneh!")
        except Exception as e:
            st.sidebar.error(f"Napaka: {e}")

# ── Auto-iskanje skladišč ────────────────────────────────────────────────────

if st.session_state.get("auto_find_warehouses") and _check_config():
    st.session_state.pop("auto_find_warehouses")
    with st.spinner("Iščem skladišča v Minimaxu ..."):
        try:
            cli  = _make_client()
            rows = cli.get_warehouses()
            df   = pd.DataFrame([{
                "Naziv":        r.get("Name",""),
                "Koda":         r.get("Code",""),
                "Warehouse ID": r.get("WarehouseId") or r.get("ID",""),
            } for r in rows])
            st.sidebar.success("✅ Skladišča najdena!")
            st.sidebar.dataframe(df, use_container_width=True)
            st.sidebar.caption("Poiščite MPK1/MPK2/MPK3/MPOC in prekopirajte ID-je v polja zgoraj.")
        except Exception as e:
            st.sidebar.error(f"Napaka: {e}")

# ── Zavihki za lokacije ───────────────────────────────────────────────────────

tabs = st.tabs([
    "🚐 MPK1 — Potujoča 1",
    "🚐 MPK2 — Potujoča 2",
    "🚐 MPK3 — Potujoča 3",
    "🏪 MPOC — Ribarnica Domžale",
])

LOC_KEYS = ["MPK1", "MPK2", "MPK3", "MPOC"]

for tab, loc_key in zip(tabs, LOC_KEYS):
    with tab:
        loc_name  = LOCATIONS[loc_key]["name"]
        wh_id     = _get_wh_id(loc_key)
        an_id     = _get_an_id(loc_key)

        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader(f"{loc_name}")
        with col2:
            find_btn = st.button(
                f"🔍 Poišči osnutke",
                key=f"find_{loc_key}",
                use_container_width=True,
            )

        if find_btn:
            if not _check_config():
                st.stop()
            if an_id == 0:
                # Poskusi prisilno razrešiti analitike
                with st.spinner("Iščem analitike..."):
                    try:
                        cli2 = _make_client()
                        _resolve_ids.clear()
                        an_id = _get_an_id(loc_key)
                    except Exception:
                        pass
            if an_id == 0:
                st.error("Ne najdem analitike za to lokacijo. Preverite kodo analitike v nastavitvah.")
                st.stop()

            with st.spinner("Iščem osnutke dokumentov ..."):
                try:
                    cli     = _make_client()
                    drafts  = cli.get_draft_entries(an_id)
                    st.session_state[f"drafts_{loc_key}"] = drafts
                except Exception as e:
                    st.error(f"Napaka pri branju osnutkov: {e}")
                    st.session_state[f"drafts_{loc_key}"] = []

        drafts = st.session_state.get(f"drafts_{loc_key}", None)

        if drafts is None:
            st.info("Kliknite 'Poišči osnutke' za prikaz čakajočih dokumentov.")
            continue

        if not drafts:
            st.success("✅ Ni čakajočih osnutkov za to lokacijo.")
            continue

        st.write(f"Najdenih **{len(drafts)}** osnutkov:")

        # ── Checkboxi za izbiro dokumentov ───────────────────────────────────
        st.caption("Izberite dokumente za obdelavo (kronološki vrstni red):")
        select_all = st.checkbox("☑ Izberi vse", key=f"sel_all_{loc_key}", value=True)

        selected_ids = []
        for d in sorted(drafts, key=lambda x: str(x.get("Date",""))):
            label = f"IS-{d.get('Number','?')} — {str(d.get('Date',''))[:10]}"
            cb_key = f"cb_{loc_key}_{d.get('StockEntryId')}"
            checked = st.checkbox(label, key=cb_key, value=select_all)
            if checked:
                selected_ids.append(d.get("StockEntryId"))

        st.divider()

        run_btn = st.button(
            f"⚡ Obdelaj vse označene osnutke ({len(selected_ids)})",
            key=f"run_{loc_key}",
            type="primary",
            use_container_width=True,
            disabled=len(selected_ids) == 0,
        )

        if run_btn and selected_ids:
            if wh_id == 0:
                st.error("Vnesite Warehouse kodo za to lokacijo v nastavitvah.")
                st.stop()

            with st.spinner(f"Berem zalogo in obdelujem {len(selected_ids)} dokumentov ... ⏳"):
                try:
                    cli = _make_client()

                    # Razvrsti po datumu kronološko
                    sorted_ids = sorted(
                        selected_ids,
                        key=lambda eid: str(next(
                            (d.get("Date","") for d in drafts if d.get("StockEntryId") == eid), ""
                        ))
                    )

                    # Preberi vse dokumente in zberi article IDs
                    all_entry_data = {}
                    all_doc_lines  = {}
                    all_item_ids   = set()

                    # Prvo branje brez enot (da dobimo article IDs)
                    for eid in sorted_ids:
                        ed = cli.get_entry_detail(eid)
                        dl = parse_entry_to_lines(ed)
                        all_entry_data[eid] = ed
                        all_doc_lines[eid]  = dl
                        for l in dl:
                            if l.get("article_id"):
                                all_item_ids.add(l["article_id"])

                    # Pridobi pravilne enote iz artikelskega šifranta
                    item_units = cli.get_item_units(list(all_item_ids))

                    # Ponovno razčleni z enotami
                    for eid in sorted_ids:
                        all_doc_lines[eid] = parse_entry_to_lines(all_entry_data[eid], item_units)

                    # Preberi zalogo enkrat za vse
                    stock_raw = cli.get_stock_by_lots(wh_id)
                    has_lots  = any(r.get("BatchNumber") for r in stock_raw)
                    if not has_lots and all_item_ids:
                        stock_raw = cli.get_stock_for_items(wh_id, list(all_item_ids))

                    stock = parse_stock_to_engine_format(stock_raw)
                    today = datetime.now()

                    # Skupna virtualna zaloga — deli se med vsemi dokumenti
                    shared_virtual = {
                        key: [lot.copy() for lot in data["lots"]]
                        for key, data in stock.items()
                    }

                    # Obdelaj kronološko z deljeno zalogo
                    all_results = {}
                    for eid in sorted_ids:
                        all_results[eid] = assign_lots_with_virtual(
                            all_doc_lines[eid], stock, shared_virtual, today
                        )

                    # Opozorila samo za artikle iz obdelanih dokumentov
                    doc_article_ids = {l["article_id"] for eid in sorted_ids
                                       for l in all_doc_lines[eid] if l.get("article_id")}
                    old_lot_warnings = check_old_lots(stock, today, doc_article_ids)

                    st.session_state[f"multi_result_{loc_key}"] = {
                        "sorted_ids":       sorted_ids,
                        "all_results":      all_results,
                        "all_entry_data":   all_entry_data,
                        "old_lot_warnings": old_lot_warnings,
                        "drafts":           drafts,
                    }
                except Exception as e:
                    st.error(f"Napaka pri obdelavi: {e}")
                    st.error(traceback.format_exc())

        # ── Prikaz rezultatov skupne obdelave ────────────────────────────────
        multi_res = st.session_state.get(f"multi_result_{loc_key}")

        if multi_res:
            st.divider()
            sorted_ids     = multi_res["sorted_ids"]
            all_results    = multi_res["all_results"]
            all_entry_data = multi_res["all_entry_data"]
            drafts_map     = {d.get("StockEntryId"): d for d in multi_res["drafts"]}

            # Skupna statistika
            def row_color(s):
                return {"ok":"🟢","matched":"🟡","partial":"🟠","no_match":"🔴","no_lots":"🔴"}.get(s,"⚪")

            total_ok      = sum(len([l for l in r if l["status"]=="ok"])           for r in all_results.values())
            total_matched = sum(len([l for l in r if l["status"]=="matched"])       for r in all_results.values())
            total_partial = sum(len([l for l in r if l["status"]=="partial"])       for r in all_results.values())
            total_none    = sum(len([l for l in r if l["status"] in ("no_match","no_lots")]) for r in all_results.values())

            c1,c2,c3,c4 = st.columns(4)
            c1.metric("✅ Točno ujemanje",    total_ok)
            c2.metric("🔄 Pametna zamenjava", total_matched)
            c3.metric("⚠️ Delno pokrito",     total_partial)
            c4.metric("❌ Brez lota",          total_none)

            # Prikaz po dokumentih
            for eid in sorted_ids:
                lines = all_results[eid]
                d     = drafts_map.get(eid, {})
                label = f"IS-{d.get('Number','?')} — {str(d.get('Date',''))[:10]}"
                no_lot_count = len([l for l in lines if l["status"] in ("no_match","no_lots","partial")])
                icon = "✅" if no_lot_count == 0 else "⚠️"
                with st.expander(f"{icon} {label}  ({len(lines)} vrstic)", expanded=(no_lot_count > 0)):
                    df_r = pd.DataFrame([{
                        "":      row_color(l["status"]),
                        "Artikel": l["article_name"],
                        "Kol.":  l["quantity_assigned"],
                        "ME":    l["unit"],
                        "Lot":   l.get("lot") or "—",
                        "Opis":  l.get("opis") or "",
                    } for l in lines])
                    st.dataframe(df_r, use_container_width=True, hide_index=True)

            # ── Poročilo napak (brez lota / delno) ───────────────────────────────
            error_rows = []
            for eid in sorted_ids:
                lines_e = all_results[eid]
                d_e     = drafts_map.get(eid, {})
                doc_num = f"IS-{d_e.get('Number','?')}"
                doc_date = str(d_e.get('Date',''))[:10]
                orig_doc = (all_entry_data[eid].get("OriginalDocumentType") or {})
                orig_num = all_entry_data[eid].get("OriginalDocumentDate", "") or ""
                for i, l in enumerate(lines_e, 1):
                    if l["status"] in ("no_match", "no_lots", "partial"):
                        status_opis = {
                            "no_match": "Ni zaloge za artikel",
                            "no_lots":  "Ni ustreznih lotov",
                            "partial":  "Premalo zaloge",
                        }.get(l["status"], l["status"])
                        # Izvleči opis napake iz polja opis
                        detail = l.get("opis", "") or ""
                        if "[" in detail:
                            detail = detail[detail.find("[")+1:detail.rfind("]")]
                        error_rows.append({
                            "Analitika":  loc_key,
                            "Dokument":   doc_num,
                            "Datum":      doc_date,
                            "Vrstica":    i,
                            "Artikel":    l["article_name"],
                            "Kol.":       l["quantity_assigned"],
                            "ME":         l.get("unit",""),
                            "Napaka":     status_opis,
                            "Podrobnost": detail,
                        })

            if error_rows:
                with st.expander(f"📋 Poročilo napak — za ročno popravilo ({len(error_rows)} vrstic)", expanded=True):
                    df_err = pd.DataFrame(error_rows)
                    st.dataframe(df_err, use_container_width=True, hide_index=True)
                    # CSV prenos
                    csv = df_err.to_csv(index=False, sep=";", encoding="utf-8-sig")
                    st.download_button(
                        label="⬇️ Prenesi poročilo (CSV)",
                        data=csv,
                        file_name=f"napake_{loc_key}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                    )

            # Opozorilo starih lotov
            old_lots = multi_res.get("old_lot_warnings", [])
            if old_lots:
                with st.expander(f"⏰ Stari loti na zalogi ({len(old_lots)} opozoril)"):
                    df_old = pd.DataFrame([{
                        "Artikel":   w["article"],
                        "Lot":       w["lot"],
                        "Dni star":  w["days_old"],
                        "Qty":       f"{w['qty']} {w['unit']}",
                        "Opozorilo": w["warning"],
                    } for w in old_lots])
                    st.dataframe(df_old, use_container_width=True, hide_index=True)
                    st.caption("Ti loti so na zalogi dlje kot pričakovano. Preverite kalo faktor.")

            if total_partial + total_none > 0:
                st.warning(f"⚠️ {total_partial + total_none} vrstic(a) brez lota. Preverite ročno pred potrditvijo.")

            st.divider()
            col_save, col_cancel = st.columns(2)
            with col_save:
                save_all_btn = st.button(
                    f"💾 Shrani vse v Minimax ({len(sorted_ids)} dokumentov)",
                    key=f"save_all_{loc_key}",
                    type="primary",
                    use_container_width=True,
                )
            with col_cancel:
                cancel_btn = st.button("✖ Zavrzi rezultate", key=f"cancel_multi_{loc_key}", use_container_width=True)

            if cancel_btn:
                del st.session_state[f"multi_result_{loc_key}"]
                st.rerun()

            if save_all_btn:
                with st.spinner(f"Shranjujem {len(sorted_ids)} dokumentov v Minimax ..."):
                    errors = []
                    saved  = 0
                    try:
                        cli = _make_client()
                        for eid in sorted_ids:
                            try:
                                cli.update_entry_with_lots(
                                    entry_id   = eid,
                                    entry_data = all_entry_data[eid],
                                    new_rows   = all_results[eid],
                                )
                                saved += 1
                            except Exception as e:
                                errors.append(f"IS-{drafts_map.get(eid,{}).get('Number','?')}: {e}")
                    except Exception as e:
                        st.error(f"Napaka pri povezavi: {e}")

                    if saved > 0:
                        st.success(f"✅ {saved}/{len(sorted_ids)} dokumentov shranjenih v Minimax!")
                    for err in errors:
                        st.error(err)

                    del st.session_state[f"multi_result_{loc_key}"]
                    if f"drafts_{loc_key}" in st.session_state:
                        del st.session_state[f"drafts_{loc_key}"]
                    st.rerun()

# ── Noga ─────────────────────────────────────────────────────────────────────

st.divider()
st.caption("Agent Hub v1.0 · Minimax API · FIFO + smart matching za ribje artikle")
