"""
Tab: Prejem blaga
Skeniranje dobavnic dobavitelja → P/L osnutek v Minimaxu (VP-CEN)
"""

import streamlit as st
import pandas as pd
import json
import base64
import re
import traceback
from datetime import datetime

from minimax_client import MinimaxClient

# ─── Konstante ────────────────────────────────────────────────────────────────

SUPPLIER_PREFIXES = {
    "ALEMAR":           "AL",
    "CERKVENIK":        "CE",
    "KVIBO":            "KV",
    "FIORITAL":         "FI",
    "FORMIO":           "FO",
    "LIBO":             "LI",
    "COST IN":          "CI",
    "ORADA ADRIATIC":   "OA",
    "MARTINOVIC":       "MF",
    "MARTINOVIĆ":       "MF",
    "ROMICA":           "RO",
    "RO-TRADE":         "RT",
    "MADIA":            "MA",
    "FRULPESCA":        "FP",
}

VP_CEN_CODE = "VP-CEN"

REQUIRED_HEADER = [
    ("supplier_id",    "❌", "Dobavitelj ni določen"),
    ("invoice_date",   "❌", "Datum dobavnice manjka"),
    ("invoice_number", "❌", "Številka dobavnice manjka"),
]
REQUIRED_ROW = [
    ("item_id",           "❌", "Artikel ni določen"),
    ("quantity",          "❌", "Količina mora biti > 0"),
    ("batch_number",      "❌", "Serija (lot) manjka"),
    ("price",             "⚠️", "Nabavna cena ni določena"),
    ("country_of_origin", "⚠️", "Država porekla manjka"),
    ("tariff",            "⚠️", "Tarifa manjka"),
]

# ─── Pomožne funkcije ─────────────────────────────────────────────────────────

def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return default

def _get_client() -> MinimaxClient:
    return MinimaxClient(
        username=st.session_state.get("username", _secret("MINIMAX_USERNAME", "")),
        password=st.session_state.get("password", _secret("MINIMAX_PASSWORD", "")),
        client_id=st.session_state.get("client_id", _secret("MINIMAX_CLIENT_ID", "")),
        client_secret=st.session_state.get("client_secret", _secret("MINIMAX_CLIENT_SECRET", "")),
        org_id=int(st.session_state.get("org_id", _secret("MINIMAX_ORG_ID", "171038"))),
    )

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
    except Exception:
        return f"{prefix}??????"

# ─── Minimax podatki (cached) ─────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def _load_items(username, org_id):
    cli = MinimaxClient(
        username=username,
        password=_secret("MINIMAX_PASSWORD", ""),
        client_id=_secret("MINIMAX_CLIENT_ID", ""),
        client_secret=_secret("MINIMAX_CLIENT_SECRET", ""),
        org_id=int(org_id),
    )
    result, page = [], 1
    while True:
        data = cli._get("/items", params={"CurrentPage": page, "PageSize": 500})
        rows = data.get("Rows", [])
        for r in rows:
            intra = r.get("Intrastat") or {}
            result.append({
                "item_id":       r.get("ItemId"),
                "name":          r.get("Name", ""),
                "code":          r.get("Code", "") or "",
                "description":   r.get("Description", "") or "",
                "unit":          r.get("UnitOfMeasurement", "kg"),
                "selling_price": float(r.get("SellingPrice") or 0),
                "tariff":        intra.get("CustomsTariffNumber", "") or r.get("CustomsTariffNumber", "") or "",
                "country":       intra.get("CountryOfOrigin", "") or r.get("CountryOfOrigin", "") or "",
            })
        if len(result) >= data.get("TotalRows", 0) or not rows:
            break
        page += 1
    return result

@st.cache_data(ttl=3600, show_spinner=False)
def _load_warehouses(username, org_id):
    cli = MinimaxClient(
        username=username,
        password=_secret("MINIMAX_PASSWORD", ""),
        client_id=_secret("MINIMAX_CLIENT_ID", ""),
        client_secret=_secret("MINIMAX_CLIENT_SECRET", ""),
        org_id=int(org_id),
    )
    return cli.get_warehouses()

@st.cache_data(ttl=3600, show_spinner=False)
def _load_suppliers(username, org_id):
    cli = MinimaxClient(
        username=username,
        password=_secret("MINIMAX_PASSWORD", ""),
        client_id=_secret("MINIMAX_CLIENT_ID", ""),
        client_secret=_secret("MINIMAX_CLIENT_SECRET", ""),
        org_id=int(org_id),
    )
    result, page = [], 1
    while True:
        data = cli._get("/suppliers", params={"CurrentPage": page, "PageSize": 100})
        rows = data.get("Rows", [])
        result.extend(rows)
        if len(result) >= data.get("TotalRows", 0) or not rows:
            break
        page += 1
    return result

def _find_wh_id(warehouses, code):
    for wh in warehouses:
        if wh.get("Code", "") == code:
            return wh.get("WarehouseId") or wh.get("ID") or 0
    return 0

def _find_supplier(suppliers, name):
    name_up = name.upper()
    best_id, best_name, best_score = 0, "", 0
    for s in suppliers:
        sn = (s.get("Name") or s.get("CompanyName") or "").upper()
        si = s.get("SupplierId") or s.get("ID") or 0
        if name_up == sn:
            return si, s.get("Name") or s.get("CompanyName") or ""
        score = sum(len(w) for w in name_up.split() if len(w) > 3 and w in sn)
        if score > best_score:
            best_score, best_id = score, si
            best_name = s.get("Name") or s.get("CompanyName") or ""
    return best_id, best_name

def _auto_load():
    """Avtomatsko naloži podatke ob prvem obisku."""
    if st.session_state.get("prejem_data_ok"):
        return True
    username = _secret("MINIMAX_USERNAME", st.session_state.get("username", ""))
    org_id   = _secret("MINIMAX_ORG_ID",   st.session_state.get("org_id", "171038"))
    if not username:
        return False
    try:
        items      = _load_items(username, org_id)
        warehouses = _load_warehouses(username, org_id)
        suppliers  = _load_suppliers(username, org_id)
        wh_id      = _find_wh_id(warehouses, VP_CEN_CODE)
        st.session_state["prejem_items"]    = items
        st.session_state["prejem_suppliers"] = suppliers
        st.session_state["prejem_wh_id"]    = wh_id
        st.session_state["prejem_data_ok"]  = True
        return True
    except Exception as e:
        st.error(f"Napaka pri nalaganju podatkov iz Minimaxa: {e}")
        return False

# ─── Matching engine ──────────────────────────────────────────────────────────

_LATIN_RE = re.compile(r'/([^/]+)/')
_SIZE_RE  = re.compile(r'(\d+)[–\-](\d+)\s*(g|kg)?', re.IGNORECASE)
_STATE_MAP = {
    'svež':'svež','sveža':'svež','sveže':'svež','fresh':'svež',
    'zamrznjen':'zamrznjen','frozen':'zamrznjen','congelato':'zamrznjen',
    'odtaljen':'odtaljen','thawed':'odtaljen','scongelato':'odtaljen',
}

def _latin(text):
    m = _LATIN_RE.search(text)
    return m.group(1).lower().strip() if m else ""

def _size(text):
    m = _SIZE_RE.search(text)
    if not m: return None
    lo, hi = int(m.group(1)), int(m.group(2))
    if (m.group(3) or "").lower() == "kg":
        lo, hi = lo*1000, hi*1000
    return lo, hi

def _state(text):
    t = text.lower()
    for k, v in _STATE_MAP.items():
        if k in t: return v
    return ""

def match_item(inv_item, our_items):
    inv_name    = inv_item.get("name", "")
    inv_tariff  = (inv_item.get("tariff") or "").strip().replace(" ","").replace(".","")
    inv_latin   = (inv_item.get("latin_name") or "").lower().strip()
    inv_country = (inv_item.get("country_of_origin") or "").upper()[:2]
    inv_size    = _size(inv_name)
    inv_state   = _state(inv_name)

    best_item, best_score, best_reason = None, -1, ""
    for item in our_items:
        score, reasons = 0, []
        item_tariff = (item.get("tariff") or "").strip().replace(" ","").replace(".","")
        item_latin  = _latin(item.get("description", ""))
        item_name   = item.get("name", "")
        item_country= (item.get("country") or "").upper()[:2]
        item_size   = _size(item_name)
        item_state  = _state(item_name)

        if inv_tariff and item_tariff:
            if inv_tariff[:8] == item_tariff[:8]:
                score += 60; reasons.append("tarifa8✓")
            elif inv_tariff[:6] == item_tariff[:6]:
                score += 35; reasons.append("tarifa6~")
        if inv_latin and item_latin:
            if inv_latin == item_latin:
                score += 50; reasons.append("latinski✓")
            elif inv_latin in item_latin or item_latin in inv_latin:
                score += 30; reasons.append("latinski~")
        if inv_size and item_size:
            lo1,hi1 = inv_size; lo2,hi2 = item_size
            if lo1==lo2 and hi1==hi2:
                score += 20; reasons.append("velikost✓")
            elif abs(lo1-lo2) < 300:
                score += 8;  reasons.append("velikost~")
        if inv_state and item_state:
            if inv_state == item_state:
                score += 15; reasons.append("stanje✓")
            else:
                score -= 15
        if inv_country and item_country and inv_country == item_country:
            score += 10; reasons.append("država✓")

        if score > best_score:
            best_score = score; best_item = item
            best_reason = ", ".join(reasons)

    conf = "🟢 visoka" if best_score >= 60 else ("🟡 srednja" if best_score >= 30 else "🔴 nizka")
    return best_item, conf, best_reason, best_score

# ─── Claude Vision ────────────────────────────────────────────────────────────

_PARSE_PROMPT = """Analiziraj to dobavnico / račun dobavitelja za ribe in morske sadeže.
Vrni SAMO čist JSON brez markdown backticks, brez komentarjev.

{
  "supplier_name": "ime dobavitelja",
  "invoice_number": "številka računa",
  "invoice_date": "YYYY-MM-DD",
  "items": [
    {
      "name": "naziv artikla",
      "latin_name": "latinsko ime če je navedeno",
      "quantity": 0.000,
      "unit": "kg",
      "price": 0.00,
      "country_of_origin": "2-črkovna ISO koda (HR, IT, NO...)",
      "tariff": "carinska tarifa brez presledkov",
      "fao_zone": "FAO cona če je navedena",
      "notes": ""
    }
  ]
}

Pravila: invoice_date=YYYY-MM-DD, country_of_origin=2 črki, tariff=samo cifre, price=nabavna cena/enoto."""

def _parse_claude(image_bytes, media_type="image/jpeg"):
    try:
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {}, "ANTHROPIC_API_KEY ni v st.secrets"
        client = anthropic.Anthropic(api_key=api_key)
        b64    = base64.b64encode(image_bytes).decode()
        block  = ({"type":"document","source":{"type":"base64","media_type":media_type,"data":b64}}
                  if media_type == "application/pdf"
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

# ─── Validacija ───────────────────────────────────────────────────────────────

def _validate(header, rows):
    errors = []
    for field, typ, msg in REQUIRED_HEADER:
        val = header.get(field)
        if not val or (isinstance(val, int) and val == 0):
            errors.append((typ, f"Glava: {msg}"))
    if not rows:
        errors.append(("❌", "Ni artikov za vnos"))
    for i, row in enumerate(rows, 1):
        for field, typ, msg in REQUIRED_ROW:
            val = row.get(field)
            if field == "quantity":
                if not val or float(val) <= 0:
                    errors.append((typ, f"Vrstica {i}: {msg}"))
            elif not val:
                errors.append((typ, f"Vrstica {i}: {msg}"))
    return errors

def _has_critical(errors):
    return any(t == "❌" for t, _ in errors)

# ─── Kreiranje P/L ────────────────────────────────────────────────────────────

def _create_pl(cli, wh_id, header, rows):
    stock_rows = []
    for row in rows:
        sr = {
            "Item":              {"ID": row["item_id"]},
            "Quantity":          float(row["quantity"]),
            "Price":             float(row.get("price") or 0),
            "BatchNumber":       row.get("batch_number", ""),
            "UnitOfMeasurement": row.get("unit", "kg"),
            "WarehouseTo":       {"ID": wh_id},
        }
        sp = row.get("selling_price")
        if sp and float(sp) > 0:
            sr["SellingPrice"] = float(sp)
        stock_rows.append(sr)
    body = {
        "StockEntryType":    "P",
        "StockEntrySubtype": "L",
        "Status":            "O",
        "Date":              header["invoice_date"] + "T00:00:00",
        "Description":       f"{header.get('invoice_number','')} — {header.get('supplier_name','')}",
        "Supplier":          {"ID": header["supplier_id"]},
        "WarehouseTo":       {"ID": wh_id},
        "StockEntryRows":    stock_rows,
    }
    return cli._post("/stockentry", body)

# ─── RENDER ───────────────────────────────────────────────────────────────────

def render():
    st.caption("Skeniranje dobavnic dobavitelja → P/L osnutek v Veleprodajnem skladišču (VP-CEN)")

    # Sidebar: samo credentials + cache
    with st.sidebar:
        st.header("⚙️ Nastavitve API")
        with st.expander("Minimax dostop", expanded=True):
            st.session_state["client_id"]     = st.text_input("Client ID",        value=_secret("MINIMAX_CLIENT_ID",""))
            st.session_state["client_secret"] = st.text_input("Client Secret",    value=_secret("MINIMAX_CLIENT_SECRET",""), type="password")
            st.session_state["username"]      = st.text_input("Uporabniško ime",  value=_secret("MINIMAX_USERNAME",""))
            st.session_state["password"]      = st.text_input("Geslo aplikacije", value=_secret("MINIMAX_PASSWORD",""), type="password")
            st.session_state["org_id"]        = st.text_input("ID organizacije",  value=_secret("MINIMAX_ORG_ID","171038"))
        st.divider()
        if st.button("🗑️ Počisti cache", use_container_width=True):
            _load_items.clear(); _load_warehouses.clear(); _load_suppliers.clear()
            for k in ["prejem_items","prejem_suppliers","prejem_wh_id","prejem_data_ok"]:
                st.session_state.pop(k, None)
            st.success("Cache počiščen!")

    # ── Avtomatsko nalaganje podatkov ─────────────────────────────────────────
    if not st.session_state.get("prejem_data_ok"):
        with st.spinner("Nalagam artikle in dobavitelje iz Minimaxa …"):
            ok = _auto_load()
        if not ok:
            st.error("Ne morem naložiti podatkov. Preverite credentials v stranski vrstici.")
            return

    items     = st.session_state["prejem_items"]
    suppliers = st.session_state["prejem_suppliers"]
    wh_id     = st.session_state["prejem_wh_id"]

    if not wh_id:
        st.error("⚠️ Skladišče VP-CEN ni najdeno v Minimaxu!")
        return

    # ═══════════════════════════════════════════════════════════════════
    # KORAK 1: Naloži dobavnice
    # ═══════════════════════════════════════════════════════════════════
    st.subheader("1️⃣ Naloži dobavnice")

    uploaded_files = st.file_uploader(
        "Izberite eno ali več dobavnic (slike ali PDF)",
        type=["jpg","jpeg","png","pdf"],
        accept_multiple_files=True,
        key="prejem_uploader",
        label_visibility="collapsed",
    )

    # Shrani bytes v session_state (file objekti se izgubijo ob rerun)
    if uploaded_files:
        if "prejem_file_store" not in st.session_state:
            st.session_state["prejem_file_store"] = {}
        for f in uploaded_files:
            if f.name not in st.session_state["prejem_file_store"]:
                st.session_state["prejem_file_store"][f.name] = {
                    "bytes": f.read(), "type": f.type, "name": f.name,
                }

    file_store = st.session_state.get("prejem_file_store", {})

    if not file_store:
        return

    # ═══════════════════════════════════════════════════════════════════
    # KORAK 2: Izbor in obdelava
    # ═══════════════════════════════════════════════════════════════════
    st.divider()
    st.subheader("2️⃣ Izberite dokumente za obdelavo")

    selected = []
    for fname in file_store:
        is_done = fname in st.session_state.get("prejem_drafts", {})
        label = f"{'✅' if is_done else '📄'} {fname}"
        if st.checkbox(label, value=True, key=f"chk_{fname}"):
            selected.append(fname)

    col_obdelaj, col_reset = st.columns([2,1])
    with col_obdelaj:
        if st.button(
            f"🤖 Obdelaj izbrane ({len(selected)})",
            type="primary", use_container_width=True,
            disabled=len(selected)==0, key="btn_obdelaj"
        ):
            if "prejem_drafts" not in st.session_state:
                st.session_state["prejem_drafts"] = {}

            prog = st.progress(0, text="Obdelujem …")
            for i, fname in enumerate(selected):
                prog.progress((i+1)/len(selected), text=f"Berem {fname} …")
                fdata = file_store[fname]
                media_map = {
                    "image/jpeg":"image/jpeg","image/jpg":"image/jpeg",
                    "image/png":"image/png","application/pdf":"application/pdf",
                }
                media_type = media_map.get(fdata["type"], "image/jpeg")

                parsed, err = _parse_claude(fdata["bytes"], media_type)
                if err or not parsed:
                    st.session_state["prejem_drafts"][fname] = {
                        "error": err or "AI ni vrnil podatkov", "header": {}, "rows": []
                    }
                    continue

                # Supplier
                sup_id, sup_name = _find_supplier(suppliers, parsed.get("supplier_name",""))
                parsed["supplier_id"]   = sup_id
                parsed["supplier_name"] = sup_name or parsed.get("supplier_name","")

                # Lot
                lot = _lot_number(parsed.get("supplier_name",""), parsed.get("invoice_date",""))
                parsed["lot_number"] = lot

                # Matching
                rows_matched = []
                for inv_item in parsed.get("items", []):
                    best, conf, reason, score = match_item(inv_item, items)
                    rows_matched.append({
                        "inv_name":          inv_item.get("name",""),
                        "item_id":           best["item_id"] if best else None,
                        "item_name":         best["name"]    if best else "",
                        "item_code":         best["code"]    if best else "",
                        "confidence":        conf,
                        "match_reason":      reason,
                        "match_score":       score,
                        "quantity":          float(inv_item.get("quantity") or 0),
                        "unit":              inv_item.get("unit","kg"),
                        "price":             float(inv_item.get("price") or 0),
                        "selling_price":     float(best["selling_price"]) if best else 0.0,
                        "batch_number":      lot,
                        "country_of_origin": inv_item.get("country_of_origin",""),
                        "tariff":            inv_item.get("tariff","") or (best["tariff"] if best else ""),
                        "fao_zone":          inv_item.get("fao_zone",""),
                    })

                st.session_state["prejem_drafts"][fname] = {
                    "error": None,
                    "header": parsed,
                    "rows":   rows_matched,
                }
            prog.empty()
            st.rerun()

    with col_reset:
        if st.button("↺ Počisti vse", use_container_width=True, key="btn_clear_all"):
            for k in ["prejem_file_store","prejem_drafts"]:
                st.session_state.pop(k, None)
            st.rerun()

    # ═══════════════════════════════════════════════════════════════════
    # KORAK 3: Pregled osnutkov
    # ═══════════════════════════════════════════════════════════════════
    drafts = st.session_state.get("prejem_drafts", {})
    if not drafts:
        return

    st.divider()
    st.subheader("3️⃣ Pregled in korekcija osnutkov")

    # Opcije za artikel dropdown
    item_map  = {f"({i['code']}) {i['name']}": i for i in items}
    item_opts = ["— izberi —"] + sorted(item_map.keys())
    sup_map   = {}
    for s in suppliers:
        sn = s.get("Name") or s.get("CompanyName") or ""
        si = s.get("SupplierId") or s.get("ID") or 0
        if sn: sup_map[sn] = si
    sup_names = sorted(sup_map.keys())

    all_valid = True  # za gumb prenos

    for fname, draft in drafts.items():
        # Napaka pri branju
        if draft.get("error"):
            st.error(f"❌ **{fname}**: {draft['error']}")
            all_valid = False
            continue

        header = draft["header"]
        rows   = draft["rows"]
        errors = _validate(header, rows)
        has_crit = _has_critical(errors)
        if has_crit:
            all_valid = False

        # Expander z ikono napake
        icon = "✅" if not errors else ("❌" if has_crit else "⚠️")
        with st.expander(
            f"{icon} **{fname}** — {header.get('supplier_name','?')} · "
            f"{header.get('invoice_date','?')} · {header.get('invoice_number','?')} "
            f"· {len(rows)} artikov",
            expanded=bool(errors)
        ):
            # Prikaz napak
            if errors:
                st.markdown("**Napake/opozorila:**")
                for typ, msg in errors:
                    st.write(f"{typ} {msg}")
                st.divider()

            # Header podatki
            c1, c2, c3 = st.columns(3)
            with c1:
                curr_sup = header.get("supplier_name","")
                sup_idx  = sup_names.index(curr_sup) if curr_sup in sup_names else 0
                sel_sup  = st.selectbox("Dobavitelj", sup_names, index=sup_idx, key=f"sup_{fname}")
                header["supplier_id"]   = sup_map.get(sel_sup, 0)
                header["supplier_name"] = sel_sup
            with c2:
                inv_date = st.text_input("Datum (YYYY-MM-DD)", value=header.get("invoice_date",""), key=f"date_{fname}")
                header["invoice_date"] = inv_date
                new_lot = _lot_number(sel_sup, inv_date)
                if new_lot != header.get("lot_number",""):
                    header["lot_number"] = new_lot
                    for row in rows: row["batch_number"] = new_lot
            with c3:
                inv_num = st.text_input("Številka dobavnice", value=header.get("invoice_number",""), key=f"num_{fname}")
                header["invoice_number"] = inv_num

            st.info(f"🏷️ Serija: **{header.get('lot_number','?')}**")

            # Artikli
            low_conf = sum(1 for r in rows if r["confidence"] == "🔴 nizka")
            if low_conf:
                st.warning(f"⚠️ {low_conf} artikov z nizkim zaupanjem — preverite!")

            for idx, row in enumerate(rows):
                conf_ico = {"🟢 visoka":"🟢","🟡 srednja":"🟡","🔴 nizka":"🔴"}.get(row["confidence"],"⚪")
                with st.expander(
                    f"{conf_ico} {idx+1}. `{row['inv_name']}` → **{row['item_name'] or '⚠️ ni določen'}**",
                    expanded=(not row.get("item_id") or row["confidence"]=="🔴 nizka")
                ):
                    st.caption(f"Ujemanje: {row['confidence']} · {row['match_reason']} · score={row['match_score']}")
                    curr_key = f"({row['item_code']}) {row['item_name']}" if row.get("item_code") else "— izberi —"
                    curr_idx = item_opts.index(curr_key) if curr_key in item_opts else 0
                    sel_art  = st.selectbox("Naš artikel", item_opts, index=curr_idx, key=f"art_{fname}_{idx}")
                    if sel_art and sel_art != "— izberi —" and sel_art in item_map:
                        si = item_map[sel_art]
                        row["item_id"]       = si["item_id"]
                        row["item_name"]     = si["name"]
                        row["item_code"]     = si["code"]
                        row["selling_price"] = si["selling_price"]
                        if not row.get("tariff"):    row["tariff"]  = si.get("tariff","")
                        if not row.get("country_of_origin"): row["country_of_origin"] = (si.get("country") or "")[:2]
                    else:
                        row["item_id"] = None

                    cc1,cc2,cc3,cc4 = st.columns(4)
                    with cc1:
                        row["quantity"] = st.number_input("Količina", value=float(row.get("quantity") or 0), min_value=0.0, step=0.001, format="%.3f", key=f"qty_{fname}_{idx}")
                        row["unit"]     = st.text_input("ME", value=row.get("unit","kg"), key=f"unit_{fname}_{idx}")
                    with cc2:
                        row["price"]         = st.number_input("Nab. cena €/kg", value=float(row.get("price") or 0), min_value=0.0, step=0.01, format="%.4f", key=f"price_{fname}_{idx}")
                        row["selling_price"] = st.number_input("Prod. cena €/kg", value=float(row.get("selling_price") or 0), min_value=0.0, step=0.01, format="%.4f", key=f"sell_{fname}_{idx}")
                    with cc3:
                        row["batch_number"]      = st.text_input("Serija / Lot", value=row.get("batch_number",""), key=f"batch_{fname}_{idx}")
                        row["country_of_origin"] = st.text_input("Država (2 črkoven)", value=row.get("country_of_origin",""), key=f"cntry_{fname}_{idx}")
                    with cc4:
                        row["tariff"]   = st.text_input("Carinska tarifa", value=row.get("tariff",""), key=f"tariff_{fname}_{idx}")
                        row["fao_zone"] = st.text_input("FAO cona", value=row.get("fao_zone",""), key=f"fao_{fname}_{idx}")

            # Predogled skupaj
            if rows:
                total_val = sum(float(r.get("quantity") or 0) * float(r.get("price") or 0) for r in rows)
                st.metric("Skupna nabavna vrednost", f"{total_val:.2f} €")

        # Shrani spremembe nazaj
        drafts[fname]["header"] = header
        drafts[fname]["rows"]   = rows

    st.session_state["prejem_drafts"] = drafts

    # ═══════════════════════════════════════════════════════════════════
    # KORAK 4: Prenos v Minimax
    # ═══════════════════════════════════════════════════════════════════
    st.divider()

    ready_count = sum(
        1 for d in drafts.values()
        if not d.get("error") and not _has_critical(_validate(d["header"], d["rows"]))
    )
    total_count = len([d for d in drafts.values() if not d.get("error")])

    if not all_valid:
        st.warning(f"⚠️ {total_count - ready_count} od {total_count} dokumentov ima kritične napake (❌). "
                   f"Popravite napake da aktivirate prenos.")

    if st.button(
        f"📤 Prenos osnutkov v Minimax ({ready_count}/{total_count})",
        type="primary",
        use_container_width=True,
        disabled=not all_valid,
        key="btn_prenos",
    ):
        cli = _get_client()
        saved, errors_prenos = [], []
        prog2 = st.progress(0, text="Prenašam …")
        items_to_send = [
            (fname, d) for fname, d in drafts.items()
            if not d.get("error") and not _has_critical(_validate(d["header"], d["rows"]))
        ]
        for i, (fname, draft) in enumerate(items_to_send):
            prog2.progress((i+1)/len(items_to_send), text=f"Prenašam {fname} …")
            try:
                result   = _create_pl(cli, wh_id, draft["header"], draft["rows"])
                entry_id = result.get("StockEntryId") or result.get("ID") or "?"
                saved.append(f"✅ **{fname}** → ID: {entry_id} · {draft['header'].get('supplier_name')} · {draft['header'].get('invoice_date')}")
                drafts.pop(fname, None)
            except Exception as e:
                errors_prenos.append(f"❌ **{fname}**: {e}")

        prog2.empty()
        for msg in saved:
            st.success(msg)
        for msg in errors_prenos:
            st.error(msg)

        if saved:
            st.session_state["prejem_drafts"] = drafts
            if not drafts:
                st.session_state.pop("prejem_file_store", None)
            st.balloons()
