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
import os
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

# Znani mappingi po dobaviteljih (dopolnjujemo sproti)
SUPPLIER_ITEM_MAPPINGS = {
    "LIBO": {
        "OČIŠČENA": {
            "item_code": "POSSS0301",
            "item_name": "POSTRV (Šarenka), 300-400g, očiščena, sveža, Slovenija",
        },
        "FILE BEL": {
            "item_code": "POSSS0202",
            "item_name": "POSTRV (Šarenka), 160-200g, file, sveža, Slovenija",
        },
        "FILE RDEČ": {
            "item_code":  None,   # potrebna ročna delitev
            "item_name":  "⚠️ Razdeliti: LPOSS0202 (150-300g) ali LPOSS0102 (300g+)",
            "needs_split": True,
            "split_options": [
                {"item_code": "LPOSS0202", "item_name": "LOSOSOVA POSTRV file, 150-300g, svež, Slovenija"},
                {"item_code": "LPOSS0102", "item_name": "LOSOSOVA POSTRV file, 300g+, svež, Slovenija"},
            ],
        },
    },
}

def _apply_supplier_mapping(supplier_name: str, rows: list) -> list:
    """Aplicira znane mappinge po dobavitelju na liste artiklov."""
    sup_up = supplier_name.upper()
    mapping = None
    for key, val in SUPPLIER_ITEM_MAPPINGS.items():
        if key in sup_up:
            mapping = val
            break
    if not mapping:
        return rows

    for row in rows:
        inv_name_up = row.get("inv_name", "").upper()
        for keyword, data in mapping.items():
            if keyword.upper() in inv_name_up:
                row["item_code"] = data.get("item_code") or ""
                row["item_name"] = data.get("item_name") or ""
                if data.get("needs_split"):
                    row["_needs_split_hint"] = True
                    row["_split_options"]    = data.get("split_options", [])
                break
    return rows
OLTREON_INFO = "OltreCon d.o.o., Orehovlje 2F, 5291 Miren"
VET_OZNAKA   = "SI 844 ES"

STATUS_ICON  = {"ready": "🟢", "sent": "⚫", "error": "🔴"}

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

# ─── Trajno shranjevanje osnutkov ────────────────────────────────────────────

DRAFTS_FILE = "prejem_osnutki.json"

def _save_drafts(drafts: dict):
    """Shrani osnutke v JSON datoteko — preživi reboot in osvežitev strani."""
    try:
        # Serializiramo — izpustimo bytes (slike) ki jih ne moremo shraniti
        def _clean(obj):
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items() if k != "bytes"}
            elif isinstance(obj, list):
                return [_clean(i) for i in obj]
            return obj
        with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
            json.dump(_clean(drafts), f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.sidebar.warning(f"⚠️ Shranjevanje osnutkov: {e}")

def _load_drafts() -> dict:
    """Naloži osnutke iz JSON datoteke ob zagonu."""
    try:
        if os.path.exists(DRAFTS_FILE):
            with open(DRAFTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

# ─── Pomožne funkcije ─────────────────────────────────────────────────────────

def _secret(key, default=""):
    try:    return st.secrets[key]
    except: return default

def _lot_number(supplier_name: str, date_str: str) -> str:
    prefix = ""
    for key, val in SUPPLIER_PREFIXES.items():
        if key in supplier_name.upper():
            prefix = val; break
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
    return "DO +4°C"

def _build_declarations(header: dict, rows: list) -> list:
    """Kreira deklaracije — ena na unikaten artikel."""
    seen, decls = {}, []
    lot_nas    = header.get("lot_number", "")
    lot_dob    = header.get("lot_dobavitelja", "")
    datum_izl  = header.get("datum_izlova", "")
    kraj_prod  = header.get("kraj_proizvoda", "")

    for row in rows:
        key = row.get("item_code", "") or row.get("inv_name", "")
        if key in seen: continue
        seen[key] = True
        kategorija = row.get("kategorija", "sveže")
        decls.append({
            "naziv_blaga":         f"{row.get('item_name') or row.get('inv_name','')} ({row.get('latin_name','')})",
            "izdelek":             "",   # TODO: po vzorcu OltreCon
            "drzava_porekla":      row.get("country_of_origin", ""),
            "kraj_proizvoda":      kraj_prod or row.get("kraj_proizvoda", ""),
            "dobavitelj":          OLTREON_INFO,
            "lot":                 lot_nas,
            "lot_dobavitelja":     lot_dob or row.get("lot_dobavitelja", ""),
            "kategorija_svezosti": kategorija,
            "porabiti_do":         "",   # TODO: izračun po vzorcu
            "datum_izlova":        datum_izl or row.get("datum_izlova", ""),
            "hraniti_temperatura": _kategorija_temperatura(kategorija),
            "veterinarska_oznaka": VET_OZNAKA,
            "item_code":           row.get("item_code", ""),
            "item_name":           row.get("item_name") or row.get("inv_name", ""),
        })
    return decls

def _generate_zpl(decl: dict) -> str:
    """ZPL za Zebra GK420t — 8x5 cm. TODO: ovalni žig, IZDELEK, PORABITI DO."""
    def _esc(s): return (s or "")[:60]
    return f"""^XA
^PW609
^LL406
^CI28
^FO15,15^A0N,20,20^FDNAZIV BLAGA: {_esc(decl.get('naziv_blaga'))}^FS
^FO15,40^A0N,18,18^FDIZDLEK: {_esc(decl.get('izdelek'))}^FS
^FO15,65^A0N,18,18^FDDRZAVA POREKLA: {_esc(decl.get('drzava_porekla'))}^FS
^FO15,88^A0N,18,18^FDKRAJ PROIZVODA: {_esc(decl.get('kraj_proizvoda'))}^FS
^FO15,111^A0N,18,18^FDDOBAVITELJ: {_esc(decl.get('dobavitelj'))}^FS
^FO15,134^A0N,18,18^FDLOT: {_esc(decl.get('lot'))}^FS
^FO15,157^A0N,18,18^FDLOT DOBAVITELJA: {_esc(decl.get('lot_dobavitelja'))}^FS
^FO15,180^A0N,18,18^FDKATEGORIJA SVEZOSTI: {_esc(decl.get('kategorija_svezosti'))}^FS
^FO15,203^A0N,18,18^FDPORABITI DO: {_esc(decl.get('porabiti_do'))}^FS
^FO15,226^A0N,18,18^FDDATUM IZLOVA: {_esc(decl.get('datum_izlova'))}^FS
^FO15,249^A0N,18,18^FDHRANITI PRI TEMPERATURI: {_esc(decl.get('hraniti_temperatura'))}^FS
^FO480,300^A0N,18,18^FD{_esc(decl.get('veterinarska_oznaka'))}^FS
^XZ"""

# ─── Validacija ───────────────────────────────────────────────────────────────

def _validate(header: dict, rows: list) -> list:
    errors = []
    for field, typ, msg in REQUIRED_HEADER:
        if not header.get(field):
            errors.append((typ, f"Glava: {msg}"))
    if not rows:
        errors.append(("❌", "Ni artikov za vnos"))
    vnum = 0
    for row in rows:
        if row.get("_split_child"):
            continue
        vnum += 1
        if row.get("_split"):
            # Validacija split vrstice
            split_rows = row.get("_split_rows", [])
            orig_qty   = float(row.get("_orig_qty") or 0)
            split_sum  = round(sum(float(r.get("quantity") or 0) for r in split_rows), 4)
            if round(split_sum - orig_qty, 4) != 0:
                errors.append(("❌", f"Vrstica {vnum} ({row.get('inv_name','?')}): vsota delov ({split_sum}) ≠ originalna količina ({orig_qty})"))
            for si, srow in enumerate(split_rows, 1):
                if not srow.get("item_code"):
                    errors.append(("❌", f"Vrstica {vnum} del {si}: šifra artikla manjka"))
                if not srow.get("quantity") or float(srow.get("quantity",0)) <= 0:
                    errors.append(("❌", f"Vrstica {vnum} del {si}: količina mora biti > 0"))
        else:
            for field, typ, msg in REQUIRED_ROW:
                val = row.get(field)
                if field == "quantity":
                    if not val or float(val) <= 0:
                        errors.append((typ, f"Vrstica {vnum} ({row.get('inv_name','?')}): {msg}"))
                elif not val:
                    errors.append((typ, f"Vrstica {vnum} ({row.get('inv_name','?')}): {msg}"))
    return errors

def _has_critical(errors): return any(t == "❌" for t, _ in errors)

def _draft_status(draft: dict) -> str:
    if draft.get("parse_error"): return "error"
    if draft.get("sent_to_minimax"): return "sent"
    return "error" if _has_critical(_validate(draft.get("header",{}), draft.get("rows",[]))) else "ready"

# ─── Minimax prenos ───────────────────────────────────────────────────────────

def _get_item_id_by_code(cli, code):
    try:
        data = cli._get("/items", params={"Code": code, "CurrentPage": 1, "PageSize": 5})
        for r in data.get("Rows", []):
            if r.get("Code","").upper() == code.upper():
                return r.get("ItemId") or 0
    except: pass
    return 0

def _get_wh_id(cli):
    try:
        for wh in cli.get_warehouses():
            if wh.get("Code","") == VP_CEN_CODE:
                return wh.get("WarehouseId") or wh.get("ID") or 0
    except: pass
    return 0

def _get_supplier_id(cli, name):
    try:
        name_up, page = name.upper(), 1
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
        sup_id = _get_supplier_id(cli, draft["header"].get("supplier_name",""))
        if not sup_id: return None, "Dobavitelj ni najden v Minimaxu"
        stock_rows = []
        for row in draft["rows"]:
            if row.get("_split_child"):
                continue
            rows_to_process = row.get("_split_rows", []) if row.get("_split") else [row]
            for r in rows_to_process:
                item_id = _get_item_id_by_code(cli, r.get("item_code",""))
                if not item_id: return None, f"Artikel '{r.get('item_code')}' ni najden"
                sr = {
                    "Item":              {"ID": item_id},
                    "Quantity":          float(r.get("quantity") or 0),
                    "Price":             float(r.get("price") or 0),
                    "BatchNumber":       r.get("batch_number",""),
                    "UnitOfMeasurement": r.get("unit","kg"),
                    "WarehouseTo":       {"ID": wh_id},
                }
                if r.get("selling_price") and float(r.get("selling_price")) > 0:
                    sr["SellingPrice"] = float(r["selling_price"])
                stock_rows.append(sr)
        h    = draft["header"]
        body = {
            "StockEntryType":"P","StockEntrySubtype":"L","Status":"O",
            "Date":        h["invoice_date"]+"T00:00:00",
            "Description": f"{h.get('invoice_number','')} — {h.get('supplier_name','')}",
            "Supplier":    {"ID": sup_id},
            "WarehouseTo": {"ID": wh_id},
            "StockEntryRows": stock_rows,
        }
        result = cli._post("/stockentry", body)
        return result.get("StockEntryId") or result.get("ID") or "?", None
    except Exception as e:
        return None, str(e)

# ─── Iskanje artiklov ─────────────────────────────────────────────────────────

def _get_article_options() -> list:
    """Vrne vse znane artikle iz mappingov za iskanje."""
    articles, seen = [], set()
    for sup_mapping in SUPPLIER_ITEM_MAPPINGS.values():
        for keyword, data in sup_mapping.items():
            for opt in data.get("split_options", []):
                if opt["item_code"] not in seen:
                    articles.append(opt)
                    seen.add(opt["item_code"])
            if data.get("item_code") and data["item_code"] not in seen:
                articles.append({"item_code": data["item_code"],
                                  "item_name": data.get("item_name","")})
                seen.add(data["item_code"])
    return sorted(articles, key=lambda x: x.get("item_code",""))

def _search_articles(query: str, options: list) -> list:
    """Filtrira artikle po besedah (ne nujno zaporedni vrstni red)."""
    if not query.strip():
        return options
    words = query.lower().split()
    result = []
    for opt in options:
        text = f"{opt.get('item_code','')} {opt.get('item_name','')}".lower()
        if all(w in text for w in words):
            result.append(opt)
    return result

# ─── RENDER ───────────────────────────────────────────────────────────────────

def render():
    st.caption("Skeniranje dobavnic dobavitelja → P/L osnutek v VP-CEN + deklaracije")

    with st.sidebar:
        st.header("⚙️ Nastavitve")
        with st.expander("Minimax dostop", expanded=False):
            st.session_state["client_id"]     = st.text_input("Client ID",        value=_secret("MINIMAX_CLIENT_ID",""))
            st.session_state["client_secret"] = st.text_input("Client Secret",    value=_secret("MINIMAX_CLIENT_SECRET",""), type="password")
            st.session_state["username"]      = st.text_input("Uporabniško ime",  value=_secret("MINIMAX_USERNAME",""))
            st.session_state["password"]      = st.text_input("Geslo aplikacije", value=_secret("MINIMAX_PASSWORD",""), type="password")
            st.session_state["org_id"]        = st.text_input("ID organizacije",  value=_secret("MINIMAX_ORG_ID","171038"))

    if "prejem_drafts" not in st.session_state:
        st.session_state["prejem_drafts"] = _load_drafts()
    if "prejem_file_store" not in st.session_state:
        st.session_state["prejem_file_store"] = {}

    drafts     = st.session_state["prejem_drafts"]
    file_store = st.session_state["prejem_file_store"]

    # ═══════════════════════════════════════════════════════════
    # UPLOAD + OBDELAVA
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
            selected_files = []
            for fname in file_store:
                is_done = any(d.get("fname") == fname for d in drafts.values())
                if st.checkbox(f"{'✅' if is_done else '📄'} {fname}", value=not is_done, key=f"chk_f_{fname}"):
                    selected_files.append(fname)

            col1, col2 = st.columns([2,1])
            with col1:
                if st.button(f"🤖 Obdelaj z AI ({len(selected_files)})", type="primary",
                             use_container_width=True, disabled=not selected_files, key="btn_obdelaj"):
                    prog = st.progress(0)
                    for i, fname in enumerate(selected_files):
                        prog.progress((i+1)/len(selected_files), text=f"Berem {fname} …")
                        fdata  = file_store[fname]
                        mmap   = {"image/jpeg":"image/jpeg","image/jpg":"image/jpeg",
                                  "image/png":"image/png","application/pdf":"application/pdf"}
                        mtype  = mmap.get(fdata["type"],"image/jpeg")
                        parsed, err = _parse_claude(fdata["bytes"], mtype)

                        draft_id = str(uuid.uuid4())[:8]
                        if err or not parsed:
                            drafts[draft_id] = {"id":draft_id,"fname":fname,
                                "parse_error": err or "AI ni vrnil podatkov",
                                "header":{},"rows":[],"declarations":[],
                                "sent_to_minimax":False,"minimax_entry_id":None}
                            continue

                        lot      = _lot_number(parsed.get("supplier_name",""), parsed.get("invoice_date",""))
                        rows_out = []
                        for item in parsed.get("items",[]):
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
                        rows_out = _apply_supplier_mapping(parsed.get("supplier_name",""), rows_out)
                        drafts[draft_id] = {
                            "id":draft_id,"fname":fname,"parse_error":None,
                            "header":header,"rows":rows_out,
                            "declarations":_build_declarations(header, rows_out),
                            "sent_to_minimax":False,"minimax_entry_id":None,
                        }
                    prog.empty()
                    st.session_state["prejem_drafts"] = drafts
                    _save_drafts(drafts)
                    st.rerun()
            with col2:
                if st.button("↺ Počisti datoteke", use_container_width=True, key="btn_clr_f"):
                    st.session_state["prejem_file_store"] = {}
                    st.rerun()

    if not drafts:
        st.info("Naloži dobavnice zgoraj za začetek.")
        return

    # ═══════════════════════════════════════════════════════════
    # SEZNAM OSNUTKOV
    # ═══════════════════════════════════════════════════════════
    st.subheader("📋 Osnutki")
    st.markdown(f"{STATUS_ICON['ready']} Pripravljen &nbsp;&nbsp;"
                f"{STATUS_ICON['error']} Pomanjkljiv &nbsp;&nbsp;"
                f"{STATUS_ICON['sent']} Poslan v Minimax", unsafe_allow_html=True)

    # Master checkbox za izbiro vseh osnutkov
    prev_master_drafts = st.session_state.get("prev_master_drafts", None)
    master_sel_drafts  = st.checkbox(
        "☑ Izberi / odzberi vse osnutke",
        key="master_sel_all_drafts",
    )
    # Ob spremembi master → posodobi vse posamezne PRED renderiranjem
    if prev_master_drafts is not None and master_sel_drafts != prev_master_drafts:
        for did in drafts:
            st.session_state[f"sel_d_{did}"] = master_sel_drafts
    st.session_state["prev_master_drafts"] = master_sel_drafts
    st.markdown("---")

    selected_draft_ids = []

    for draft_id, draft in list(drafts.items()):
        status = _draft_status(draft)
        icon   = STATUS_ICON[status]
        h      = draft.get("header", {})
        fname  = draft.get("fname", "")

        col_chk, col_exp = st.columns([0.5, 9.5])
        with col_chk:
            sel = st.checkbox("", key=f"sel_d_{draft_id}")
            if sel: selected_draft_ids.append(draft_id)
        with col_exp:
            lbl = (f"{icon} **{h.get('supplier_name') or fname}**  ·  "
                   f"{h.get('invoice_date','?')}  ·  #{h.get('invoice_number','?')}  ·  "
                   f"{len(draft.get('rows',[]))} artikov  ·  "
                   f"{len(draft.get('declarations',[]))} deklaracij"
                   + (f"  ·  Minimax ID: {draft.get('minimax_entry_id')}" if draft.get("sent_to_minimax") else ""))

            with st.expander(lbl, expanded=False):
                if draft.get("parse_error"):
                    st.error(f"Napaka branja: {draft['parse_error']}")
                    continue

                errors = _validate(h, draft["rows"])
                if errors:
                    for typ, msg in errors: st.write(f"{typ} {msg}")
                    st.divider()

                # Header
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

                # ── TAB: ARTIKLI ──────────────────────────────────────────
                with tab_art:
                    for idx, row in enumerate(draft["rows"]):
                        if row.get("_split_child"):
                            continue

                        is_split  = bool(row.get("_split"))
                        all_coded = all(
                            (r.get("item_code") or "") != ""
                            for r in ([row] + row.get("_split_rows", []))
                        )
                        orig_qty  = float(row.get("_orig_qty") or row.get("quantity") or 0)
                        art_icon  = "✅" if all_coded else ("✂️" if is_split else "❌")

                        # Naslov: naziv dobavnice + Minimax naziv če je znan
                        mm_naziv = row.get("item_name","")
                        mm_label = f"  →  {mm_naziv}" if mm_naziv and not row.get("_needs_split_hint") else ""
                        split_label = " — ⚠️ razdeliti!" if row.get("_needs_split_hint") and not is_split else ""
                        if is_split:
                            exp_suffix = " — ✂️ razdeljena"
                        elif row.get("item_code"):
                            exp_suffix = f"  `{row['item_code']}`{mm_label}"
                        elif row.get("_needs_split_hint"):
                            exp_suffix = split_label
                        else:
                            exp_suffix = " — šifra manjka"
                        with st.expander(
                            f"{art_icon} {idx+1}. {row['inv_name']}  ({orig_qty} {row.get('unit','kg')}){exp_suffix}",
                            expanded=False
                        ):
                            if row.get("latin_name"):
                                st.caption(f"🔬 *{row['latin_name']}*")

                            if not is_split:
                                # Normalna vrstica
                                cc1,cc2,cc3,cc4 = st.columns(4)
                                with cc1:
                                    row["item_code"] = st.text_input("Minimax šifra ⚠️", value=row.get("item_code",""), key=f"code_{draft_id}_{idx}")
                                    row["quantity"]  = st.number_input("Količina", value=float(row.get("quantity") or 0), min_value=0.0, step=0.001, format="%.3f", key=f"qty_{draft_id}_{idx}")
                                with cc2:
                                    row["unit"]  = st.text_input("ME", value=row.get("unit","kg"), key=f"unit_{draft_id}_{idx}")
                                    row["price"] = st.number_input("Nab. cena €", value=float(row.get("price") or 0), min_value=0.0, step=0.01, format="%.4f", key=f"price_{draft_id}_{idx}")
                                with cc3:
                                    row["selling_price"] = st.number_input("Prod. cena €", value=float(row.get("selling_price") or 0), min_value=0.0, step=0.01, format="%.4f", key=f"sell_{draft_id}_{idx}")
                                    row["batch_number"]  = st.text_input("Serija / Lot", value=row.get("batch_number",""), key=f"batch_{draft_id}_{idx}")
                                with cc4:
                                    row["country_of_origin"] = st.text_input("Država (2 črkoven)", value=row.get("country_of_origin",""), key=f"cntry_{draft_id}_{idx}")
                                    row["tariff"]            = st.text_input("Carinska tarifa", value=row.get("tariff",""), key=f"tariff_{draft_id}_{idx}")

                                # Hint za split (npr. Libo FILE RDEČ)
                                if row.get("_needs_split_hint") and not is_split:
                                    st.warning("⚠️ Ta artikel zahteva ročno delitev glede na velikost!")
                                    opts = row.get("_split_options", [])
                                    if opts:
                                        st.caption("Možnosti: " + " · ".join(f"`{o['item_code']}` {o['item_name']}" for o in opts))

                                if st.button("✂️ Razdeli vrstico", key=f"split_{draft_id}_{idx}",
                                             help="Razdeli na več Minimax artiklov"):
                                    row["_split"]    = True
                                    row["_orig_qty"] = orig_qty
                                    opts = row.get("_split_options", [])
                                    template = {k:v for k,v in row.items() if not k.startswith("_")}
                                    row["_split_rows"] = [
                                        {**template,
                                         "item_code": opts[0]["item_code"] if opts else "",
                                         "item_name": opts[0]["item_name"] if opts else "",
                                         "quantity": 0.0, "_split_child": True},
                                    ]
                                    st.rerun()
                            else:
                                # ── Razdeljena vrstica — st.form preprečuje zapiranje ob spremembi
                                split_rows  = row.get("_split_rows", [])
                                all_opts    = _get_article_options()
                                opt_labels  = ["— izberi —"] + [f"{o['item_code']}  {o['item_name']}" for o in all_opts]

                                split_sum = round(sum(float(r.get("quantity") or 0) for r in split_rows), 4)
                                diff      = round(orig_qty - split_sum, 4)
                                st.caption(f"Skupna količina dobavnice: **{orig_qty} {row.get('unit','kg')}**")
                                if diff != 0:
                                    st.warning(f"⚠️ Vsota delov: **{split_sum} kg** — manjka še **{diff} kg**")
                                else:
                                    st.success(f"✅ Vsota delov: {split_sum} kg = {orig_qty} kg")

                                with st.form(key=f"form_split_{draft_id}_{idx}"):
                                    for si, srow in enumerate(split_rows):
                                        st.markdown(f"**Del {si+1}:**")

                                        # Iskanje artikla
                                        search_q = st.text_input(
                                            "Minimax artikel (išči po šifri ali nazivu)",
                                            value=srow.get("item_code",""),
                                            key=f"sq_{draft_id}_{idx}_{si}",
                                            placeholder="npr: POSSS ali postrv file ali 300-400"
                                        )
                                        filtered = _search_articles(search_q, all_opts)
                                        f_labels  = ["— izberi —"] + [f"{o['item_code']}  {o['item_name']}" for o in filtered]
                                        # Predizpolni indeks če je šifra že znana
                                        curr_code = srow.get("item_code","")
                                        curr_idx  = next((i+1 for i,o in enumerate(filtered) if o["item_code"]==curr_code), 0)
                                        sel_art = st.selectbox(
                                            "Izberi artikel",
                                            f_labels,
                                            index=curr_idx,
                                            key=f"sel_{draft_id}_{idx}_{si}",
                                            label_visibility="collapsed",
                                        )

                                        sc1, sc2, sc3, sc4 = st.columns(4)
                                        with sc1:
                                            srow["quantity"] = st.number_input("Količina (kg)", value=float(srow.get("quantity") or 0), min_value=0.0, step=0.001, format="%.3f", key=f"sqty_{draft_id}_{idx}_{si}")
                                        with sc2:
                                            srow["price"] = st.number_input("Nab. cena €", value=float(srow.get("price") or 0), min_value=0.0, step=0.01, format="%.4f", key=f"sprice_{draft_id}_{idx}_{si}")
                                        with sc3:
                                            srow["selling_price"] = st.number_input("Prod. cena €", value=float(srow.get("selling_price") or 0), min_value=0.0, step=0.01, format="%.4f", key=f"ssell_{draft_id}_{idx}_{si}")
                                            srow["batch_number"]  = st.text_input("Serija / Lot", value=srow.get("batch_number",""), key=f"sbatch_{draft_id}_{idx}_{si}")
                                        with sc4:
                                            srow["country_of_origin"] = st.text_input("Država", value=srow.get("country_of_origin",""), key=f"scntry_{draft_id}_{idx}_{si}")
                                            srow["tariff"]            = st.text_input("Tarifa", value=srow.get("tariff",""), key=f"stariff_{draft_id}_{idx}_{si}")

                                        if si < len(split_rows)-1:
                                            st.divider()

                                    # Gumbi znotraj forme
                                    fa, fb, fc, fd = st.columns(4)
                                    with fa:
                                        add_part = st.form_submit_button("➕ Dodaj del", use_container_width=True)
                                    with fb:
                                        rem_part = st.form_submit_button("➖ Odstrani zadnji", use_container_width=True,
                                                                          disabled=len(split_rows) <= 1)
                                    with fc:
                                        unsplit  = st.form_submit_button("↺ Razveljavi", use_container_width=True)
                                    with fd:
                                        confirm  = st.form_submit_button("✅ Potrdi", type="primary", use_container_width=True)

                                    if confirm or add_part or rem_part or unsplit:
                                        # Najprej apliciraj iskanje / selekcijo na vsak del
                                        for si, srow in enumerate(split_rows):
                                            sel_key = f"sel_{draft_id}_{idx}_{si}"
                                            sel_val = st.session_state.get(sel_key, "— izberi —")
                                            if sel_val and sel_val != "— izberi —":
                                                code = sel_val.split("  ")[0].strip()
                                                name_part = sel_val[len(code):].strip()
                                                srow["item_code"] = code
                                                srow["item_name"] = name_part
                                        if add_part:
                                            template = {k:v for k,v in row.items() if not k.startswith("_")}
                                            split_rows.append({**template,"item_code":"","item_name":"","quantity":0.0,"_split_child":True})
                                        if rem_part and len(split_rows) > 1:
                                            split_rows.pop()
                                        if unsplit:
                                            for k in ["_split","_orig_qty","_split_rows"]:
                                                row.pop(k, None)
                                        row["_split_rows"] = split_rows
                                        st.session_state["prejem_drafts"] = drafts
                                        _save_drafts(drafts)
                                        st.rerun()


                    if draft["rows"]:
                        total = 0.0
                        for r in draft["rows"]:
                            if r.get("_split"):
                                for sr in r.get("_split_rows",[]):
                                    total += float(sr.get("quantity") or 0) * float(sr.get("price") or 0)
                            elif not r.get("_split_child"):
                                total += float(r.get("quantity") or 0) * float(r.get("price") or 0)
                        st.metric("Skupna nabavna vrednost", f"{total:.2f} €")
                # ── TAB: DEKLARACIJE ──────────────────────────────────────
                with tab_decl:
                    draft["declarations"] = _build_declarations(h, draft["rows"])
                    decls = draft["declarations"]

                    if not decls:
                        st.info("Deklaracije bodo generirane ko so artikli določeni.")
                    else:
                        # ── Master vrstica: izberi vse + skupne kopije ────
                        prev_msd_k = f"prev_msd_{draft_id}"
                        m_col1, m_col2, m_col3 = st.columns([0.5, 5, 1.5])
                        with m_col1:
                            master_sel_decl = st.checkbox(
                                "☑", key=f"msd_{draft_id}",
                                help="Izberi / odzberi vse deklaracije"
                            )
                            # Ob spremembi → posodobi vse posamezne PRED renderiranjem
                            prev_msd = st.session_state.get(prev_msd_k, None)
                            if prev_msd is not None and master_sel_decl != prev_msd:
                                for di2 in range(len(decls)):
                                    st.session_state[f"ds_{draft_id}_{di2}"] = master_sel_decl
                            st.session_state[prev_msd_k] = master_sel_decl
                        with m_col2:
                            st.markdown("**Deklaracija**")
                        with m_col3:
                            # Master kopije — ko se spremeni, posodobi vse posamezne
                            prev_master_k = f"prev_mc_{draft_id}"
                            master_copies = st.number_input(
                                "Kopije (vse)", min_value=1, max_value=99, value=1,
                                key=f"mc_{draft_id}", label_visibility="collapsed",
                                help="Nastavi število kopij za vse deklaracije"
                            )
                            prev_val = st.session_state.get(prev_master_k, master_copies)
                            if master_copies != prev_val:
                                for di2 in range(len(decls)):
                                    st.session_state[f"ic_{draft_id}_{di2}"] = master_copies
                            st.session_state[prev_master_k] = master_copies

                        st.markdown("---")

                        # ── Posamezne deklaracije ─────────────────────────
                        selected_decls = []
                        for di, decl in enumerate(decls):
                            d_col1, d_col2, d_col3 = st.columns([0.5, 5, 1.5])
                            with d_col1:
                                d_sel = st.checkbox("", key=f"ds_{draft_id}_{di}")
                            with d_col2:
                                # Naslov deklaracije: naziv artikla + Minimax šifra če je znana
                                decl_title = decl.get('item_name') or decl.get('naziv_blaga','')
                                decl_code  = decl.get('item_code','')
                                decl_label = f"🏷️ {decl_title}" + (f"  `{decl_code}`" if decl_code else "")
                                with st.expander(decl_label, expanded=False):
                                    dc1, dc2 = st.columns(2)
                                    with dc1:
                                        decl["naziv_blaga"]       = st.text_input("Naziv blaga",       value=decl.get("naziv_blaga",""),          key=f"dn_{draft_id}_{di}")
                                        decl["izdelek"]           = st.text_input("Izdelek ⏳",        value=decl.get("izdelek",""),              key=f"di_{draft_id}_{di}")
                                        decl["drzava_porekla"]    = st.text_input("Država porekla",    value=decl.get("drzava_porekla",""),       key=f"dd_{draft_id}_{di}")
                                        decl["kraj_proizvoda"]    = st.text_input("Kraj proizvoda",    value=decl.get("kraj_proizvoda",""),       key=f"dk_{draft_id}_{di}")
                                        decl["dobavitelj"]        = st.text_input("Dobavitelj",        value=decl.get("dobavitelj",OLTREON_INFO), key=f"ddo_{draft_id}_{di}")
                                    with dc2:
                                        decl["lot"]               = st.text_input("LOT (naš)",         value=decl.get("lot",""),                  key=f"dl_{draft_id}_{di}")
                                        decl["lot_dobavitelja"]   = st.text_input("LOT dobavitelja",   value=decl.get("lot_dobavitelja",""),      key=f"dld_{draft_id}_{di}")
                                        decl["kategorija_svezosti"] = st.text_input("Kategorija",      value=decl.get("kategorija_svezosti",""), key=f"dks_{draft_id}_{di}")
                                        decl["porabiti_do"]       = st.text_input("Porabiti do ⏳",    value=decl.get("porabiti_do",""),          key=f"dp_{draft_id}_{di}")
                                        decl["datum_izlova"]      = st.text_input("Datum izlova",      value=decl.get("datum_izlova",""),         key=f"diz_{draft_id}_{di}")
                                        decl["hraniti_temperatura"] = st.text_input("Hraniti pri T.",  value=decl.get("hraniti_temperatura",""), key=f"dht_{draft_id}_{di}")
                                    st.caption(f"Vet. oznaka: {VET_OZNAKA}")
                            with d_col3:
                                ind_copies = st.number_input(
                                    "Kopije", min_value=1, max_value=99,
                                    value=int(st.session_state.get(f"ic_{draft_id}_{di}", master_copies)),
                                    key=f"ic_{draft_id}_{di}",
                                    label_visibility="collapsed",
                                )
                            if d_sel:
                                selected_decls.append((di, decl, ind_copies))

                        # ── Gumb NATISNI (pod seznamom) ───────────────────
                        st.markdown("---")
                        if st.button(
                            f"🖨️ Natisni deklaracije ({len(selected_decls)} izbranih · "
                            f"{sum(c for _,_,c in selected_decls)} kopij skupaj)",
                            key=f"print_{draft_id}",
                            type="primary",
                            use_container_width=True,
                            disabled=not selected_decls,
                        ):
                            # TODO: direktno tiskanje na Zebra GK420t
                            # Zaenkrat generiramo ZPL datoteke za prenos
                            zpl_all = ""
                            for di, decl, copies in selected_decls:
                                for _ in range(copies):
                                    zpl_all += _generate_zpl(decl) + "\n"
                            st.download_button(
                                f"⬇️ Prenesi ZPL ({len(selected_decls)} deklaracij)",
                                data=zpl_all,
                                file_name=f"deklaracije_{draft_id}.zpl",
                                mime="text/plain",
                                key=f"dl_all_zpl_{draft_id}",
                            )
                            st.info("⏳ Direktno tiskanje na Zebra GK420t bo implementirano ko dobimo vzorec OltreCon deklaracije.")

                # Shrani spremembe
                draft["header"]       = h
                drafts[draft_id]      = draft

    st.session_state["prejem_drafts"] = drafts
    _save_drafts(drafts)

    # ═══════════════════════════════════════════════════════════
    # AKCIJSKI GUMBI
    # ═══════════════════════════════════════════════════════════
    # Gumb za brisanje nad črto — bolj pri roki
    st.markdown("---")
    del_col1, del_col2 = st.columns([2, 1])
    with del_col1:
        to_del_top = selected_draft_ids if selected_draft_ids else []
        if st.button(
            f"🗑️ Izbriši dobavnice  ({len(to_del_top)} izbranih)" if to_del_top
            else "🗑️ Izbriši dobavnice  (označi za brisanje)",
            use_container_width=True,
            disabled=not to_del_top,
            key="btn_del_top",
        ):
            for did in to_del_top:
                drafts.pop(did, None)
            st.session_state["prejem_drafts"] = drafts
            _save_drafts(drafts)
            st.rerun()

    st.divider()

    to_act = selected_draft_ids if selected_draft_ids else list(drafts.keys())
    ready_ids = [
        did for did in to_act
        if not drafts[did].get("parse_error")
        and not drafts[did].get("sent_to_minimax")
        and not _has_critical(_validate(drafts[did].get("header",{}), drafts[did].get("rows",[])))
    ]

    col_send, col_del = st.columns(2)
    with col_send:
        if st.button(
            f"📤 Pošlji v Minimax  ({len(ready_ids)} osnutkov)",
            type="primary", use_container_width=True,
            disabled=not ready_ids, key="btn_send",
        ):
            prog = st.progress(0)
            for i, did in enumerate(ready_ids):
                prog.progress((i+1)/len(ready_ids), text="Prenašam …")
                entry_id, err = _send_draft(drafts[did])
                if err:
                    st.error(f"❌ {drafts[did]['header'].get('supplier_name','?')}: {err}")
                else:
                    drafts[did]["sent_to_minimax"]  = True
                    drafts[did]["minimax_entry_id"] = entry_id
                    st.success(f"✅ {drafts[did]['header'].get('supplier_name','?')} → ID: {entry_id}")
            prog.empty()
            st.session_state["prejem_drafts"] = drafts
            _save_drafts(drafts)
            st.rerun()

    with col_del:
        to_del = selected_draft_ids
        if st.button(
            f"🗑️ Izbriši osnutke  ({len(to_del)} izbranih)",
            use_container_width=True, disabled=not to_del, key="btn_del",
        ):
            for did in to_del:
                drafts.pop(did, None)
            st.session_state["prejem_drafts"] = drafts
            _save_drafts(drafts)
            st.rerun()

    if selected_draft_ids:
        st.caption(f"Izbrano: {len(selected_draft_ids)} osnutkov")
    else:
        st.caption("Brez izbora = akcija velja za vse osnutke.")
