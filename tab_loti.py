"""
Tab: Loti -- dodelitev serij
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
from lot_engine import assign_lots_with_virtual, check_old_lots, finalize_writeoffs
from config import get_client, get_wh_id, get_an_id, check_config, resolve_ids


@st.cache_data(ttl=900, show_spinner=False)  # 15 min cache
def _get_stock_cached(username, org_id, wh_id):
    """
    Direktni per-lot podatki iz Minimax zaloge.
    GET /stocks?WarehouseId=X&ResultsByBatchNumber=D
    Vrne tocne kolicine po lotih — april loti ki so porabljeni niso vrnjeni.
    Ni potrebe po P/L, IS, FIFO ali kakrsnem koli racunanju.
    """
    from minimax_client import MinimaxClient
    from config import _secret

    cli = MinimaxClient(
        username=username, password=_secret("MINIMAX_PASSWORD", ""),
        client_id=_secret("MINIMAX_CLIENT_ID", ""),
        client_secret=_secret("MINIMAX_CLIENT_SECRET", ""),
        org_id=int(org_id),
    )

    result = []
    page   = 1
    while True:
        data = cli._get("/stocks", params={
            "WarehouseId":          wh_id,
            "ResultsByBatchNumber": "D",
            "CurrentPage":          page,
            "PageSize":             200,
        })
        rows = data.get("Rows", [])
        for row in rows:
            item_id = (row.get("Item") or {}).get("ID")
            batch   = row.get("BatchNumber") or ""
            qty     = float(row.get("Quantity") or 0)
            if not item_id or not batch or qty < 0.05:  # pod 50g = ghost lot
                continue
            result.append({
                "Item":              {"ID": item_id},
                "ItemName":          row.get("ItemName", "") or "",
                "ItemCode":          row.get("ItemCode", "") or "",
                "BatchNumber":       batch,
                "Quantity":          qty,
                "UnitOfMeasurement": row.get("UnitOfMeasurement", "kg") or "kg",
                "Price":             float(row.get("AveragePurchasePrice") or 0),
            })
        total   = data.get("TotalRows", 0)
        fetched = (page - 1) * 200 + len(rows)
        if fetched >= total:
            break
        page += 1
    return result



def render():
    st.caption("Avtomatska FIFO dodelitev serij za maloprodajne dokumente v Minimaxu")

    # Stranska vrstica
    with st.sidebar:
        st.header("\u2699\ufe0f Nastavitve API")

        def _secret(key, default=""):
            try:
                return st.secrets[key]
            except Exception:
                pass
            import os
            return os.environ.get(key, default)

        with st.expander("Minimax dostop", expanded=True):
            st.caption("Podatki odjemalca (iz emaila Minimax podpore):")
            st.session_state["client_id"]     = st.text_input("Client ID",        value=_secret("MINIMAX_CLIENT_ID", "OltreCon"))
            st.session_state["client_secret"] = st.text_input("Client Secret",    value=_secret("MINIMAX_CLIENT_SECRET", ""), type="password")
            st.caption("Podatki uporabnika:")
            st.session_state["username"]      = st.text_input("Uporabni\u0161ko ime",  value=_secret("MINIMAX_USERNAME", "Agent-hub"))
            st.session_state["password"]      = st.text_input("Geslo aplikacije", value=_secret("MINIMAX_PASSWORD", ""), type="password")
            st.caption("Organizacija:")
            st.session_state["org_id"]        = st.text_input("ID organizacije",  value=_secret("MINIMAX_ORG_ID", "171038"))

        st.divider()

        with st.expander("Kode skladi\u0161\u010d", expanded=True):
            st.session_state["wh_mpk1"] = st.text_input("MPK1 \u2014 Potujо\u010da 1",  value=_secret("WH_MPK1", "MP-K1"))
            st.session_state["wh_mpk2"] = st.text_input("MPK2 \u2014 Potujо\u010da 2",  value=_secret("WH_MPK2", "MP-K2"))
            st.session_state["wh_mpk3"] = st.text_input("MPK3 \u2014 Potujо\u010da 3",  value=_secret("WH_MPK3", "MP-K3"))
            st.session_state["wh_mpoc"] = st.text_input("MPOC \u2014 Ribarnica Dom\u017eale", value=_secret("WH_MPOC", "MP-RD"))

        st.divider()

        with st.expander("Kode analitik", expanded=True):
            st.session_state["an_mpk1"] = st.text_input("Analytic koda MPK1", value=_secret("AN_MPK1", "MPK1"))
            st.session_state["an_mpk2"] = st.text_input("Analytic koda MPK2", value=_secret("AN_MPK2", "MPK2"))
            st.session_state["an_mpk3"] = st.text_input("Analytic koda MPK3", value=_secret("AN_MPK3", "MPK3"))
            st.session_state["an_mpoc"] = st.text_input("Analytic koda MPOC", value=_secret("AN_MPOC", "MPOC"))

        st.divider()
        if st.button("\U0001f50d Poi\u0161\u010di ID-je analitik avtomatsko"):
            st.session_state["auto_find_analytics"] = True
        if st.button("\U0001f50d Poi\u0161\u010di ID-je skladi\u0161\u010d avtomatsko"):
            st.session_state["auto_find_warehouses"] = True
        if st.button("\U0001f527 Diagnostika lotov (MPK2)"):
            st.session_state["diagnose_lots"] = True
        debug_loc = st.selectbox("Debug zaloge za:", ["MPK1","MPK2","MPK3","MPOC"], index=1, key="debug_loc_sel")
        if st.button("\U0001f50d Debug zaloge"):
            st.session_state["debug_stock"] = True
        if st.button("\U0001f5d1\ufe0f Po\u010disti cache zaloge"):
            for k in list(st.session_state.keys()):
                if k.startswith("stock_cache_") or k == "item_units_cache":
                    del st.session_state[k]
            try:
                _get_stock_cached.clear()
                _get_pl_historical_cached.clear()
            except Exception:
                pass
            st.sidebar.success("Cache po\u010di\u0161\u010den!")

    # Sidebar akcije
    if st.session_state.get("auto_find_analytics") and check_config():
        st.session_state.pop("auto_find_analytics")
        with st.spinner("I\u0161\u010dem analitike ..."):
            try:
                rows = get_client().get_analytics()
                st.sidebar.success("\u2705 Analitike najdene!")
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
                st.sidebar.success(f"\u2705 WH ID: {diag['warehouse_id']}")
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
                cli      = get_client()
                wh       = get_wh_id(_dloc)
                raw      = cli.get_stock_by_lots(wh)
                st.sidebar.write(f"Lokacija: {_dloc} | WH ID: `{wh}`")
                st.sidebar.write(f"/stocks: {len(raw)} artiklov")
                if raw:
                    # Testiraj vec artiklov - najprej tisti ki bi morali imeti lote
                    test_candidates = [r for r in raw if any(
                        kw in (r.get("ItemName","") or "").upper()
                        for kw in ["LOSOS","SARD","BRANC","ORADA","POSTRV","LIGNJI"]
                    )] or raw
                    test_row = test_candidates[0] if test_candidates else None
                    if test_row:
                        fid   = (test_row.get("Item") or {}).get("ID")
                        fname = test_row.get("ItemName", "")

                        def _check(label, data):
                            if isinstance(data, list):
                                rows = data
                            elif isinstance(data, dict):
                                rows = data.get("Rows") or data.get("rows") or []
                                if not rows:
                                    rows = [data]
                            else:
                                rows = []
                            has_b = any(r.get("BatchNumber") or r.get("Serija") for r in rows)
                            st.sidebar.write(f"{label}: {len(rows)} vrstic, loti: {has_b}")
                            if rows:
                                st.sidebar.json(rows[0])
                            return has_b

                        # TEST: /stocks?WarehouseId=X&ResultsByBatchNumber=D
                        try:
                            r1 = cli._get("/stocks", params={
                                "WarehouseId": wh,
                                "ResultsByBatchNumber": "D",
                                "CurrentPage": 1,
                                "PageSize": 20,
                            })
                            rows = r1.get("Rows", []) if isinstance(r1, dict) else []
                            has_b = any(r.get("BatchNumber") for r in rows)
                            st.sidebar.write(f"/stocks?RBN=D: {r1.get('TotalRows',0)} skupaj, {len(rows)} vrstic, loti: {has_b}")
                            if rows:
                                st.sidebar.json(rows[0])
                            if has_b:
                                st.sidebar.success("✅ ResultsByBatchNumber=D DELA!")
                        except Exception as e:
                            st.sidebar.error(f"Test RBN=D: {e}")
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")

    if st.session_state.get("auto_find_warehouses") and check_config():
        st.session_state.pop("auto_find_warehouses")
        with st.spinner("I\u0161\u010dem skladi\u0161\u010da ..."):
            try:
                rows = get_client().get_warehouses()
                st.sidebar.success("\u2705 Skladi\u0161\u010da najdena!")
                st.sidebar.dataframe(pd.DataFrame([{
                    "Naziv": r.get("Name",""), "Koda": r.get("Code",""), "Warehouse ID": r.get("WarehouseId") or r.get("ID","")
                } for r in rows]), use_container_width=True)
                st.sidebar.caption("Poi\u0161\u010dite MPK1/MPK2/MPK3/MPOC in prekopirajte ID-je v polja zgoraj.")
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")

    # Tabs za lokacije
    tabs     = st.tabs(["\U0001f690 MPK1 \u2014 Potujо\u010da 1", "\U0001f690 MPK2 \u2014 Potujо\u010da 2", "\U0001f690 MPK3 \u2014 Potujо\u010da 3", "\U0001f3ea MPOC \u2014 Ribarnica Dom\u017eale"])
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
                # Počisti cache — rdeča, mora biti kliknjena pred iskanjem
                cache_key = f"cache_cleared_{loc_key}"
                if st.button("🗑️ Počisti cache", key=f"clear_{loc_key}",
                             use_container_width=True, type="primary"):
                    try:
                        _get_stock_cached.clear()
                        _get_pl_historical_cached.clear()
                    except Exception:
                        pass
                    for k in list(st.session_state.keys()):
                        if k.startswith("stock_cache_") or k == "item_units_cache":
                            del st.session_state[k]
                    st.session_state.pop(f"multi_result_{loc_key}", None)
                    st.session_state[cache_key] = True
                    st.success("Cache počiščen!")
            with col3:
                cache_ok = st.session_state.get(cache_key, False)
                find_btn = st.button(
                    "🔍 Poišči osnutke",
                    key=f"find_{loc_key}",
                    use_container_width=True,
                    disabled=not cache_ok,
                    help="" if cache_ok else "Najprej klikni 'Počisti cache'",
                )

            if find_btn:
                st.session_state[cache_key] = False  # reset — naslednjič spet počisti
                if not check_config(): st.stop()
                if an_id == 0:
                    with st.spinner("I\u0161\u010dem analitike..."):
                        try:
                            resolve_ids.clear()
                            an_id = get_an_id(loc_key)
                        except Exception: pass
                if an_id == 0:
                    st.error("Ne najdem analitike. Preverite kodo v nastavitvah.")
                    st.stop()
                with st.spinner("I\u0161\u010dem osnutke dokumentov ..."):
                    try:
                        drafts = get_client().get_draft_entries(an_id)
                        st.session_state[f"drafts_{loc_key}"] = drafts
                    except Exception as e:
                        st.error(f"Napaka pri branju osnutkov: {e}")
                        st.session_state[f"drafts_{loc_key}"] = []

            drafts = st.session_state.get(f"drafts_{loc_key}", None)
            if drafts is None:
                st.info("Kliknite 'Poi\u0161\u010di osnutke' za prikaz \u010dakajo\u010dih dokumentov.")
                continue
            if not drafts:
                st.success("\u2705 Ni \u010dakajo\u010dih osnutkov za to lokacijo.")
                continue

            st.write(f"Najdenih **{len(drafts)}** osnutkov:")
            st.caption("Izberite dokumente za obdelavo (kronolo\u0161ki vrstni red):")
            select_all = st.checkbox("\u2611 Izberi vse", key=f"sel_all_{loc_key}", value=True)

            selected_ids = []
            for d in sorted(drafts, key=lambda x: str(x.get("Date",""))):
                label  = f"IS-{d.get('Number','?')} \u2014 {str(d.get('Date',''))[:10]}"
                cb_key = f"cb_{loc_key}_{d.get('StockEntryId')}"
                if st.checkbox(label, key=cb_key, value=select_all):
                    selected_ids.append(d.get("StockEntryId"))

            st.divider()
            run_btn = st.button(
                f"\u26a1 Obdelaj vse ozna\u010dene osnutke ({len(selected_ids)})",
                key=f"run_{loc_key}", type="primary",
                use_container_width=True, disabled=len(selected_ids) == 0,
            )

            if run_btn and selected_ids:
                if wh_id == 0:
                    st.error("Vnesite Warehouse kodo za to lokacijo v nastavitvah.")
                    st.stop()
                with st.spinner(f"Berem zalogo in obdelujem {len(selected_ids)} dokumentov ... \u23f3"):
                    try:
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

                        if "item_units_cache" not in st.session_state:
                            st.session_state["item_units_cache"] = {}
                        missing = [i for i in all_item_ids if i not in st.session_state["item_units_cache"]]
                        if missing:
                            new_units = cli.get_item_units(missing)
                            st.session_state["item_units_cache"].update(new_units)
                        item_units = st.session_state["item_units_cache"]
                        for eid in sorted_ids:
                            all_doc_lines[eid] = parse_entry_to_lines(all_entry_data[eid], item_units)

                        username  = st.session_state.get("username", "")
                        org_id    = st.session_state.get("org_id", "171038")
                        stock_raw = _get_stock_cached(username, org_id, wh_id)
                        stock     = parse_stock_to_engine_format(stock_raw)

                        shared_virtual = {key: [lot.copy() for lot in data["lots"]] for key, data in stock.items()}
                        all_results    = {}
                        article_dates  = {}
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
                                    if aid not in article_dates or doc_date > article_dates[aid]:
                                        article_dates[aid] = doc_date

                        # Finalizacija odpisov — po zadnjem dokumentu
                        last_eid  = sorted_ids[-1]
                        last_info = next((d for d in drafts if d.get("StockEntryId") == last_eid), {})
                        last_date_str = str(last_info.get("Date", ""))[:10]
                        try:
                            last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
                        except Exception:
                            last_date = datetime.now()

                        wo_lines = finalize_writeoffs(shared_virtual, stock, last_date)
                        if wo_lines:
                            all_results[last_eid] = all_results[last_eid] + wo_lines

                        old_lot_warnings = check_old_lots(
                            stock, datetime.now(),
                            article_ids=doc_article_ids,
                            article_dates=article_dates,
                        )

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

            multi_res = st.session_state.get(f"multi_result_{loc_key}")
            if multi_res:
                st.divider()
                sorted_ids     = multi_res["sorted_ids"]
                all_results    = multi_res["all_results"]
                all_entry_data = multi_res["all_entry_data"]
                drafts_map     = {d.get("StockEntryId"): d for d in multi_res["drafts"]}

                def row_color(s):
                    return {"ok":"\U0001f7e2","matched":"\U0001f7e1","partial":"\U0001f7e0",
                            "no_match":"\U0001f534","no_lots":"\U0001f534","writeoff":"\U0001f4e4"}.get(s,"\u26aa")

                total_ok      = sum(len([l for l in r if l["status"]=="ok"])                    for r in all_results.values())
                total_matched = sum(len([l for l in r if l["status"]=="matched"])                for r in all_results.values())
                total_partial = sum(len([l for l in r if l["status"]=="partial"])                for r in all_results.values())
                total_none    = sum(len([l for l in r if l["status"] in ("no_match","no_lots")]) for r in all_results.values())

                c1,c2,c3,c4 = st.columns(4)
                c1.metric("\u2705 To\u010dno ujemanje",    total_ok)
                c2.metric("\U0001f504 Pametna zamenjava", total_matched)
                c3.metric("\u26a0\ufe0f Delno pokrito",   total_partial)
                c4.metric("\u274c Brez lota",             total_none)

                all_lots_rows = []
                for eid in sorted_ids:
                    lines    = all_results[eid]
                    d        = drafts_map.get(eid, {})
                    doc_num  = f"IS-{d.get('Number','?')}"
                    doc_date = str(d.get('Date',''))[:10]
                    for l in lines:
                        all_lots_rows.append({
                            "Analitika": loc_key, "Dokument": doc_num, "Datum": doc_date,
                            "Artikel":   l["article_name"], "Kol.": l["quantity_assigned"],
                            "ME":        l.get("unit",""), "Lot": l.get("lot") or "\u2014",
                            "Status":    l["status"], "Opis": l.get("opis") or "",
                        })

                if all_lots_rows:
                    import io
                    buf_lots = io.BytesIO()
                    pd.DataFrame(all_lots_rows).to_excel(buf_lots, index=False, engine="openpyxl")
                    st.download_button(
                        label="\u2b07\ufe0f Prenesi seznam lotov (Excel)",
                        data=buf_lots.getvalue(),
                        file_name=f"loti_{loc_key}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_lots_{loc_key}",
                    )

                for eid in sorted_ids:
                    lines = all_results[eid]
                    d     = drafts_map.get(eid, {})
                    label = f"IS-{d.get('Number','?')} \u2014 {str(d.get('Date',''))[:10]}"
                    no_lot_count = len([l for l in lines if l["status"] in ("no_match","no_lots","partial")])
                    icon = "\u2705" if no_lot_count == 0 else "\u26a0\ufe0f"
                    with st.expander(f"{icon} {label}  ({len(lines)} vrstic)", expanded=(no_lot_count > 0)):
                        def _fmt_opis(l):
                            o = l.get("opis") or ""
                            if l["status"] == "writeoff":
                                return ("odpis star lot  " + o).strip()
                            return o
                        df_r = pd.DataFrame([{
                            "": row_color(l["status"]), "Artikel": l["article_name"],
                            "Kol.": l["quantity_assigned"], "ME": l["unit"],
                            "Lot": l.get("lot") or "\u2014", "Opis": _fmt_opis(l),
                        } for l in lines])
                        st.dataframe(df_r, use_container_width=True, hide_index=True)

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
                    with st.expander(f"\U0001f4cb Poro\u010dilo napak ({len(error_rows)} vrstic)", expanded=True):
                        df_err = pd.DataFrame(error_rows)
                        st.dataframe(df_err, use_container_width=True, hide_index=True)
                        import io
                        buf = io.BytesIO()
                        df_err.to_excel(buf, index=False, engine="openpyxl")
                        st.download_button(
                            label="\u2b07\ufe0f Prenesi poro\u010dilo (Excel)",
                            data=buf.getvalue(),
                            file_name=f"napake_{loc_key}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )

                old_lots = multi_res.get("old_lot_warnings", [])
                if old_lots:
                    with st.expander(f"\u23f0 Stari loti na zalogi ({len(old_lots)} opozoril)"):
                        df_old = pd.DataFrame([{
                            "Artikel":   w["article"], "Lot": w["lot"],
                            "Dni star":  w["days_old"],
                            "Qty":       f"{w['qty']} {w['unit']}",
                            "Opozorilo": w["warning"],
                        } for w in old_lots])
                        st.dataframe(df_old, use_container_width=True, hide_index=True)
                        st.caption("Starost lota je ra\u010dunana na datum zadnjega dokumenta kjer se artikel pojavi.")

                if total_partial + total_none > 0:
                    st.warning(f"\u26a0\ufe0f {total_partial + total_none} vrstic(a) brez lota. Preverite ro\u010dno pred potrditvijo.")

                st.divider()
                col_save, col_cancel = st.columns(2)
                with col_save:
                    save_all_btn = st.button(
                        f"\U0001f4be Shrani vse v Minimax ({len(sorted_ids)} dokumentov)",
                        key=f"save_all_{loc_key}", type="primary", use_container_width=True,
                    )
                with col_cancel:
                    cancel_btn = st.button("\u2716 Zavrzi rezultate", key=f"cancel_multi_{loc_key}", use_container_width=True)

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
                                    st.write(f"\u2705 {doc_label} shranjen")
                                except Exception as e:
                                    errors.append(f"{doc_label}: {e}")
                                    st.error(f"Napaka {doc_label}: {e}")
                                    st.code(traceback.format_exc())
                        except Exception as e:
                            st.error(f"Napaka pri povezavi: {e}")
                            st.code(traceback.format_exc())
                        if saved > 0:
                            st.success(f"\u2705 {saved}/{len(sorted_ids)} dokumentov shranjenih v Minimax!")
                        for err in errors:
                            st.error(err)
                        if saved > 0 and not errors:
                            del st.session_state[f"multi_result_{loc_key}"]
                            st.session_state.pop(f"drafts_{loc_key}", None)
                            st.rerun()
                        elif errors:
                            st.warning("\u26a0\ufe0f Napake pri shranjevanju \u2014 rezultati ostanejo prikazani.")
