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


@st.cache_data(ttl=900, show_spinner=False)  # 15 min cache
def _get_stock_cached(username, org_id, wh_id):
    """Cachirana zaloga po lotih — velja 15 minut."""
    from minimax_client import MinimaxClient
    from config import _secret
    cli = MinimaxClient(
        username      = username,
        password      = _secret("MINIMAX_PASSWORD", ""),
        client_id     = _secret("MINIMAX_CLIENT_ID", ""),
        client_secret = _secret("MINIMAX_CLIENT_SECRET", ""),
        org_id        = int(org_id),
    )
    stock_raw = cli.get_stock_by_lots(wh_id)
    if not any(r.get("BatchNumber") for r in stock_raw):
        stock_raw = cli.get_stock_for_items(wh_id, [])
    return stock_raw


def render():
    st.caption("Avtomatska FIFO dodelitev serij za maloprodajne dokumente v Minimaxu")

    # ── Stranska vrstica ──────────────────────────────────────────────────────
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
            st.session_state["wh_mpk1"] = st.text_input("MPK1 — Potujoča 1",  value=_secret("WH_MPK1", "MP-K1"))
            st.session_state["wh_mpk2"] = st.text_input("MPK2 — Potujoča 2",  value=_secret("WH_MPK2", "MP-K2"))
            st.session_state["wh_mpk3"] = st.text_input("MPK3 — Potujoča 3",  value=_secret("WH_MPK3", "MP-K3"))
            st.session_state["wh_mpoc"] = st.text_input("MPOC — Rib. Domžale", value=_secret("WH_MPOC", "MP-RD"))

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
        if st.button("🔍 Debug zaloge (MPK2)"):
            st.session_state["debug_stock"] = True
        if st.button("🗑️ Počisti cache zaloge"):
            for k in list(st.session_state.keys()):
                if k.startswith("stock_cache_") or k == "item_units_cache":
                    del st.session_state[k]
            st.sidebar.success("Cache počiščen!")

    # ── Sidebar akcije ────────────────────────────────────────────────────────
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
        with st.spinner("Berem zalogo ..."):
            try:
                cli   = get_client()
                wh    = get_wh_id("MPK2")
                raw   = cli.get_stock_by_lots(wh)
                has_lots = any(r.get("BatchNumber") for r in raw)
                st.sidebar.write(f"WH ID: `{wh}` (tip: {type(wh).__name__})")
                st.sidebar.write(f"get_stock_by_lots: {len(raw)} vrstic, loti: {has_lots}")
                if not has_lots:
                    items = cli.get_stock_for_items(wh, [])
                    st.sidebar.write(f"get_stock_for_items: {len(items)} vrstic")
                    sample = items[:5]
                    for s in sample:
                        st.sidebar.write(f"  {s.get('ItemName','')} | lot={s.get('BatchNumber')} | qty={s.get('Quantity')}")
                    if not items:
                        # Show raw P/L docs
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

    # ── Tabs za lokacije ──────────────────────────────────────────────────────
    tabs     = st.tabs(["🚐 MPK1 — Potujoča 1", "🚐 MPK2 — Potujoča 2", "🚐 MPK3 — Potujoča 3", "🏪 MPOC — Ribarnica Domžale"])
    LOC_KEYS = ["MPK1", "MPK2", "MPK3", "MPOC"]

    for tab, loc_key in zip(tabs, LOC_KEYS):
        with tab:
            loc_name = LOCATIONS[loc_key]["name"]
            wh_id    = get_wh_id(loc_key)
            an_id    = get_an_id(loc_key)

            col1, col2 = st.columns([2, 1])
            with col1:
                st.subheader(loc_name)
            with col2:
                find_btn = st.button("🔍 Poišči osnutke", key=f"find_{loc_key}", use_container_width=True)

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
                label  = f"IS-{d.get('Number','?')} — {str(d.get('Date',''))[:10]}"
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

                for eid in sorted_ids:
                    lines = all_results[eid]
                    d     = drafts_map.get(eid, {})
                    label = f"IS-{d.get('Number','?')} — {str(d.get('Date',''))[:10]}"
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
                                try:
                                    cli.update_entry_with_lots(
                                        entry_id=eid, entry_data=all_entry_data[eid],
                                        new_rows=all_results[eid],
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
                        st.session_state.pop(f"drafts_{loc_key}", None)
                        st.rerun()
