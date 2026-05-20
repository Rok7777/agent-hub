"""
Tab: Loti — dodelitev serij
Ureja: chat "Zapiranje LOT"
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import traceback

from minimax_client import (
    MinimaxClient, LOCATIONS,
    parse_stock_to_engine_format, parse_entry_to_lines,
)
from lot_engine import assign_lots_with_virtual, check_old_lots
from config import get_client, get_wh_id, get_an_id, check_config, resolve_ids


def _scan_pl(cli, wh_id, date_from, date_to=None):
    """
    Skenira P/L dokumente in vrne (pl_received, batch_to_article, lot_price, item_info).
    date_to: ce podan, zaustavi skeniranje ko dokumenti presezejo ta datum.
    """
    from collections import defaultdict
    pl_received      = defaultdict(lambda: defaultdict(float))
    batch_to_article = {}
    lot_price        = defaultdict(lambda: defaultdict(float))
    item_info        = {}

    page = 1
    while True:
        try:
            data = cli._get("/stockentry", params={
                "StockEntryType": "P", "StockEntrySubtype": "L",
                "Status": "P", "DateFrom": date_from,
                "CurrentPage": page, "PageSize": 50,
            })
            rows = data.get("Rows", [])
            if not rows:
                break
            for entry in rows:
                eid = entry.get("StockEntryId")
                if not eid:
                    continue
                # Preskoči dokumente ki so novejši od date_to (za historical scan)
                if date_to:
                    entry_date = str(entry.get("Date", "") or "")[:10]
                    if entry_date and entry_date >= date_to:
                        continue
                try:
                    detail = cli.get_entry_detail(eid)
                    for row in (detail.get("StockEntryRows") or []):
                        wh_to   = (row.get("WarehouseTo") or {}).get("ID")
                        if str(wh_to) != str(wh_id):
                            continue
                        item_id = (row.get("Item") or {}).get("ID")
                        batch   = row.get("BatchNumber", "") or ""
                        qty     = float(row.get("Quantity") or 0)
                        price   = float(row.get("Price") or 0)
                        if not item_id or not batch or qty <= 0:
                            continue
                        pl_received[item_id][batch] += qty
                        batch_to_article[batch] = item_id
                        if price > 0:
                            lot_price[item_id][batch] = price
                        if item_id not in item_info:
                            item_info[item_id] = {
                                "ItemName":          row.get("ItemName") or (row.get("Item") or {}).get("Name", ""),
                                "ItemCode":          row.get("ItemCode", "") or "",
                                "UnitOfMeasurement": row.get("UnitOfMeasurement", "kg") or "kg",
                            }
                except Exception:
                    continue
            total   = data.get("TotalRows", 0)
            fetched = (page - 1) * 50 + len(rows)
            if fetched >= total:
                break
            page += 1
        except Exception:
            break

    return {
        "pl_received":      {k: dict(v) for k, v in pl_received.items()},
        "batch_to_article": batch_to_article,
        "lot_price":        {k: dict(v) for k, v in lot_price.items()},
        "item_info":        item_info,
    }


@st.cache_data(ttl=86400, show_spinner=False)  # 24h — stari P/L se ne spremenijo
def _get_pl_historical_cached(username, org_id, wh_id):
    """P/L dokumenti 61-365 dni nazaj. Cachet 24h ker se ne spremenijo."""
    from minimax_client import MinimaxClient
    from config import _secret
    from datetime import datetime, timedelta
    cli = MinimaxClient(
        username=username, password=_secret("MINIMAX_PASSWORD", ""),
        client_id=_secret("MINIMAX_CLIENT_ID", ""),
        client_secret=_secret("MINIMAX_CLIENT_SECRET", ""),
        org_id=int(org_id),
    )
    now       = datetime.now()
    date_from = (now - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00")
    date_to   = (now - timedelta(days=60)).strftime("%Y-%m-%d")
    return _scan_pl(cli, wh_id, date_from, date_to)


@st.cache_data(ttl=900, show_spinner=False)  # 15 min cache
def _get_stock_cached(username, org_id, wh_id):
    """
    Scaling faktor pristop:
    1. P/L historical (61-365 dni, 24h cache) + P/L recent (0-60 dni, 15 min)
    2. IS (60 dni) z batch->artikel popravkom
    3. /stocks per artikel = ground truth za skupno zalogo
    4. Scale lot kolicine da skupaj = /stocks total
    """
    from minimax_client import MinimaxClient
    from config import _secret
    from datetime import datetime, timedelta
    from collections import defaultdict

    cli = MinimaxClient(
        username=username, password=_secret("MINIMAX_PASSWORD", ""),
        client_id=_secret("MINIMAX_CLIENT_ID", ""),
        client_secret=_secret("MINIMAX_CLIENT_SECRET", ""),
        org_id=int(org_id),
    )

    # ── P/L: historical (24h cache) + recent (svez) ───────────────────────────
    hist = _get_pl_historical_cached(username, org_id, wh_id)

    date_from_recent = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00")
    recent = _scan_pl(cli, wh_id, date_from_recent)

    # Merge historical + recent
    pl_received      = defaultdict(lambda: defaultdict(float))
    batch_to_article = {}
    lot_price        = defaultdict(lambda: defaultdict(float))
    item_info        = {}

    for src_data in [hist, recent]:
        for item_id, batches in src_data["pl_received"].items():
            for batch, qty in batches.items():
                pl_received[item_id][batch] += qty
        batch_to_article.update(src_data["batch_to_article"])
        for item_id, batches in src_data["lot_price"].items():
            for batch, price in batches.items():
                if price > 0:
                    lot_price[item_id][batch] = price
        for item_id, info in src_data["item_info"].items():
            if item_id not in item_info:
                item_info[item_id] = info

    # ── IS (60 dni) z batch->artikel popravkom ────────────────────────────────
    is_consumed  = defaultdict(lambda: defaultdict(float))
    date_from_is = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00")
    page = 1
    while True:
        try:
            data = cli._get("/stockentry", params={
                "StockEntryType": "I", "StockEntrySubtype": "S",
                "Status": "P", "DateFrom": date_from_is,
                "CurrentPage": page, "PageSize": 50,
            })
            rows = data.get("Rows", [])
            if not rows:
                break
            for entry in rows:
                eid = entry.get("StockEntryId")
                if not eid:
                    continue
                try:
                    detail = cli.get_entry_detail(eid)
                    for row in (detail.get("StockEntryRows") or []):
                        wh_from = (row.get("WarehouseFrom") or {}).get("ID")
                        if str(wh_from) != str(wh_id):
                            continue
                        item_id_is = (row.get("Item") or {}).get("ID")
                        batch      = row.get("BatchNumber", "") or ""
                        qty        = float(row.get("Quantity") or 0)
                        if not batch or qty <= 0:
                            continue
                        orig = batch_to_article.get(batch, item_id_is)
                        is_consumed[orig][batch] += qty
                except Exception:
                    continue
            total   = data.get("TotalRows", 0)
            fetched = (page - 1) * 50 + len(rows)
            if fetched >= total:
                break
            page += 1
        except Exception:
            break

    # ── /stocks: skupna realna zaloga per artikel ─────────────────────────────
    stocks_raw   = cli.get_stock_by_lots(wh_id)
    stocks_total = {}
    for row in stocks_raw:
        item_id = (row.get("Item") or {}).get("ID")
        qty     = float(row.get("Quantity") or 0)
        if item_id and qty > 0:
            stocks_total[item_id] = stocks_total.get(item_id, 0) + qty
        if item_id and item_id not in item_info:
            item_info[item_id] = {
                "ItemName":          row.get("ItemName", "") or "",
                "ItemCode":          row.get("ItemCode", "") or "",
                "UnitOfMeasurement": row.get("UnitOfMeasurement", "kg") or "kg",
            }

    # ── Scaling + sestavi rezultat ─────────────────────────────────────────────
    result = []
    for item_id in pl_received:
        lot_remaining = {}
        for batch, recv in pl_received[item_id].items():
            consumed  = is_consumed[item_id].get(batch, 0)
            remaining = round(recv - consumed, 3)
            if remaining > 0.001:
                lot_remaining[batch] = {"remaining": remaining, "received": recv}

        if not lot_remaining:
            continue

        true_total = stocks_total.get(item_id, 0)
        if true_total <= 0:
            continue

        pl_is_total = sum(v["remaining"] for v in lot_remaining.values())
        scale       = (true_total / pl_is_total) if pl_is_total > 0 else 1.0

        info = item_info.get(item_id, {})
        for batch, data in lot_remaining.items():
            scaled = round(data["remaining"] * scale, 3)
            scaled = min(scaled, round(data["received"], 3))
            if scaled <= 0.001:
                continue
            result.append({
                "Item":              {"ID": item_id},
                "ItemName":          info.get("ItemName", ""),
                "ItemCode":          info.get("ItemCode", "") or "",
                "BatchNumber":       batch,
                "Quantity":          scaled,
                "UnitOfMeasurement": info.get("UnitOfMeasurement", "kg"),
                "Price":             lot_price.get(item_id, {}).get(batch, 0),
            })
    return result


def _fallback_pl_is(cli, wh_id):
    return []



def _fallback_pl_is(cli, wh_id):
    """Ni vec potreben."""
    return []



def _fallback_pl_is(cli, wh_id):
    """Ni vec potreben - FIFO rebalancing pokriva vse primere."""
    return []



def _fallback_pl_is(cli, wh_id):
    """Fallback: P/L-IS z batch->artikel popravkom (ce /stocks ne vraca lotov)."""
    from datetime import datetime, timedelta
    from collections import defaultdict

    lot_qty          = defaultdict(lambda: defaultdict(float))
    lot_price        = defaultdict(lambda: defaultdict(float))
    batch_to_article = {}
    item_info        = {}

    date_from_pl = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00")
    page = 1
    while True:
        try:
            data = cli._get("/stockentry", params={
                "StockEntryType": "P", "StockEntrySubtype": "L",
                "Status": "P", "DateFrom": date_from_pl,
                "CurrentPage": page, "PageSize": 50,
            })
            rows = data.get("Rows", [])
            if not rows:
                break
            for entry in rows:
                eid = entry.get("StockEntryId")
                if not eid:
                    continue
                try:
                    detail = cli.get_entry_detail(eid)
                    for row in (detail.get("StockEntryRows") or []):
                        wh_to   = (row.get("WarehouseTo") or {}).get("ID")
                        if str(wh_to) != str(wh_id):
                            continue
                        item_id = (row.get("Item") or {}).get("ID")
                        batch   = row.get("BatchNumber", "") or ""
                        qty     = float(row.get("Quantity") or 0)
                        price   = float(row.get("Price") or 0)
                        if not item_id or not batch or qty <= 0:
                            continue
                        lot_qty[item_id][batch] += qty
                        batch_to_article[batch] = item_id
                        if price > 0:
                            lot_price[item_id][batch] = price
                        if item_id not in item_info:
                            item_info[item_id] = {
                                "ItemName":          row.get("ItemName") or (row.get("Item") or {}).get("Name", ""),
                                "ItemCode":          row.get("ItemCode", "") or "",
                                "UnitOfMeasurement": row.get("UnitOfMeasurement", "kg") or "kg",
                            }
                except Exception:
                    continue
            total   = data.get("TotalRows", 0)
            fetched = (page - 1) * 50 + len(rows)
            if fetched >= total:
                break
            page += 1
        except Exception:
            break

    date_from_is = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00")
    page = 1
    while True:
        try:
            data = cli._get("/stockentry", params={
                "StockEntryType": "I", "StockEntrySubtype": "S",
                "Status": "P", "DateFrom": date_from_is,
                "CurrentPage": page, "PageSize": 50,
            })
            rows = data.get("Rows", [])
            if not rows:
                break
            for entry in rows:
                eid = entry.get("StockEntryId")
                if not eid:
                    continue
                try:
                    detail = cli.get_entry_detail(eid)
                    for row in (detail.get("StockEntryRows") or []):
                        wh_from = (row.get("WarehouseFrom") or {}).get("ID")
                        if str(wh_from) != str(wh_id):
                            continue
                        item_id_on_is = (row.get("Item") or {}).get("ID")
                        batch         = row.get("BatchNumber", "") or ""
                        qty           = float(row.get("Quantity") or 0)
                        if not batch or qty <= 0:
                            continue
                        original = batch_to_article.get(batch, item_id_on_is)
                        lot_qty[original][batch] -= qty
                except Exception:
                    continue
            total   = data.get("TotalRows", 0)
            fetched = (page - 1) * 50 + len(rows)
            if fetched >= total:
                break
            page += 1
        except Exception:
            break

    result = []
    for item_id, batches in lot_qty.items():
        info = item_info.get(item_id, {})
        for batch, qty in batches.items():
            if qty > 0.001:
                result.append({
                    "Item":              {"ID": item_id},
                    "ItemName":          info.get("ItemName", ""),
                    "ItemCode":          info.get("ItemCode", "") or "",
                    "BatchNumber":       batch,
                    "Quantity":          round(qty, 3),
                    "UnitOfMeasurement": info.get("UnitOfMeasurement", "kg"),
                    "Price":             lot_price.get(item_id, {}).get(batch, 0),
                })
    return result



def render():
    st.caption("Avtomatska FIFO dodelitev serij za maloprodajne dokumente v Minimaxu")

    # ── Stranska vrstica ──────────────────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Nastavitve API")

        def _secret(key, default=""):
            try:
                return st.secrets[key]
            except Exception:
                return default

        with st.expander("Minimax dostop", expanded=True):
            st.caption("Podatki odjemalca (iz emaila Minimax podpore):")
            st.session_state["client_id"]     = st.text_input("Client ID",        value=_secret("MINIMAX_CLIENT_ID", "OltreCon"))
            st.session_state["client_secret"] = st.text_input("Client Secret",    value=_secret("MINIMAX_CLIENT_SECRET", ""), type="password")
            st.caption("Podatki uporabnika:")
            st.session_state["username"]      = st.text_input("Uporabniško ime",  value=_secret("MINIMAX_USERNAME", "Agent-hub"))
            st.session_state["password"]      = st.text_input("Geslo aplikacije", value=_secret("MINIMAX_PASSWORD", ""), type="password")
            st.caption("Organizacija:")
            st.session_state["org_id"]        = st.text_input("ID organizacije",  value=_secret("MINIMAX_ORG_ID", "171038"))

        st.divider()

        with st.expander("Kode skladišč", expanded=True):
            st.session_state["wh_mpk1"] = st.text_input("MPK1 — Potujоča 1",  value=_secret("WH_MPK1", "MP-K1"))
            st.session_state["wh_mpk2"] = st.text_input("MPK2 — Potujоča 2",  value=_secret("WH_MPK2", "MP-K2"))
            st.session_state["wh_mpk3"] = st.text_input("MPK3 — Potujоča 3",  value=_secret("WH_MPK3", "MP-K3"))
            st.session_state["wh_mpoc"] = st.text_input("MPOC — Ribarnica Domžale", value=_secret("WH_MPOC", "MP-RD"))

        st.divider()

        with st.expander("Kode analitik", expanded=True):
            st.session_state["an_mpk1"] = st.text_input("Analytic koda MPK1", value=_secret("AN_MPK1", "MPK1"))
            st.session_state["an_mpk2"] = st.text_input("Analytic koda MPK2", value=_secret("AN_MPK2", "MPK2"))
            st.session_state["an_mpk3"] = st.text_input("Analytic koda MPK3", value=_secret("AN_MPK3", "MPK3"))
            st.session_state["an_mpoc"] = st.text_input("Analytic koda MPOC", value=_secret("AN_MPOC", "MPOC"))

        st.divider()
        if st.button("🔍 Poišči ID-je analitik avtomatsko"):
            st.session_state["auto_find_analytics"] = True
        if st.button("🔍 Poišči ID-je skladišč avtomatsko"):
            st.session_state["auto_find_warehouses"] = True
        if st.button("🔧 Diagnostika lotov (MPK2)"):
            st.session_state["diagnose_lots"] = True
        debug_loc = st.selectbox("Debug zaloge za:", ["MPK1","MPK2","MPK3","MPOC"], index=1, key="debug_loc_sel")
        if st.button("🔍 Debug zaloge"):
            st.session_state["debug_stock"] = True
        if st.button("🗑️ Počisti cache zaloge"):
            for k in list(st.session_state.keys()):
                if k.startswith("stock_cache_") or k == "item_units_cache":
                    del st.session_state[k]
            try:
                _get_stock_cached.clear()
                _get_pl_historical_cached.clear()
            except Exception:
                pass
            st.sidebar.success("Cache počiščen!")

    # ── Sidebar akcije ────────────────────────────────────────────────────────────────────────────
    if st.session_state.get("auto_find_analytics") and check_config():
        st.session_state.pop("auto_find_analytics")
        with st.spinner("Iščem analitike ..."):
            try:
                rows = get_client().get_analytics()
                st.sidebar.success("✅ Analitike najdene!")
                st.sidebar.dataframe(pd.DataFrame([{
                    "Koda": r.get("Code",""), "Naziv": r.get("Name",""), "Analytic ID": r.get("AnalyticId","")
                } for r in rows]), use_container_width=True)
                st.sidebar.caption("Prekopirajte ID-je v polja zgoraj.")
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")

    if st.session_state.get("diagnose_lots") and check_config():
        st.session_state.pop("diagnose_lots")
        with st.spinner("Diagnostika ..."):
            try:
                diag = get_client().diagnose_lots(get_wh_id("MPK2"))
                st.sidebar.success(f"✅ WH ID: {diag['warehouse_id']}")
                if diag['found']:
                    for f in diag['found']:
                        st.sidebar.write(f"Tip {f['type']}: lot={f['batch']}, wh_from={f['wh_from']}, wh_to={f['wh_to']}")
                else:
                    st.sidebar.warning("Ni dokumentov z loti v zadnjih 14 dneh!")
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")

    if st.session_state.get("debug_stock") and check_config():
        st.session_state.pop("debug_stock")
        _dloc = st.session_state.get("debug_loc_sel", "MPK2")
        with st.spinner(f"Berem zalogo {_dloc} ..."):
            try:
                cli   = get_client()
                wh    = get_wh_id(_dloc)
                raw   = cli.get_stock_by_lots(wh)
                has_lots = any(r.get("BatchNumber") for r in raw)
                st.sidebar.write(f"Lokacija: {_dloc} | WH ID: `{wh}`")
                st.sidebar.write(f"/stocks vraca: {len(raw)} vrstic, loti (BatchNumber): {has_lots}")
                if has_lots:
                    sample = [r for r in raw if r.get("BatchNumber")][:8]
                    for s in sample:
                        st.sidebar.write(f"  {s.get('ItemName','')[:30]} | {s.get('BatchNumber')} | {s.get('Quantity')} {s.get('UnitOfMeasurement','')} | NC={s.get('Price',0)}")
                    st.sidebar.info("✅ /stocks vraca lote — ground truth deluje!")
                else:
                    st.sidebar.warning("⚠️ /stocks ne vraca BatchNumber — bo aktiviran fallback P/L-IS")
                if not has_lots:
                    items = cli.get_stock_for_items(wh, [])
                    st.sidebar.write(f"get_stock_for_items: {len(items)} vrstic")
                    sample = items[:5]
                    for s in sample:
                        st.sidebar.write(f"  {s.get('ItemName','')} | lot={s.get('BatchNumber')} | qty={s.get('Quantity')}")
                    if not items:
                        try:
                            from datetime import timedelta
                            date_from = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00")
                            data = cli._get("/stockentry", params={"StockEntryType":"P","StockEntrySubtype":"L","Status":"P","DateFrom":date_from,"CurrentPage":1,"PageSize":5})
                            docs = data.get("Rows",[])
                            st.sidebar.write(f"P/L dokumenti (60 dni): {data.get('TotalRows',0)}")
                            if docs:
                                d0 = cli.get_entry_detail(docs[0].get("StockEntryId"))
                                r0 = (d0.get("StockEntryRows") or [{}])[0]
                                st.sidebar.write(f"Prva vrstica: wh_from={((r0.get('WarehouseFrom') or {}).get('ID'))}, wh_to={((r0.get('WarehouseTo') or {}).get('ID'))}")
                        except Exception as ex:
                            st.sidebar.error(f"P/L debug napaka: {ex}")
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")

    if st.session_state.get("auto_find_warehouses") and check_config():
        st.session_state.pop("auto_find_warehouses")
        with st.spinner("Iščem skladišča ..."):
            try:
                rows = get_client().get_warehouses()
                st.sidebar.success("✅ Skladišča najdena!")
                st.sidebar.dataframe(pd.DataFrame([{
                    "Naziv": r.get("Name",""), "Koda": r.get("Code",""), "Warehouse ID": r.get("WarehouseId") or r.get("ID","")
                } for r in rows]), use_container_width=True)
                st.sidebar.caption("Poiščite MPK1/MPK2/MPK3/MPOC in prekopirajte ID-je v polja zgoraj.")
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")

    # ── Tabs za lokacije ────────────────────────────────────────────────────────────────────────
    tabs     = st.tabs(["🚐 MPK1 — Potujоča 1", "🚐 MPK2 — Potujоča 2", "🚐 MPK3 — Potujоča 3", "🏪 MPOC — Ribarnica Domžale"])
    LOC_KEYS = ["MPK1", "MPK2", "MPK3", "MPOC"]

    for tab, loc_key in zip(tabs, LOC_KEYS):
        with tab:
            loc_name = LOCATIONS[loc_key]["name"]
            wh_id    = get_wh_id(loc_key)
            an_id    = get_an_id(loc_key)

            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.subheader(loc_name)
            with col2:
                find_btn = st.button("🔍 Poišči osnutke", key=f"find_{loc_key}", use_container_width=True)
            with col3:
                if st.button("🗑️ Počisti cache", key=f"clear_{loc_key}", use_container_width=True):
                    try:
                        _get_stock_cached.clear()
                        _get_pl_historical_cached.clear()
                    except Exception:
                        pass
                    for k in list(st.session_state.keys()):
                        if k.startswith("stock_cache_") or k == "item_units_cache":
                            del st.session_state[k]
                    st.session_state.pop(f"multi_result_{loc_key}", None)
                    st.success("Cache počiščen!")

            if find_btn:
                if not check_config(): st.stop()
                if an_id == 0:
                    with st.spinner("Iščem analitike..."):
                        try:
                            resolve_ids.clear()
                            an_id = get_an_id(loc_key)
                        except Exception: pass
                if an_id == 0:
                    st.error("Ne najdem analitike. Preverite kodo v nastavitvah.")
                    st.stop()
                with st.spinner("Iščem osnutke dokumentov ..."):
                    try:
                        drafts = get_client().get_draft_entries(an_id)
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
            st.caption("Izberite dokumente za obdelavo (kronološki vrstni red):")
            select_all = st.checkbox("☑ Izberi vse", key=f"sel_all_{loc_key}", value=True)

            selected_ids = []
            for d in sorted(drafts, key=lambda x: str(x.get("Date",""))):
                label  = f"IS-{d.get('Number','?')}"+" — "+str(d.get('Date',''))[:10]
                cb_key = f"cb_{loc_key}_{d.get('StockEntryId')}"
                if st.checkbox(label, key=cb_key, value=select_all):
                    selected_ids.append(d.get("StockEntryId"))

            st.divider()
            run_btn = st.button(
                f"⚡ Obdelaj vse označene osnutke ({len(selected_ids)})",
                key=f"run_{loc_key}", type="primary",
                use_container_width=True, disabled=len(selected_ids) == 0,
            )

            if run_btn and selected_ids:
                if wh_id == 0:
                    st.error("Vnesite Warehouse kodo za to lokacijo v nastavitvah.")
                    st.stop()
                with st.spinner(f"Berem zalogo in obdelujem {len(selected_ids)} dokumentov ... ⏳"):
                    try:
                        # Cache client v session (izognemo se novemu token requestu)
                        if "cached_client" not in st.session_state:
                            st.session_state["cached_client"] = get_client()
                        cli = st.session_state["cached_client"]
                        sorted_ids = sorted(
                            selected_ids,
                            key=lambda eid: str(next((d.get("Date","") for d in drafts if d.get("StockEntryId") == eid), ""))
                        )

                        all_entry_data, all_doc_lines, all_item_ids = {}, {}, set()
                        for eid in sorted_ids:
                            ed = cli.get_entry_detail(eid)
                            dl = parse_entry_to_lines(ed)
                            all_entry_data[eid] = ed
                            all_doc_lines[eid]  = dl
                            for l in dl:
                                if l.get("article_id"): all_item_ids.add(l["article_id"])

                        # Cache item_units v session da ne kličemo API vsakič
                        if "item_units_cache" not in st.session_state:
                            st.session_state["item_units_cache"] = {}
                        missing = [i for i in all_item_ids if i not in st.session_state["item_units_cache"]]
                        if missing:
                            new_units = cli.get_item_units(missing)
                            st.session_state["item_units_cache"].update(new_units)
                        item_units = st.session_state["item_units_cache"]
                        for eid in sorted_ids:
                            all_doc_lines[eid] = parse_entry_to_lines(all_entry_data[eid], item_units)

                        # Razreši numerični warehouse ID (koda "MP-K2" → numerični 27421)
                        # Cachirana zaloga (15 min) — get_stock_for_items se kliče samo enkrat
                        username = st.session_state.get("username", "")
                        org_id   = st.session_state.get("org_id", "171038")
                        stock_raw = _get_stock_cached(username, org_id, wh_id)
                        stock = parse_stock_to_engine_format(stock_raw)

                        shared_virtual = {key: [lot.copy() for lot in data["lots"]] for key, data in stock.items()}
                        all_results    = {}

                        # Za vsak artikel shrani datum ZADNJEGA dokumenta kjer se pojavi
                        # article_dates: {article_id: datetime}
                        article_dates   = {}
                        doc_article_ids = set()

                        for eid in sorted_ids:
                            d_info = next((d for d in drafts if d.get("StockEntryId") == eid), {})
                            doc_date_str = str(d_info.get("Date", ""))[:10]
                            try:
                                doc_date = datetime.strptime(doc_date_str, "%Y-%m-%d")
                            except Exception:
                                doc_date = datetime.now()

                            all_results[eid] = assign_lots_with_virtual(
                                all_doc_lines[eid], stock, shared_virtual, doc_date
                            )

                            for l in all_doc_lines[eid]:
                                aid = l.get("article_id")
                                if aid:
                                    doc_article_ids.add(aid)
                                    # Posodobi na najnovejši datum za ta artikel
                                    if aid not in article_dates or doc_date > article_dates[aid]:
                                        article_dates[aid] = doc_date

                        old_lot_warnings = check_old_lots(
                            stock, datetime.now(),
                            article_ids=doc_article_ids,
                            article_dates=article_dates,
                        )

                        st.session_state[f"multi_result_{loc_key}"] = {
                            "sorted_ids": sorted_ids, "all_results": all_results,
                            "all_entry_data": all_entry_data,
                            "old_lot_warnings": old_lot_warnings, "drafts": drafts,
                        }
                    except Exception as e:
                        st.error(f"Napaka pri obdelavi: {e}")
                        st.error(traceback.format_exc())

            multi_res = st.session_state.get(f"multi_result_{loc_key}")
            if multi_res:
                st.divider()
                sorted_ids     = multi_res["sorted_ids"]
                all_results    = multi_res["all_results"]
                all_entry_data = multi_res["all_entry_data"]
                drafts_map     = {d.get("StockEntryId"): d for d in multi_res["drafts"]}

                def row_color(s):
                    return {"ok":"🟢","matched":"🟡","partial":"🟠","no_match":"🔴","no_lots":"🔴","writeoff":"📤"}.get(s,"⚪")

                total_ok      = sum(len([l for l in r if l["status"]=="ok"])                    for r in all_results.values())
                total_matched = sum(len([l for l in r if l["status"]=="matched"])                for r in all_results.values())
                total_partial = sum(len([l for l in r if l["status"]=="partial"])                for r in all_results.values())
                total_none    = sum(len([l for l in r if l["status"] in ("no_match","no_lots")]) for r in all_results.values())

                c1,c2,c3,c4 = st.columns(4)
                c1.metric("✅ Točno ujemanje",    total_ok)
                c2.metric("🔄 Pametna zamenjava", total_matched)
                c3.metric("⚠️ Delno pokrito",     total_partial)
                c4.metric("❌ Brez lota",          total_none)

                # Pripravi Excel za vse dodeljene lote
                all_lots_rows = []
                for eid in sorted_ids:
                    lines = all_results[eid]
                    d     = drafts_map.get(eid, {})
                    doc_num  = f"IS-{d.get('Number','?')}"
                    doc_date = str(d.get('Date',''))[:10]
                    for l in lines:
                        all_lots_rows.append({
                            "Analitika":  loc_key,
                            "Dokument":   doc_num,
                            "Datum":      doc_date,
                            "Artikel":    l["article_name"],
                            "Kol.":       l["quantity_assigned"],
                            "ME":         l.get("unit",""),
                            "Lot":        l.get("lot") or "—",
                            "Status":     l["status"],
                            "Opis":       l.get("opis") or "",
                        })

                if all_lots_rows:
                    import io
                    buf_lots = io.BytesIO()
                    pd.DataFrame(all_lots_rows).to_excel(buf_lots, index=False, engine="openpyxl")
                    st.download_button(
                        label="⬇️ Prenesi seznam lotov (Excel)",
                        data=buf_lots.getvalue(),
                        file_name=f"loti_{loc_key}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_lots_{loc_key}",
                    )

                for eid in sorted_ids:
                    lines = all_results[eid]
                    d     = drafts_map.get(eid, {})
                    label = f"IS-{d.get('Number','?')}"+" — "+str(d.get('Date',''))[:10]
                    no_lot_count = len([l for l in lines if l["status"] in ("no_match","no_lots","partial")])
                    icon = "✅" if no_lot_count == 0 else "⚠️"
                    with st.expander(f"{icon} {label}  ({len(lines)} vrstic)", expanded=(no_lot_count > 0)):
                        df_r = pd.DataFrame([{
                            "": row_color(l["status"]), "Artikel": l["article_name"],
                            "Kol.": l["quantity_assigned"], "ME": l["unit"],
                            "Lot": l.get("lot") or "—", "Opis": l.get("opis") or "",
                        } for l in lines])
                        st.dataframe(df_r, use_container_width=True, hide_index=True)

                # Poročilo napak
                error_rows = []
                for eid in sorted_ids:
                    lines_e  = all_results[eid]
                    d_e      = drafts_map.get(eid, {})
                    doc_num  = f"IS-{d_e.get('Number','?')}"
                    doc_date = str(d_e.get('Date',''))[:10]
                    for i, l in enumerate(lines_e, 1):
                        if l["status"] in ("no_match", "no_lots", "partial"):
                            status_opis = {
                                "no_match": "Ni zaloge za artikel",
                                "no_lots":  "Ni ustreznih lotov",
                                "partial":  "Premalo zaloge",
                            }.get(l["status"], l["status"])
                            detail = l.get("opis", "") or ""
                            if "[" in detail:
                                detail = detail[detail.find("[")+1:detail.rfind("]")]
                            error_rows.append({
                                "Analitika": loc_key, "Dokument": doc_num, "Datum": doc_date,
                                "Vrstica": i, "Artikel": l["article_name"],
                                "Kol.": l["quantity_assigned"], "ME": l.get("unit",""),
                                "Napaka": status_opis, "Podrobnost": detail,
                            })

                if error_rows:
                    with st.expander(f"📋 Poročilo napak ({len(error_rows)} vrstic)", expanded=True):
                        df_err = pd.DataFrame(error_rows)
                        st.dataframe(df_err, use_container_width=True, hide_index=True)
                        import io
                        buf = io.BytesIO()
                        df_err.to_excel(buf, index=False, engine="openpyxl")
                        st.download_button(
                            label="⬇️ Prenesi poročilo (Excel)",
                            data=buf.getvalue(),
                            file_name=f"napake_{loc_key}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )

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
                        st.caption("Starost lota je računana na datum zadnjega dokumenta kjer se artikel pojavi.")

                if total_partial + total_none > 0:
                    st.warning(f"⚠️ {total_partial + total_none} vrstic(a) brez lota. Preverite ročno pred potrditvijo.")

                st.divider()
                col_save, col_cancel = st.columns(2)
                with col_save:
                    save_all_btn = st.button(
                        f"💾 Shrani vse v Minimax ({len(sorted_ids)} dokumentov)",
                        key=f"save_all_{loc_key}", type="primary", use_container_width=True,
                    )
                with col_cancel:
                    cancel_btn = st.button("✖ Zavrzi rezultate", key=f"cancel_multi_{loc_key}", use_container_width=True)

                if cancel_btn:
                    del st.session_state[f"multi_result_{loc_key}"]
                    st.rerun()

                if save_all_btn:
                    with st.spinner(f"Shranjujem {len(sorted_ids)} dokumentov v Minimax ..."):
                        errors, saved = [], 0
                        try:
                            cli = get_client()
                            for eid in sorted_ids:
                                doc_label = f"IS-{drafts_map.get(eid,{}).get('Number','?')}"
                                try:
                                    rows = all_results[eid]
                                    st.write(f"Shranjujem {doc_label} ({len(rows)} vrstic)...")
                                    cli.update_entry_with_lots(
                                        entry_id=eid, entry_data=all_entry_data[eid],
                                        new_rows=rows,
                                    )
                                    saved += 1
                                    st.write(f"✅ {doc_label} shranjen")
                                except Exception as e:
                                    import traceback
                                    errors.append(f"{doc_label}: {e}")
                                    st.error(f"Napaka {doc_label}: {e}")
                                    st.code(traceback.format_exc())
                        except Exception as e:
                            import traceback
                            st.error(f"Napaka pri povezavi: {e}")
                            st.code(traceback.format_exc())
                        if saved > 0:
                            st.success(f"✅ {saved}/{len(sorted_ids)} dokumentov shranjenih v Minimax!")
                        for err in errors:
                            st.error(err)
                        # Rerun samo če ni napak
                        if saved > 0 and not errors:
                            del st.session_state[f"multi_result_{loc_key}"]
                            st.session_state.pop(f"drafts_{loc_key}", None)
                            st.rerun()
                        elif errors:
                            st.warning("⚠️ Napake pri shranjevanju — rezultati ostanejo prikazani.")
