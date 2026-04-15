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
from lot_engine import assign_lots

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

        # Prikaz seznama osnutkov
        df_drafts = pd.DataFrame([{
            "Številka":  f"IS-{d.get('Number','?')}",
            "Datum":     str(d.get('Date',''))[:10],
            "Stranka":   d.get('Customer', {}).get('Name', 'Končni kupec'),
            "ID":        d.get('StockEntryId'),
        } for d in drafts])

        st.dataframe(df_drafts.drop(columns=["ID"]), use_container_width=True, hide_index=True)

        # Izbira dokumenta
        doc_options = {
            f"IS-{d.get('Number','?')} ({str(d.get('Date',''))[:10]})": d.get('StockEntryId')
            for d in drafts
        }
        selected_label = st.selectbox(
            "Izberite dokument za obdelavo:",
            options=list(doc_options.keys()),
            key=f"sel_{loc_key}",
        )
        selected_id = doc_options[selected_label]

        run_btn = st.button(
            f"⚡ Zaženi agenta za {selected_label}",
            key=f"run_{loc_key}",
            type="primary",
            use_container_width=True,
        )

        if run_btn:
            if wh_id == 0:
                st.error("Vnesite Warehouse ID za to lokacijo v nastavitvah.")
                st.stop()

            with st.spinner("Berem dokument in zalogo ... ⏳"):
                try:
                    cli          = _make_client()
                    entry_data   = cli.get_entry_detail(selected_id)
                    stock_raw    = cli.get_stock_by_lots(wh_id)
                    doc_lines    = parse_entry_to_lines(entry_data)

                    # Če splošni klic ni vrnil lotov, poiščemo po posameznih artiklih
                    has_lots = any(r.get("BatchNumber") for r in stock_raw)
                    if not has_lots and doc_lines:
                        item_ids = list({l["article_id"] for l in doc_lines if l.get("article_id")})
                        stock_raw = cli.get_stock_for_items(wh_id, item_ids)

                    stock        = parse_stock_to_engine_format(stock_raw)
                    today        = datetime.now()
                    result_lines = assign_lots(doc_lines, stock, today)
                    
                    # Debug info
                    entry_keys = list(entry_data.keys()) if isinstance(entry_data, dict) else str(type(entry_data))
                    rows = entry_data.get("StockEntryRows") or []
                    first_row = str(rows[0]) if rows else "Ni vrstic v StockEntryRows"
                    lots_sample = [r for r in stock_raw if r.get("BatchNumber")][:3]
                    st.session_state[f"debug_{loc_key}_{selected_id}"] = {
                        "entry_keys": entry_keys,
                        "doc_lines_count": len(doc_lines),
                        "stock_count": len(stock),
                        "rows_count": len(rows),
                        "first_row": first_row,
                        "has_lots": has_lots,
                        "lots_sample": str(lots_sample),
                        "raw_sample": str(entry_data)[:300],
                    }

                    st.session_state[f"result_{loc_key}_{selected_id}"] = {
                        "lines":      result_lines,
                        "entry_data": entry_data,
                        "entry_id":   selected_id,
                        "label":      selected_label,
                    }
                except Exception as e:
                    st.error(f"Napaka pri obdelavi: {e}")
                    st.error(traceback.format_exc())

        # Prikaz rezultatov
        res_key = f"result_{loc_key}_{selected_id}"
        result  = st.session_state.get(res_key)

        if result:
            st.divider()
            lines = result["lines"]
            label = result["label"]

            # Debug prikaz
            debug_key = f"debug_{loc_key}_{selected_id}"
            if debug_key in st.session_state:
                dbg = st.session_state[debug_key]
                with st.expander("🔧 Debug info (za razvijalca)"):
                    st.write(f"Ključi dokumenta: {dbg['entry_keys']}")
                    st.write(f"Vrstic v dokumentu: {dbg['doc_lines_count']}")
                    st.write(f"Vrstic (StockEntryRows): {dbg.get('rows_count', '?')}")
                    st.write(f"Artiklov v zalogi: {dbg['stock_count']}")
                    st.write(f"Loti najdeni: {dbg.get('has_lots', '?')}")
                    st.write("Vzorec lotov:")
                    st.code(dbg.get('lots_sample', ''))
                    st.write("Prva vrstica:")
                    st.code(dbg.get('first_row', ''))

            # Statistika
            ok_lines      = [l for l in lines if l['status'] == 'ok']
            matched_lines = [l for l in lines if l['status'] == 'matched']
            partial_lines = [l for l in lines if l['status'] == 'partial']
            no_match      = [l for l in lines if l['status'] in ('no_match','no_lots')]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("✅ Točno ujemanje",    len(ok_lines))
            c2.metric("🔄 Pametna zamenjava", len(matched_lines))
            c3.metric("⚠️ Delno pokrito",     len(partial_lines))
            c4.metric("❌ Brez lota",          len(no_match))

            # Barvna tabela rezultatov
            def row_color(status):
                return {"ok": "🟢", "matched": "🟡", "partial": "🟠", "no_match": "🔴", "no_lots": "🔴"}.get(status, "⚪")

            df_res = pd.DataFrame([{
                "":         row_color(l['status']),
                "Artikel":  l['article_name'],
                "Kol.":     l['quantity_assigned'],
                "ME":       l['unit'],
                "Lot":      l.get('lot') or "—",
                "Opis":     l.get('opis') or "",
            } for l in lines])

            st.dataframe(df_res, use_container_width=True, hide_index=True)

            if no_match or partial_lines:
                st.warning(
                    f"⚠️ {len(no_match)+len(partial_lines)} vrstic(a) ostane brez lota. "
                    "Preverite ročno pred potrditvijo v Minimaxu."
                )

            # Potrditev
            st.divider()
            col_conf, col_cancel = st.columns(2)

            with col_conf:
                confirm_btn = st.button(
                    f"💾 Shrani in pošlji v Minimax",
                    key=f"confirm_{loc_key}_{selected_id}",
                    type="primary",
                    use_container_width=True,
                )

            with col_cancel:
                cancel_btn = st.button(
                    "✖ Zavrzi rezultate",
                    key=f"cancel_{loc_key}_{selected_id}",
                    use_container_width=True,
                )

            if cancel_btn:
                del st.session_state[res_key]
                st.rerun()

            if confirm_btn:
                with st.spinner("Shranjujem v Minimax ..."):
                    try:
                        cli = _make_client()
                        cli.update_entry_with_lots(
                            entry_id   = result["entry_id"],
                            entry_data = result["entry_data"],
                            new_rows   = lines,
                        )
                        st.success(f"✅ Dokument {label} uspešno posodobljen v Minimaxu!")
                        del st.session_state[res_key]
                        # Posodobi seznam osnutkov
                        if f"drafts_{loc_key}" in st.session_state:
                            del st.session_state[f"drafts_{loc_key}"]
                        st.rerun()
                    except Exception as e:
                        st.error(f"Napaka pri shranjevanju: {e}")
                        st.error(traceback.format_exc())

# ── Noga ─────────────────────────────────────────────────────────────────────

st.divider()
st.caption("Agent Hub v1.0 · Minimax API · FIFO + smart matching za ribje artikle")
