"""
Tab: Prejem blaga
Tok: Naloži dobavnice → AI prebere → osnutki v Streamlitu → pošlji v Minimax + tiskaj deklaracije
"""

import streamlit as st
import pandas as pd
import json
import base64
import re
import traceback
import uuid
from datetime import datetime

from minimax_client import MinimaxClient

# ─── Konstante ────────────────────────────────────────────────────────────────

SUPPLIER_PREFIXES = {
    "ALEMAR": "AL", "CERKVENIK": "CE", "KVIBO": "KV",
    "FIORITAL": "FI", "FORMIO": "FO", "LIBO": "LI",
    "COST IN": "CI", "ORADA ADRIATIC": "OA",
    "MARTINOVIC": "MF", "MARTINOVIĆ": "MF",
    "ROMICA": "RO", "RO-TRADE": "RT", "MADIA": "MA", "FRULPESCA": "FP",
}

VP_CEN_CODE  = "VP-CEN"
OLTREON_INFO = "OltreCon d.o.o., Orehovlje 2F, 5291 Miren"
VET_OZNAKA   = "SI 844 ES"  # fiksna veterinarska oznaka

# Status
STATUS_ICON  = {"ready": "🟢", "sent": "⚫", "error": "🔴"}
STATUS_LABEL = {"ready": "Pripravljen", "sent": "Poslan v Minimax", "error": "Pomanjkljiv"}

REQUIRED_HEADER = [
    ("supplier_name",  "❌", "Dobavitelj ni vpisan"),
    ("invoice_date",   "❌", "Datum dobavnice manjka"),
    ("invoice_number", "❌", "Številka dobavnice manjka"),
]
REQUIRED_ROW = [
    ("item_code",          "❌", "Šifra artikla manjka"),
    ("quantity",           "❌", "Količina mora biti > 0"),
    ("batch_number",       "❌", "Serija (lot) manjka"),
    ("price",              "⚠️", "Nabavna cena ni določena"),
    ("country_of_origin",  "⚠️", "Država porekla manjka"),
    ("tariff",             "⚠️", "Carinska tarifa manjka"),
]

# ─── Pomožne funkcije ─────────────────────────────────────────────────────────

def _secret(key, default=""):
    try:    return st.secrets[key]
    except: return default

def _lot_number(supplier_name: str, date_str: str) -> str:
    prefix = ""
    sup_up = supplier_name.upper()
    for key, val in SUPPLIER_PREFIXES.items():
        if key in sup_up:
            prefix = val
            break
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return f"{prefix}{d.strftime('%d%m%y')}"
    except:
        return f"{prefix}??????"

def _get_client() -> MinimaxClient:
    return MinimaxClient(
        username=_secret("MINIMAX_USERNAME", st.session_state.get("username", "")),
        password=_secret("MINIMAX_PASSWORD", st.session_state.get("password", "")),
        client_id=_secret("MINIMAX_CLIENT_ID", st.session_state.get("client_id", "")),
        client_secret=_secret("MINIMAX_CLIENT_SECRET", st.session_state.get("client_secret", "")),
        org_id=int(_secret("MINIMAX_ORG_ID", st.session_state.get("org_id", "171038"))),
    )

# ─── Claude Vision ────────────────────────────────────────────────────────────

_PARSE_PROMPT = """Analiziraj to dobavnico / račun dobavitelja za ribe in morske sadeže.
Vrni SAMO čist JSON brez markdown backticks, brez komentarjev.

{
  "supplier_name": "ime dobavitelja",
  "invoice_number": "številka računa ali dobavnice",
  "invoice_date": "YYYY-MM-DD",
  "lot_dobavitelja": "LOT številka dobavitelja če je navedena",
  "datum_izlova": "YYYY-MM-DD datum izlova/pridelave če je naveden",
  "kraj_proizvoda": "kraj pridelave/izlova če je naveden",
  "items": [
    {
      "name": "naziv artikla kot piše na dobavnici",
      "latin_name": "latinsko ime vrste če je navedeno",
      "quantity": 0.000,
      "unit": "kg",
      "price": 0.00,
      "country_of_origin": "2-črkovna ISO koda (HR, IT, NO, SI...)",
      "tariff": "carinska tarifa samo cifre brez presledkov",
      "fao_zone": "FAO cona če je navedena",
      "kategorija": "sveže ali zamrznjeno ali odtaljeno",
      "lot_dobavitelja": "LOT za ta artikel če je ločen od splošnega",
      "datum_izlova": "YYYY-MM-DD datum izlova za ta artikel če je ločen"
    }
  ]
}

Pravila: invoice_date/datum_izlova=YYYY-MM-DD, country_of_origin=2 črki, tariff=samo cifre."""

def _parse_claude(image_bytes: bytes, media_type: str = "image/jpeg"):
    try:
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {}, "ANTHROPIC_API_KEY ni v st.secrets"
        client = anthropic.Anthropic(api_key=api_key)
        b64    = base64.b64encode(image_bytes).decode()
        block  = ({"type":"document","source":{"type":"base64","media_type":media_type,"data":b64}}
                  if media_type=="application/pdf"
                  else {"type":"image","source":{"type":"base64","media_type":media_type,"data":b64}})
        resp = client.messages.create(
            model="claude-opus-4-5", max_tokens=2048,
            messages=[{"role":"user","content":[block,{"type":"text","text":_PARSE_PROMPT}]}],
        )
        raw = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return {}, f"JSON napaka: {e}"
    except Exception as e:
        return {}, str(e)

# ─── Deklaracije ──────────────────────────────────────────────────────────────

def _kategorija_temperatura(kategorija: str) -> str:
    k = kategorija.lower()
    if "zamrz" in k: return "DO -18°C"
    if "odtalj" in k: return "DO +4°C"
    return "DO +4°C"  # sveže

def _build_declarations(header: dict, rows: list) -> list:
    """
    Kreira deklaracije — ena na unikaten artikel.
    TODO: Dopolniti ko dobimo vzorec OltreCon deklaracije:
          - Polje IZDELEK
          - Izračun PORABITI DO
          - Ovalni žig (slika)
    """
    seen    = {}
    decls   = []
    lot_nas = header.get("lot_number", "")
    lot_dob = header.get("lot_dobavitelja", "")
    datum_izlova  = header.get("datum_izlova", "")
    kraj_proizvoda = header.get("kraj_proizvoda", "")

    for row in rows:
        key = row.get("item_code", "") or row.get("inv_name", "")
        if key in seen:
            continue
        seen[key] = True

        kategorija = row.get("kategorija", "sveže")
        decl = {
            "naziv_blaga":       f"{row.get('item_name') or row.get('inv_name','')} ({row.get('latin_name','')})",
            "izdelek":           "",  # TODO: dopolniti po vzorcu OltreCon
            "drzava_porekla":    row.get("country_of_origin", ""),
            "kraj_proizvoda":    kraj_proizvoda or row.get("kraj_proizvoda", ""),
            "dobavitelj":        OLTREON_INFO,
            "lot":               lot_nas,
            "lot_dobavitelja":   lot_dob or row.get("lot_dobavitelja", ""),
            "kategorija_svezosti": kategorija,
            "porabiti_do":       "",  # TODO: izračun po vzorcu
            "datum_izlova":      datum_izlova or row.get("datum_izlova", ""),
            "hraniti_temperatura": _kategorija_temperatura(kategorija),
            "veterinarska_oznaka": VET_OZNAKA,
            "item_code":         row.get("item_code", ""),
            "item_name":         row.get("item_name") or row.get("inv_name", ""),
        }
        decls.append(decl)
    return decls

def _generate_zpl(decl: dict) -> str:
    """
    Generira ZPL kodo za Zebra GK420t — nalepka 8x5 cm (609x406 dots pri 203dpi).
    TODO: Finalizirati ko dobimo:
          - Vzorec OltreCon deklaracije (polje IZDELEK, PORABITI DO)
          - Datoteko ovalnega žiga (slika za ^GF)
    """
    naziv    = (decl.get("naziv_blaga") or "")[:60]
    izdelek  = decl.get("izdelek") or "TODO"
    drzava   = decl.get("drzava_porekla", "")
    kraj     = decl.get("kraj_proizvoda", "")
    dob      = decl.get("dobavitelj", "")
    lot      = decl.get("lot", "")
    lot_d    = decl.get("lot_dobavitelja", "")
    kat      = decl.get("kategorija_svezosti", "")
    por      = decl.get("porabiti_do") or "TODO"
    izlov    = decl.get("datum_izlova", "")
    temp     = decl.get("hraniti_temperatura", "")
    vet      = decl.get("veterinarska_oznaka", VET_OZNAKA)

    return f"""^XA
^PW609
^LL406
^CI28
^FO15,15^A0N,20,20^FDNAZIV BLAGA: {naziv}^FS
^FO15,40^A0N,18,18^FDIZDLEK: {izdelek}^FS
^FO15,65^A0N,18,18^FDDRZAVA POREKLA: {drzava}^FS
^FO15,88^A0N,18,18^FDKRAJ PROIZVODA: {kraj}^FS
^FO15,111^A0N,18,18^FDDOBAVITELJ: {dob[:45]}^FS
^FO15,134^A0N,18,18^FDLOT: {lot}^FS
^FO15,157^A0N,18,18^FDLOT DOBAVITELJA: {lot_d}^FS
^FO15,180^A0N,18,18^FDKATEGORIJA SVEZOSTI: {kat}^FS
^FO15,203^A0N,18,18^FDPORABITI DO: {por}^FS
^FO15,226^A0N,18,18^FDDATUM IZLOVA: {izlov}^FS
^FO15,249^A0N,18,18^FDHRANITI PRI TEMPERATURI: {temp}^FS
^FO480,270^A0N,20,20^FD{vet}^FS
^XZ"""

# ─── Validacija ───────────────────────────────────────────────────────────────

def _validate(header: dict, rows: list) -> list:
    errors = []
    for field, typ, msg in REQUIRED_HEADER:
        if not header.get(field):
            errors.append((typ, f"Glava: {msg}"))
    if not rows:
        errors.append(("❌", "Ni artikov za vnos"))
    for i, row in enumerate(rows, 1):
        for field, typ, msg in REQUIRED_ROW:
            val = row.get(field)
            if field == "quantity":
                if not val or float(val) <= 0:
                    errors.append((typ, f"Vrstica {i} ({row.get('inv_name','?')}): {msg}"))
            elif not val:
                errors.append((typ, f"Vrstica {i} ({row.get('inv_name','?')}): {msg}"))
    return errors

def _has_critical(errors): return any(t == "❌" for t, _ in errors)

def _draft_status(draft: dict) -> str:
    if draft.get("parse_error"): return "error"
    if draft.get("sent_to_minimax"): return "sent"
    errors = _validate(draft.get("header", {}), draft.get("rows", []))
    return "error" if _has_critical(errors) else "ready"

# ─── Minimax prenos ───────────────────────────────────────────────────────────

def _get_item_id_by_code(cli, code):
    try:
        data = cli._get("/items", params={"Code": code, "CurrentPage": 1, "PageSize": 5})
        for r in data.get("Rows", []):
            if r.get("Code", "").upper() == code.upper():
                return r.get("ItemId") or 0
    except: pass
    return 0

def _get_wh_id(cli):
    try:
        for wh in cli.get_warehouses():
            if wh.get("Code", "") == VP_CEN_CODE:
                return wh.get("WarehouseId") or wh.get("ID") or 0
    except: pass
    return 0

def _get_supplier_id(cli, name):
    try:
        name_up = name.upper()
        page = 1
        while True:
            data = cli._get("/suppliers", params={"CurrentPage": page, "PageSize": 100})
            rows = data.get("Rows", [])
            for s in rows:
                sn = (s.get("Name") or s.get("CompanyName") or "").upper()
                if name_up in sn or sn in name_up:
                    return s.get("SupplierId") or s.get("ID") or 0
            if len(rows) < 100: break
            page += 1
    except: pass
    return 0

def _send_draft(draft: dict) -> tuple:
    try:
        cli    = _get_client()
        wh_id  = _get_wh_id(cli)
        if not wh_id: return None, "Skladišče VP-CEN ni najdeno"
        sup_id = _get_supplier_id(cli, draft["header"].get("supplier_name", ""))
        if not sup_id: return None, f"Dobavitelj ni najden v Minimaxu"

        stock_rows = []
        for row in draft["rows"]:
            item_id = _get_item_id_by_code(cli, row.get("item_code", ""))
            if not item_id: return None, f"Artikel '{row.get('item_code')}' ni najden"
            sr = {
                "Item":              {"ID": item_id},
                "Quantity":          float(row.get("quantity") or 0),
                "Price":             float(row.get("price") or 0),
                "BatchNumber":       row.get("batch_number", ""),
                "UnitOfMeasurement": row.get("unit", "kg"),
                "WarehouseTo":       {"ID": wh_id},
            }
            if row.get("selling_price") and float(row.get("selling_price")) > 0:
                sr["SellingPrice"] = float(row["selling_price"])
            stock_rows.append(sr)

        h = draft["header"]
        body = {
            "StockEntryType": "P", "StockEntrySubtype": "L", "Status": "O",
            "Date":        h["invoice_date"] + "T00:00:00",
            "Description": f"{h.get('invoice_number','')} — {h.get('supplier_name','')}",
            "Supplier":    {"ID": sup_id},
            "WarehouseTo": {"ID": wh_id},
            "StockEntryRows": stock_rows,
        }
        result   = cli._post("/stockentry", body)
        entry_id = result.get("StockEntryId") or result.get("ID") or "?"
        return entry_id, None
    except Exception as e:
        return None, str(e)

# ─── RENDER ───────────────────────────────────────────────────────────────────

def render():
    st.caption("Skeniranje dobavnic dobavitelja → P/L osnutek v VP-CEN + deklaracije")

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Nastavitve")
        with st.expander("Minimax dostop", expanded=False):
            st.session_state["client_id"]     = st.text_input("Client ID",        value=_secret("MINIMAX_CLIENT_ID",""))
            st.session_state["client_secret"] = st.text_input("Client Secret",    value=_secret("MINIMAX_CLIENT_SECRET",""), type="password")
            st.session_state["username"]      = st.text_input("Uporabniško ime",  value=_secret("MINIMAX_USERNAME",""))
            st.session_state["password"]      = st.text_input("Geslo aplikacije", value=_secret("MINIMAX_PASSWORD",""), type="password")
            st.session_state["org_id"]        = st.text_input("ID organizacije",  value=_secret("MINIMAX_ORG_ID","171038"))
        st.divider()
        st.caption(f"Osnutkov v pomnilniku: {len(st.session_state.get('prejem_drafts', {}))}")

    # Init
    if "prejem_drafts" not in st.session_state:
        st.session_state["prejem_drafts"] = {}
    if "prejem_file_store" not in st.session_state:
        st.session_state["prejem_file_store"] = {}

    drafts     = st.session_state["prejem_drafts"]
    file_store = st.session_state["prejem_file_store"]

    # ═══════════════════════════════════════════════════════════
    # UPLOAD + OBDELAVA (zgoraj, zložljivo)
    # ═══════════════════════════════════════════════════════════
    with st.expander("📤 Naloži in obdelaj dobavnice", expanded=not bool(drafts)):

        uploaded_files = st.file_uploader(
            "Izberite dobavnice (slike ali PDF)",
            type=["jpg","jpeg","png","pdf"],
            accept_multiple_files=True,
            key="prejem_uploader",
            label_visibility="collapsed",
        )
        if uploaded_files:
            for f in uploaded_files:
                if f.name not in file_store:
                    file_store[f.name] = {"bytes": f.read(), "type": f.type, "name": f.name}
            st.session_state["prejem_file_store"] = file_store

        if file_store:
            selected = []
            for fname in file_store:
                is_done = any(d.get("fname") == fname for d in drafts.values())
                lbl = f"{'✅' if is_done else '📄'} {fname}"
                if st.checkbox(lbl, value=not is_done, key=f"chk_{fname}"):
                    selected.append(fname)

            col1, col2 = st.columns([2,1])
            with col1:
                if st.button(f"🤖 Obdelaj z AI ({len(selected)})", type="primary",
                             use_container_width=True, disabled=not selected, key="btn_obdelaj"):
                    prog = st.progress(0)
                    for i, fname in enumerate(selected):
                        prog.progress((i+1)/len(selected), text=f"Berem {fname} …")
                        fdata = file_store[fname]
                        mmap  = {"image/jpeg":"image/jpeg","image/jpg":"image/jpeg",
                                 "image/png":"image/png","application/pdf":"application/pdf"}
                        mtype = mmap.get(fdata["type"], "image/jpeg")
                        parsed, err = _parse_claude(fdata["bytes"], mtype)

                        draft_id = str(uuid.uuid4())[:8]
                        if err or not parsed:
                            drafts[draft_id] = {
                                "id": draft_id, "fname": fname,
                                "parse_error": err or "AI ni vrnil podatkov",
                                "header": {}, "rows": [], "declarations": [],
                                "sent_to_minimax": False, "minimax_entry_id": None,
                            }
                            continue

                        lot = _lot_number(parsed.get("supplier_name",""), parsed.get("invoice_date",""))
                        rows_out = []
                        for item in parsed.get("items", []):
                            rows_out.append({
                                "inv_name":          item.get("name",""),
                                "item_code":         "",
                                "item_name":         "",
                                "latin_name":        item.get("latin_name",""),
                                "quantity":          float(item.get("quantity") or 0),
                                "unit":              item.get("unit","kg"),
                                "price":             float(item.get("price") or 0),
                                "selling_price":     0.0,
                                "batch_number":      lot,
                                "country_of_origin": item.get("country_of_origin",""),
                                "tariff":            item.get("tariff",""),
                                "fao_zone":          item.get("fao_zone",""),
                                "kategorija":        item.get("kategorija","sveže"),
                                "lot_dobavitelja":   item.get("lot_dobavitelja", parsed.get("lot_dobavitelja","")),
                                "datum_izlova":      item.get("datum_izlova", parsed.get("datum_izlova","")),
                                "kraj_proizvoda":    parsed.get("kraj_proizvoda",""),
                            })

                        header = {
                            "supplier_name":   parsed.get("supplier_name",""),
                            "invoice_number":  parsed.get("invoice_number",""),
                            "invoice_date":    parsed.get("invoice_date",""),
                            "lot_number":      lot,
                            "lot_dobavitelja": parsed.get("lot_dobavitelja",""),
                            "datum_izlova":    parsed.get("datum_izlova",""),
                            "kraj_proizvoda":  parsed.get("kraj_proizvoda",""),
                        }
                        decls = _build_declarations(header, rows_out)
                        drafts[draft_id] = {
                            "id": draft_id, "fname": fname,
                            "parse_error": None,
                            "header":       header,
                            "rows":         rows_out,
                            "declarations": decls,
                            "sent_to_minimax": False,
                            "minimax_entry_id": None,
                        }

                    prog.empty()
                    st.session_state["prejem_drafts"] = drafts
                    st.rerun()

            with col2:
                if st.button("↺ Počisti datoteke", use_container_width=True, key="btn_clr_files"):
                    st.session_state["prejem_file_store"] = {}
                    st.rerun()

    if not drafts:
        st.info("Naloži dobavnice zgoraj za začetek.")
        return

    # ═══════════════════════════════════════════════════════════
    # SEZNAM OSNUTKOV
    # ═══════════════════════════════════════════════════════════
    st.subheader("📋 Osnutki")

    # Legenda
    st.markdown(
        f"{STATUS_ICON['ready']} Pripravljen &nbsp;&nbsp;"
        f"{STATUS_ICON['error']} Pomanjkljiv &nbsp;&nbsp;"
        f"{STATUS_ICON['sent']} Poslan v Minimax",
        unsafe_allow_html=True
    )
    st.markdown("---")

    selected_ids = []

    for draft_id, draft in list(drafts.items()):
        status = _draft_status(draft)
        icon   = STATUS_ICON[status]
        h      = draft.get("header", {})
        fname  = draft.get("fname", "")

        # Checkbox za izbor
        col_chk, col_exp = st.columns([0.5, 9.5])
        with col_chk:
            if st.checkbox("", key=f"sel_{draft_id}", value=False):
                selected_ids.append(draft_id)
        with col_exp:
            label = (
                f"{icon} **{h.get('supplier_name') or fname}**  ·  "
                f"{h.get('invoice_date','?')}  ·  "
                f"#{h.get('invoice_number','?')}  ·  "
                f"{len(draft.get('rows',[]))} artikov  ·  "
                f"{len(draft.get('declarations',[]))} deklaracij"
            )
            if draft.get("sent_to_minimax"):
                label += f"  ·  ID: {draft.get('minimax_entry_id','')}"

            with st.expander(label, expanded=False):

                if draft.get("parse_error"):
                    st.error(f"Napaka branja: {draft['parse_error']}")
                    continue

                # ── Header korekcija ──────────────────────────────────────
                errors = _validate(h, draft["rows"])
                if errors:
                    for typ, msg in errors:
                        st.write(f"{typ} {msg}")
                    st.divider()

                c1,c2,c3 = st.columns(3)
                with c1:
                    h["supplier_name"]  = st.text_input("Dobavitelj", value=h.get("supplier_name",""), key=f"sup_{draft_id}")
                with c2:
                    new_date = st.text_input("Datum (YYYY-MM-DD)", value=h.get("invoice_date",""), key=f"dt_{draft_id}")
                    if new_date != h.get("invoice_date",""):
                        h["invoice_date"] = new_date
                        new_lot = _lot_number(h.get("supplier_name",""), new_date)
                        h["lot_number"] = new_lot
                        for row in draft["rows"]: row["batch_number"] = new_lot
                    else:
                        h["invoice_date"] = new_date
                with c3:
                    h["invoice_number"] = st.text_input("Št. dobavnice", value=h.get("invoice_number",""), key=f"num_{draft_id}")

                c4,c5 = st.columns(2)
                with c4:
                    h["lot_dobavitelja"] = st.text_input("LOT dobavitelja", value=h.get("lot_dobavitelja",""), key=f"lotd_{draft_id}")
                with c5:
                    h["datum_izlova"] = st.text_input("Datum izlova", value=h.get("datum_izlova",""), key=f"izlov_{draft_id}")

                st.info(f"🏷️ Naš LOT: **{h.get('lot_number','?')}**  ·  Skladišče: **VP-CEN**")

                # ── Tabs: Artikli | Deklaracije ───────────────────────────
                tab_art, tab_decl = st.tabs(["🐟 Artikli", "🏷️ Deklaracije"])

                with tab_art:
                    for idx, row in enumerate(draft["rows"]):
                        art_icon = "✅" if row.get("item_code") else "❌"
                        with st.expander(
                            f"{art_icon} {idx+1}. {row['inv_name']}"
                            + (f" — `{row['item_code']}`" if row.get("item_code") else " — šifra manjka"),
                            expanded=not row.get("item_code")
                        ):
                            if row.get("latin_name"):
                                st.caption(f"🔬 *{row['latin_name']}*")
                            cc1,cc2,cc3,cc4 = st.columns(4)
                            with cc1:
                                row["item_code"] = st.text_input("Minimax šifra ⚠️", value=row.get("item_code",""), key=f"code_{draft_id}_{idx}")
                                row["quantity"]  = st.number_input("Količina", value=float(row.get("quantity") or 0), min_value=0.0, step=0.001, format="%.3f", key=f"qty_{draft_id}_{idx}")
                            with cc2:
                                row["unit"]  = st.text_input("ME", value=row.get("unit","kg"), key=f"unit_{draft_id}_{idx}")
                                row["price"] = st.number_input("Nab. cena €", value=float(row.get("price") or 0), min_value=0.0, step=0.01, format="%.4f", key=f"price_{draft_id}_{idx}")
                            with cc3:
                                row["selling_price"]     = st.number_input("Prod. cena €", value=float(row.get("selling_price") or 0), min_value=0.0, step=0.01, format="%.4f", key=f"sell_{draft_id}_{idx}")
                                row["batch_number"]      = st.text_input("Serija / Lot", value=row.get("batch_number",""), key=f"batch_{draft_id}_{idx}")
                            with cc4:
                                row["country_of_origin"] = st.text_input("Država (2 črkoven)", value=row.get("country_of_origin",""), key=f"cntry_{draft_id}_{idx}")
                                row["tariff"]            = st.text_input("Carinska tarifa", value=row.get("tariff",""), key=f"tariff_{draft_id}_{idx}")

                    if draft["rows"]:
                        total = sum(float(r.get("quantity") or 0)*float(r.get("price") or 0) for r in draft["rows"])
                        st.metric("Skupna nabavna vrednost", f"{total:.2f} €")

                with tab_decl:
                    # Regeneriraj deklaracije ob vsaki spremembi
                    draft["declarations"] = _build_declarations(h, draft["rows"])
                    decls = draft["declarations"]

                    if not decls:
                        st.info("Deklaracije bodo generirane ko so artikli določeni.")
                    else:
                        for di, decl in enumerate(decls):
                            with st.expander(f"🏷️ {decl['item_name'] or decl['naziv_blaga']}", expanded=False):
                                dc1, dc2 = st.columns(2)
                                with dc1:
                                    decl["naziv_blaga"]       = st.text_input("Naziv blaga",       value=decl.get("naziv_blaga",""),       key=f"dg_naz_{draft_id}_{di}")
                                    decl["izdelek"]           = st.text_input("Izdelek ⏳ TODO",    value=decl.get("izdelek",""),           key=f"dg_izd_{draft_id}_{di}")
                                    decl["drzava_porekla"]    = st.text_input("Država porekla",     value=decl.get("drzava_porekla",""),    key=f"dg_drz_{draft_id}_{di}")
                                    decl["kraj_proizvoda"]    = st.text_input("Kraj proizvoda",     value=decl.get("kraj_proizvoda",""),    key=f"dg_kraj_{draft_id}_{di}")
                                    decl["dobavitelj"]        = st.text_input("Dobavitelj",         value=decl.get("dobavitelj",OLTREON_INFO), key=f"dg_dob_{draft_id}_{di}")
                                with dc2:
                                    decl["lot"]               = st.text_input("LOT (naš)",          value=decl.get("lot",""),               key=f"dg_lot_{draft_id}_{di}")
                                    decl["lot_dobavitelja"]   = st.text_input("LOT dobavitelja",    value=decl.get("lot_dobavitelja",""),    key=f"dg_lotd_{draft_id}_{di}")
                                    decl["kategorija_svezosti"] = st.text_input("Kategorija svežosti", value=decl.get("kategorija_svezosti",""), key=f"dg_kat_{draft_id}_{di}")
                                    decl["porabiti_do"]       = st.text_input("Porabiti do ⏳ TODO", value=decl.get("porabiti_do",""),       key=f"dg_por_{draft_id}_{di}")
                                    decl["datum_izlova"]      = st.text_input("Datum izlova",       value=decl.get("datum_izlova",""),      key=f"dg_izl_{draft_id}_{di}")
                                    decl["hraniti_temperatura"] = st.text_input("Hraniti pri temp.", value=decl.get("hraniti_temperatura",""), key=f"dg_tmp_{draft_id}_{di}")

                                st.caption(f"Vet. oznaka: {decl.get('veterinarska_oznaka', VET_OZNAKA)}")

                                # ZPL preview + download
                                zpl = _generate_zpl(decl)
                                col_zpl1, col_zpl2 = st.columns(2)
                                with col_zpl1:
                                    if st.button("🖨️ Natisni deklaracijo", key=f"print_{draft_id}_{di}",
                                                  use_container_width=True):
                                        # TODO: direktno tiskanje na Zebra GK420t
                                        st.info("⏳ Tiskanje na Zebra GK420t — v razvoju. "
                                                "Prenesite ZPL in pošljite na printer.")
                                with col_zpl2:
                                    st.download_button(
                                        "⬇️ Prenesi ZPL",
                                        data=zpl,
                                        file_name=f"dekl_{draft_id}_{di}.zpl",
                                        mime="text/plain",
                                        key=f"dl_zpl_{draft_id}_{di}",
                                        use_container_width=True,
                                    )

                # Shrani spremembe
                draft["header"]       = h
                drafts[draft_id]      = draft

    st.session_state["prejem_drafts"] = drafts

    # ═══════════════════════════════════════════════════════════
    # AKCIJSKI GUMBI (spodaj)
    # ═══════════════════════════════════════════════════════════
    st.divider()

    ready_ids = [
        did for did in (selected_ids or list(drafts.keys()))
        if not drafts[did].get("parse_error")
        and not drafts[did].get("sent_to_minimax")
        and not _has_critical(_validate(drafts[did].get("header",{}), drafts[did].get("rows",[])))
    ]

    col_send, col_del = st.columns(2)

    with col_send:
        n_ready = len([did for did in ready_ids if did in (selected_ids or list(drafts.keys()))])
        all_ok  = all(
            not _has_critical(_validate(drafts[did].get("header",{}), drafts[did].get("rows",[])))
            for did in drafts if not drafts[did].get("parse_error") and not drafts[did].get("sent_to_minimax")
        )
        if st.button(
            f"📤 Pošlji v Minimax  ({len(ready_ids)} osnutkov)",
            type="primary", use_container_width=True,
            disabled=not ready_ids,
            key="btn_send_minimax",
        ):
            to_send = selected_ids if selected_ids else list(drafts.keys())
            prog = st.progress(0)
            for i, did in enumerate([d for d in to_send if d in ready_ids]):
                prog.progress((i+1)/len(ready_ids), text=f"Prenašam …")
                entry_id, err = _send_draft(drafts[did])
                if err:
                    st.error(f"❌ {drafts[did]['header'].get('supplier_name','?')}: {err}")
                else:
                    drafts[did]["sent_to_minimax"]   = True
                    drafts[did]["minimax_entry_id"]  = entry_id
                    st.success(f"✅ {drafts[did]['header'].get('supplier_name','?')} → Minimax ID: {entry_id}")
            prog.empty()
            st.session_state["prejem_drafts"] = drafts
            st.rerun()

    with col_del:
        to_del = selected_ids if selected_ids else []
        if st.button(
            f"🗑️ Izbriši osnutke  ({len(to_del)} izbranih)",
            use_container_width=True,
            disabled=not to_del,
            key="btn_delete",
        ):
            for did in to_del:
                drafts.pop(did, None)
            st.session_state["prejem_drafts"] = drafts
            st.rerun()

    if selected_ids:
        st.caption(f"Izbrano: {len(selected_ids)} osnutkov")
    else:
        st.caption("Kljukica ob osnutku = izbor za pošiljanje/brisanje. Brez izbora = akcija velja za vse.")
