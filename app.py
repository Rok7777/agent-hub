"""
Agent Hub — Dodelitev lotov + Obdelava temeljnic za Minimax.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import traceback

from minimax_client import (
    MinimaxClient, LOCATIONS, BLAGAJNE,
    parse_stock_to_engine_format, parse_entry_to_lines,
)
from lot_engine import assign_lots, assign_lots_with_virtual, check_old_lots

st.set_page_config(page_title="Agent Hub", page_icon="🐟", layout="wide")
st.title("🐟 Agent Hub")

def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return default

# ── Stranska vrstica ──────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Nastavitve API")
    with st.expander("Minimax dostop", expanded=True):
        st.caption("Podatki odjemalca:")
        client_id     = st.text_input("Client ID",        value=_secret("MINIMAX_CLIENT_ID", "OltreCon"))
        client_secret = st.text_input("Client Secret",    value=_secret("MINIMAX_CLIENT_SECRET", ""), type="password")
        st.caption("Podatki uporabnika:")
        username      = st.text_input("Uporabniško ime",  value=_secret("MINIMAX_USERNAME", "Agent-hub"))
        password      = st.text_input("Geslo aplikacije", value=_secret("MINIMAX_PASSWORD", ""), type="password")
        st.caption("Organizacija:")
        org_id        = st.text_input("ID organizacije",  value=_secret("MINIMAX_ORG_ID", "171038"))
    st.divider()
    with st.expander("Kode skladišč", expanded=True):
        wh_mpk1 = st.text_input("MPK1 — Potujoča 1",   value=_secret("WH_MPK1", "MP-K1"))
        wh_mpk2 = st.text_input("MPK2 — Potujoča 2",   value=_secret("WH_MPK2", "MP-K2"))
        wh_mpk3 = st.text_input("MPK3 — Potujoča 3",   value=_secret("WH_MPK3", "MP-K3"))
        wh_mpoc = st.text_input("MPOC — Rib. Domžale",  value=_secret("WH_MPOC", "MP-RD"))
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


def _check_config() -> bool:
    if not all([username, password, client_id, client_secret, org_id]):
        st.warning("⚠️ Izpolnite vse nastavitve API v stranski vrstici.")
        return False
    return True

def _make_client() -> MinimaxClient:
    return MinimaxClient(
        username=username, password=password,
        client_id=client_id, client_secret=client_secret, org_id=int(org_id),
    )

WH_CODES = {"MPK1": wh_mpk1, "MPK2": wh_mpk2, "MPK3": wh_mpk3, "MPOC": wh_mpoc}
AN_CODES = {"MPK1": an_mpk1, "MPK2": an_mpk2, "MPK3": an_mpk3, "MPOC": an_mpoc}

@st.cache_data(ttl=3600, show_spinner=False)
def _resolve_ids(_username, _password, _client_id, _client_secret, _org_id):
    cli = MinimaxClient(username=_username, password=_password,
                        client_id=_client_id, client_secret=_client_secret, org_id=int(_org_id))
    wh_map, an_map = {}, {}
    try:
        for row in cli.get_warehouses():
            code = (row.get("Code") or "").strip().upper()
            wid  = row.get("WarehouseId") or row.get("ID")
            if code and wid: wh_map[code] = int(wid)
    except Exception: pass
    try:
        for row in cli.get_analytics():
            code = (row.get("Code") or "").strip().upper()
            aid  = row.get("AnalyticId")
            if code and aid: an_map[code] = int(aid)
    except Exception: pass
    return wh_map, an_map

def _get_wh_id(loc_key):
    code = WH_CODES.get(loc_key, "").strip().upper()
    if not code: return 0
    if all([username, password, client_id, client_secret, org_id]):
        wh_map, _ = _resolve_ids(username, password, client_id, client_secret, org_id)
        return wh_map.get(code, 0)
    return 0

def _get_an_id(loc_key):
    code = AN_CODES.get(loc_key, "").strip().upper()
    if not code: return 0
    if all([username, password, client_id, client_secret, org_id]):
        _, an_map = _resolve_ids(username, password, client_id, client_secret, org_id)
        return an_map.get(code, 0)
    return 0

# Sidebar akcije
if st.session_state.get("auto_find_analytics") and _check_config():
    st.session_state.pop("auto_find_analytics")
    with st.spinner("Iščem analitike ..."):
        try:
            rows = _make_client().get_analytics()
            st.sidebar.success("✅ Analitike najdene!")
            st.sidebar.dataframe(pd.DataFrame([{"Koda": r.get("Code",""), "Naziv": r.get("Name",""), "ID": r.get("AnalyticId","")} for r in rows]), use_container_width=True)
        except Exception as e:
            st.sidebar.error(f"Napaka: {e}")

if st.session_state.get("diagnose_lots") and _check_config():
    st.session_state.pop("diagnose_lots")
    with st.spinner("Diagnostika ..."):
        try:
            diag = _make_client().diagnose_lots(_get_wh_id("MPK2"))
            st.sidebar.success(f"✅ WH ID: {diag['warehouse_id']}")
            for f in diag.get('found', []): st.sidebar.write(f"lot={f['batch']}")
        except Exception as e:
            st.sidebar.error(f"Napaka: {e}")

if st.session_state.get("auto_find_warehouses") and _check_config():
    st.session_state.pop("auto_find_warehouses")
    with st.spinner("Iščem skladišča ..."):
        try:
            rows = _make_client().get_warehouses()
            st.sidebar.success("✅ Skladišča najdena!")
            st.sidebar.dataframe(pd.DataFrame([{"Naziv": r.get("Name",""), "Koda": r.get("Code",""), "ID": r.get("WarehouseId") or r.get("ID","")} for r in rows]), use_container_width=True)
        except Exception as e:
            st.sidebar.error(f"Napaka: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# GLAVNA NAVIGACIJA
# ══════════════════════════════════════════════════════════════════════════════

main_tab1, main_tab2 = st.tabs([
    "📦 Loti — dodelitev serij",
    "💰 Temeljnice — dnevni izkupiček",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: LOTI
# ══════════════════════════════════════════════════════════════════════════════

with main_tab1:
    st.caption("Avtomatska FIFO dodelitev serij za maloprodajne dokumente v Minimaxu")

    tabs = st.tabs(["🚐 MPK1 — Potujoča 1", "🚐 MPK2 — Potujoča 2", "🚐 MPK3 — Potujoča 3", "🏪 MPOC — Ribarnica Domžale"])
    LOC_KEYS = ["MPK1", "MPK2", "MPK3", "MPOC"]

    for tab, loc_key in zip(tabs, LOC_KEYS):
        with tab:
            loc_name = LOCATIONS[loc_key]["name"]
            wh_id    = _get_wh_id(loc_key)
            an_id    = _get_an_id(loc_key)

            col1, col2 = st.columns([2, 1])
            with col1: st.subheader(loc_name)
            with col2:
                find_btn = st.button("🔍 Poišči osnutke", key=f"find_{loc_key}", use_container_width=True)

            if find_btn:
                if not _check_config(): st.stop()
                if an_id == 0:
                    with st.spinner("Iščem analitike..."):
                        try:
                            _resolve_ids.clear()
                            an_id = _get_an_id(loc_key)
                        except Exception: pass
                if an_id == 0:
                    st.error("Ne najdem analitike. Preverite kodo v nastavitvah.")
                    st.stop()
                with st.spinner("Iščem osnutke ..."):
                    try:
                        drafts = _make_client().get_draft_entries(an_id)
                        st.session_state[f"drafts_{loc_key}"] = drafts
                    except Exception as e:
                        st.error(f"Napaka: {e}")
                        st.session_state[f"drafts_{loc_key}"] = []

            drafts = st.session_state.get(f"drafts_{loc_key}", None)
            if drafts is None:
                st.info("Kliknite 'Poišči osnutke' za prikaz čakajočih dokumentov.")
                continue
            if not drafts:
                st.success("✅ Ni čakajočih osnutkov.")
                continue

            st.write(f"Najdenih **{len(drafts)}** osnutkov:")
            sel_all = st.checkbox("☑ Izberi vse", key=f"sel_all_{loc_key}", value=True)
            selected_ids = []
            for d in sorted(drafts, key=lambda x: str(x.get("Date",""))):
                label = f"IS-{d.get('Number','?')} — {str(d.get('Date',''))[:10]}"
                if st.checkbox(label, key=f"cb_{loc_key}_{d.get('StockEntryId')}", value=sel_all):
                    selected_ids.append(d.get("StockEntryId"))

            st.divider()
            run_btn = st.button(f"⚡ Obdelaj vse označene ({len(selected_ids)})", key=f"run_{loc_key}",
                                type="primary", use_container_width=True, disabled=len(selected_ids)==0)

            if run_btn and selected_ids:
                if wh_id == 0:
                    st.error("Vnesite Warehouse kodo v nastavitvah.")
                    st.stop()
                with st.spinner(f"Obdelujem {len(selected_ids)} dokumentov ... ⏳"):
                    try:
                        cli = _make_client()
                        sorted_ids = sorted(selected_ids, key=lambda eid: str(next((d.get("Date","") for d in drafts if d.get("StockEntryId")==eid), "")))
                        all_entry_data, all_doc_lines, all_item_ids = {}, {}, set()
                        for eid in sorted_ids:
                            ed = cli.get_entry_detail(eid)
                            dl = parse_entry_to_lines(ed)
                            all_entry_data[eid] = ed
                            all_doc_lines[eid]  = dl
                            for l in dl:
                                if l.get("article_id"): all_item_ids.add(l["article_id"])
                        item_units = cli.get_item_units(list(all_item_ids))
                        for eid in sorted_ids:
                            all_doc_lines[eid] = parse_entry_to_lines(all_entry_data[eid], item_units)
                        stock_raw = cli.get_stock_by_lots(wh_id)
                        if not any(r.get("BatchNumber") for r in stock_raw) and all_item_ids:
                            stock_raw = cli.get_stock_for_items(wh_id, list(all_item_ids))
                        stock = parse_stock_to_engine_format(stock_raw)
                        today = datetime.now()
                        shared_virtual = {k: [l.copy() for l in v["lots"]] for k, v in stock.items()}
                        all_results = {eid: assign_lots_with_virtual(all_doc_lines[eid], stock, shared_virtual, today) for eid in sorted_ids}
                        st.session_state[f"multi_result_{loc_key}"] = {
                            "sorted_ids": sorted_ids, "all_results": all_results,
                            "all_entry_data": all_entry_data,
                            "old_lot_warnings": check_old_lots(stock, today), "drafts": drafts,
                        }
                    except Exception as e:
                        st.error(f"Napaka: {e}")
                        st.error(traceback.format_exc())

            multi_res = st.session_state.get(f"multi_result_{loc_key}")
            if multi_res:
                st.divider()
                sorted_ids     = multi_res["sorted_ids"]
                all_results    = multi_res["all_results"]
                all_entry_data = multi_res["all_entry_data"]
                drafts_map     = {d.get("StockEntryId"): d for d in multi_res["drafts"]}
                rc = lambda s: {"ok":"🟢","matched":"🟡","partial":"🟠","no_match":"🔴","no_lots":"🔴"}.get(s,"⚪")
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("✅ Točno",    sum(len([l for l in r if l["status"]=="ok"])           for r in all_results.values()))
                c2.metric("🔄 Zamenjava",sum(len([l for l in r if l["status"]=="matched"])       for r in all_results.values()))
                c3.metric("⚠️ Delno",   sum(len([l for l in r if l["status"]=="partial"])       for r in all_results.values()))
                c4.metric("❌ Brez",    sum(len([l for l in r if l["status"] in ("no_match","no_lots")]) for r in all_results.values()))
                for eid in sorted_ids:
                    lines = all_results[eid]
                    d = drafts_map.get(eid, {})
                    no_lot = len([l for l in lines if l["status"] in ("no_match","no_lots","partial")])
                    with st.expander(f"{'✅' if no_lot==0 else '⚠️'} IS-{d.get('Number','?')} — {str(d.get('Date',''))[:10]}  ({len(lines)} vrstic)", expanded=(no_lot>0)):
                        st.dataframe(pd.DataFrame([{"": rc(l["status"]), "Artikel": l["article_name"], "Kol.": l["quantity_assigned"], "ME": l["unit"], "Lot": l.get("lot") or "—", "Opis": l.get("opis") or ""} for l in lines]), use_container_width=True, hide_index=True)
                old_lots = multi_res.get("old_lot_warnings", [])
                if old_lots:
                    with st.expander(f"⏰ Stari loti ({len(old_lots)})"):
                        st.dataframe(pd.DataFrame([{"Artikel": w["article"], "Lot": w["lot"], "Dni": w["days_old"], "Qty": f"{w['qty']} {w['unit']}", "Opozorilo": w["warning"]} for w in old_lots]), use_container_width=True, hide_index=True)
                st.divider()
                c_save, c_cancel = st.columns(2)
                with c_save:
                    save_btn = st.button(f"💾 Shrani vse ({len(sorted_ids)} dok.)", key=f"save_all_{loc_key}", type="primary", use_container_width=True)
                with c_cancel:
                    if st.button("✖ Zavrzi", key=f"cancel_{loc_key}", use_container_width=True):
                        del st.session_state[f"multi_result_{loc_key}"]
                        st.rerun()
                if save_btn:
                    with st.spinner("Shranjujem ..."):
                        errors, saved = [], 0
                        try:
                            cli = _make_client()
                            for eid in sorted_ids:
                                try:
                                    cli.update_entry_with_lots(entry_id=eid, entry_data=all_entry_data[eid], new_rows=all_results[eid])
                                    saved += 1
                                except Exception as e:
                                    errors.append(f"IS-{drafts_map.get(eid,{}).get('Number','?')}: {e}")
                        except Exception as e:
                            st.error(f"Napaka: {e}")
                        if saved > 0: st.success(f"✅ {saved}/{len(sorted_ids)} shranjenih!")
                        for err in errors: st.error(err)
                        del st.session_state[f"multi_result_{loc_key}"]
                        st.session_state.pop(f"drafts_{loc_key}", None)
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: TEMELJNICE — DNEVNI IZKUPIČEK
# ══════════════════════════════════════════════════════════════════════════════

with main_tab2:
    st.caption("Pregled osnutkov temeljnic, popravek knjižb in navodila za vnos v blagajno")

    col_btn, col_space = st.columns([1, 2])
    with col_btn:
        scan_btn = st.button("🔍 Poišči osnutke temeljnic", type="primary",
                             use_container_width=True, key="scan_journals")

    if scan_btn:
        if not _check_config(): st.stop()
        with st.spinner("Iščem osnutke temeljnic ..."):
            try:
                cli      = _make_client()
                osnutki_raw = cli.get_journal_drafts()
                osnutki  = []
                for j in osnutki_raw:
                    podatki = cli.parse_journal_placila(j)
                    if podatki:
                        osnutki.append(podatki)
                st.session_state["journal_osnutki"] = osnutki
                st.session_state.pop("journal_rezultat", None)
            except Exception as e:
                st.error(f"Napaka: {e}")
                st.error(traceback.format_exc())

    osnutki = st.session_state.get("journal_osnutki", None)

    if osnutki is None:
        st.info("👆 Kliknite 'Poišči osnutke temeljnic' za začetek.")

    elif len(osnutki) == 0:
        st.success("✅ Ni osnutkov temeljnic za obdelavo.")

    else:
        st.divider()
        st.subheader(f"Najdenih {len(osnutki)} osnutkov")

        # Izberi vse checkbox
        sel_all_j = st.checkbox("☑ Izberi vse", value=True, key="j_sel_all")
        izbrani = []

        # Grupiranje po blagajnah
        from collections import defaultdict
        po_blagajnah = defaultdict(list)
        for o in osnutki:
            po_blagajnah[o["analitika_sifra"]].append(o)

        # Prikaz po blagajnah
        for sifra in sorted(po_blagajnah.keys()):
            skupina = sorted(po_blagajnah[sifra], key=lambda x: x["datum"])
            naziv   = skupina[0]["blagajna_naziv"]
            skupaj_blagajna = sum(o["skupaj"] for o in skupina)

            st.markdown(f"### 🏪 {sifra} — {naziv}")
            st.caption(f"Skupaj: **{skupaj_blagajna:.2f} €** | {len(skupina)} osnutek/ov")

            # Glava tabele
            hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([0.5, 1.5, 1.5, 1, 1, 1])
            hc1.markdown("**✓**")
            hc2.markdown("**Datum**")
            hc3.markdown("**Vrsta plačila**")
            hc4.markdown("**Gotovina**")
            hc5.markdown("**Kartica**")
            hc6.markdown("**Skupaj**")

            for o in skupina:
                if o["rezim"] == "oba":
                    vrsta = "Gotovina + Kartica"
                elif o["rezim"] == "samo_kartica":
                    vrsta = "Samo kartica"
                else:
                    vrsta = "Samo gotovina"

                c1, c2, c3, c4, c5, c6 = st.columns([0.5, 1.5, 1.5, 1, 1, 1])
                checked = c1.checkbox("", value=sel_all_j,
                                      key=f"jcb_{o['journal_id']}",
                                      label_visibility="collapsed")
                c2.write(o["datum"])
                c3.write(vrsta)
                c4.write(f"{o['znesek_gotovina']:.2f} €" if o["znesek_gotovina"] else "—")
                c5.write(f"{o['znesek_kartica']:.2f} €" if o["znesek_kartica"] else "—")
                c6.write(f"**{o['skupaj']:.2f} €**")
                if checked:
                    izbrani.append(o)

                # Navodila za blagajno
                with st.expander("📋 Navodila za vnos v blagajno"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Blagajniški PREJEMEK:**")
                        st.markdown(f"- Stranka: `Končni kupec - maloprodaja`")
                        st.markdown(f"- Analitika: `{o['analitika_polno']}`")
                        st.markdown(f"- Tip: `Dnevni iztržek`")
                        st.markdown(f"- Znesek: **{o['skupaj']:.2f} €**")
                    with col2:
                        st.markdown("**Blagajniški IZDATEK:**")
                        st.markdown(f"- Analitika: `{o['analitika_polno']}`")
                        if o["rezim"] in ("oba", "samo_gotovina"):
                            st.markdown(f"- Polog gotovine - domača DE: **{o['znesek_gotovina']:.2f} €**")
                        if o["rezim"] in ("oba", "samo_kartica"):
                            st.markdown(f"- Terjatev za plačila z kartico: **{o['znesek_kartica']:.2f} €**")

            st.divider()

        # Povzetek izbora
        if izbrani:
            skupaj_vsota = sum(o["skupaj"] for o in izbrani)
            m1, m2, m3 = st.columns(3)
            m1.metric("Izbranih", len(izbrani))
            m2.metric("Blagajn", len(set(o["analitika_sifra"] for o in izbrani)))
            m3.metric("Skupaj", f"{skupaj_vsota:.2f} €")

        run_j_btn = st.button(
            f"▶️ Popravi in potrdi {len(izbrani)} temeljnic",
            type="primary", use_container_width=True,
            key="run_journals", disabled=len(izbrani) == 0,
        )

        if run_j_btn and izbrani:
            if not _check_config(): st.stop()
            with st.spinner("Popravljam temeljnice ..."):
                cli     = _make_client()
                uspesno = []
                napake  = []
                for o in izbrani:
                    try:
                        cli.popravi_in_potrdi_journal(o)
                        uspesno.append(o)
                    except Exception as e:
                        napake.append({"blagajna": o["blagajna_naziv"], "datum": o["datum"], "napaka": str(e)})

                if uspesno:
                    st.success(f"✅ {len(uspesno)} temeljnic uspešno popravljenih in potrjenih!")
                    st.dataframe(pd.DataFrame([{
                        "Datum":    o["datum"],
                        "Blagajna": o["blagajna_naziv"],
                        "Skupaj":   f"{o['skupaj']:.2f} €",
                    } for o in uspesno]), use_container_width=True, hide_index=True)

                if napake:
                    st.error(f"❌ {len(napake)} napak:")
                    for n in napake:
                        st.error(f"{n['datum']} | {n['blagajna']}: {n['napaka']}")

                st.session_state.pop("journal_osnutki", None)
                if not napake:
                    st.rerun()

# ── Noga ──────────────────────────────────────────────────────────────────────
st.divider()
st.caption("Agent Hub v2.0 · Minimax API · Loti + Temeljnice")
