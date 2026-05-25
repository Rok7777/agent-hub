"""
Tab: Prejem blaga
Skeniranje dobavnic dobavitelja → kreiranje P/L osnutka v Minimaxu (VP-CEN)
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

# Obvezna polja pred kreacijo osnutka
# ❌ = blokira kreacijo, ⚠️ = opozorilo (ne blokira)
REQUIRED_HEADER = [
    ("supplier_id",    "❌", "Dobavitelj ni določen ali ga ni v Minimaxu"),
    ("invoice_date",   "❌", "Datum dobavnice manjka"),
    ("invoice_number", "❌", "Številka dobavnice manjka"),
]
REQUIRED_ROW = [
    ("item_id",          "❌", "Artikel ni določen"),
    ("quantity",         "❌", "Količina mora biti > 0"),
    ("batch_number",     "❌", "Serija (lot) manjka"),
    ("price",            "⚠️", "Nabavna cena ni določena"),
    ("country_of_origin","⚠️", "Država porekla manjka"),
    ("tariff",           "⚠️", "Tarifa manjka"),
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
    """Generira lot: PREFIX + DDMMYY iz datuma dobavnice."""
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
    """Naloži vse artikle tipa Blago iz Minimaxa."""
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
            # Tarifa in poreklo sta v Intrastat sekciji
            intra = r.get("Intrastat") or {}
            result.append({
                "item_id":       r.get("ItemId"),
                "name":          r.get("Name", ""),
                "code":          r.get("Code", "") or r.get("Sifra", ""),
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


def _find_wh_id(warehouses: list, code: str) -> int:
    for wh in warehouses:
        if wh.get("Code", "") == code:
            return wh.get("WarehouseId") or wh.get("ID") or 0
    return 0


def _find_supplier(suppliers: list, name: str) -> tuple:
    """Vrne (supplier_id, supplier_name) za najboljše ujemanje."""
    name_up = name.upper()
    best_id, best_name, best_score = 0, "", 0
    for s in suppliers:
        s_name = (s.get("Name") or s.get("CompanyName") or "").upper()
        s_id   = s.get("SupplierId") or s.get("ID") or 0
        # Točno ujemanje
        if name_up == s_name:
            return s_id, s.get("Name") or s.get("CompanyName") or ""
        # Delno ujemanje — scoring
        score = 0
        for word in name_up.split():
            if len(word) > 3 and word in s_name:
                score += len(word)
        if score > best_score:
            best_score = score
            best_id    = s_id
            best_name  = s.get("Name") or s.get("CompanyName") or ""
    return best_id, best_name


# ─── Matching engine ──────────────────────────────────────────────────────────

_LATIN_RE  = re.compile(r'/([^/]+)/')
_SIZE_RE   = re.compile(r'(\d+)[–\-](\d+)\s*(g|kg)?', re.IGNORECASE)
_STATE_MAP = {
    'svež': 'svež', 'sveža': 'svež', 'sveže': 'svež', 'fresh': 'svež',
    'zamrznjen': 'zamrznjen', 'frozen': 'zamrznjen', 'congelato': 'zamrznjen',
    'odtaljen': 'odtaljen', 'thawed': 'odtaljen', 'scongelato': 'odtaljen',
}


def _latin(text: str) -> str:
    m = _LATIN_RE.search(text)
    return m.group(1).lower().strip() if m else ""


def _size(text: str):
    m = _SIZE_RE.search(text)
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    unit = (m.group(3) or "").lower()
    if unit == "kg":
        lo, hi = lo * 1000, hi * 1000
    return lo, hi


def _state(text: str) -> str:
    t = text.lower()
    for k, v in _STATE_MAP.items():
        if k in t:
            return v
    return ""


def match_item(inv_item: dict, our_items: list) -> tuple:
    """
    Poišče najboljši artikel iz Minimaxa za artikel z dobavnice.
    Vrne (item_dict | None, confidence_label, reason, score)

    Hierarhija ujemanja:
      1. Tarifa (8-mestna) — najmočnejši signal
      2. Latinsko ime iz opisa (/Sparus aurata/)
      3. Velikost ribe (g/kg range)
      4. Stanje (svež/zamrznjen/odtaljen)
      5. Država porekla
    """
    inv_name    = inv_item.get("name", "")
    inv_tariff  = (inv_item.get("tariff") or "").strip().replace(" ", "").replace(".", "")
    inv_latin   = (inv_item.get("latin_name") or "").lower().strip()
    inv_country = (inv_item.get("country_of_origin") or "").upper()[:2]
    inv_size    = _size(inv_name)
    inv_state   = _state(inv_name)

    best_item, best_score, best_reason = None, -1, ""

    for item in our_items:
        score   = 0
        reasons = []

        item_tariff  = (item.get("tariff") or "").strip().replace(" ", "").replace(".", "")
        item_latin   = _latin(item.get("description", ""))
        item_name    = item.get("name", "")
        item_country = (item.get("country") or "").upper()[:2]
        item_size    = _size(item_name)
        item_state   = _state(item_name)

        # 1. Tarifa — definitivni signal če je 8-mestna
        if inv_tariff and item_tariff:
            if inv_tariff[:8] == item_tariff[:8]:
                score += 60
                reasons.append("tarifa8✓")
            elif inv_tariff[:6] == item_tariff[:6]:
                score += 35
                reasons.append("tarifa6~")

        # 2. Latinsko ime
        if inv_latin and item_latin:
            if inv_latin == item_latin:
                score += 50
                reasons.append("latinski✓")
            elif inv_latin in item_latin or item_latin in inv_latin:
                score += 30
                reasons.append("latinski~")

        # 3. Velikost
        if inv_size and item_size:
            lo1, hi1 = inv_size
            lo2, hi2 = item_size
            if lo1 == lo2 and hi1 == hi2:
                score += 20
                reasons.append("velikost✓")
            elif abs(lo1 - lo2) < 300:
                score += 8
                reasons.append("velikost~")

        # 4. Stanje
        if inv_state and item_state:
            if inv_state == item_state:
                score += 15
                reasons.append("stanje✓")
            else:
                score -= 15  # Napačno stanje je disqualifier

        # 5. Država porekla
        if inv_country and item_country:
            if inv_country == item_country:
                score += 10
                reasons.append("država✓")

        if score > best_score:
            best_score  = score
            best_item   = item
            best_reason = ", ".join(reasons)

    if best_score >= 60:
        confidence = "🟢 visoka"
    elif best_score >= 30:
        confidence = "🟡 srednja"
    else:
        confidence = "🔴 nizka"

    return best_item, confidence, best_reason, best_score


# ─── Claude Vision ────────────────────────────────────────────────────────────

_PARSE_PROMPT = """Analiziraj to dobavnico / račun dobavitelja za ribe in morske sadeže.
Vrni SAMO čist JSON brez markdown backticks, brez komentarjev, brez dodatnega besedila.

{
  "supplier_name": "točno ime dobavitelja kot piše na dokumentu",
  "invoice_number": "številka računa ali dobavnice",
  "invoice_date": "YYYY-MM-DD",
  "items": [
    {
      "name": "naziv artikla kot piše na dobavnici",
      "latin_name": "latinsko ime vrste (Sparus aurata, Salmo salar...) če je navedeno",
      "quantity": 0.000,
      "unit": "kg",
      "price": 0.00,
      "country_of_origin": "2-črkovna ISO koda (HR, IT, NO, PT, ES, FR...)",
      "tariff": "carinska tarifa brez presledkov (npr. 03028530)",
      "fao_zone": "FAO območje če je navedeno (npr. FAO 37.2.1)",
      "notes": ""
    }
  ]
}

Pravila:
- invoice_date: vedno ISO format YYYY-MM-DD
- quantity: samo decimalno število (ne besede)
- price: nabavna cena na enoto mere brez valute
- country_of_origin: SAMO 2-črkovna koda (HR, IT, NO, PT, ES, FR, DE, GB, MA...)
- tariff: samo cifre brez pik in presledkov, ali prazen string
- Če podatka ni, vrni prazen string "" ali 0
"""


def _parse_invoice_claude(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Pokliče Claude Vision za parsanje dobavnice. Vrne dict ali {}."""
    try:
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY", "")
        if not api_key:
            st.error("⚠️ ANTHROPIC_API_KEY ni nastavljen v st.secrets! "
                     "Dodajte ključ in ponovite.")
            return {}

        client  = anthropic.Anthropic(api_key=api_key)
        b64     = base64.b64encode(image_bytes).decode()

        # PDF → document type, slike → image type
        if media_type == "application/pdf":
            content_block = {
                "type": "document",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            }
        else:
            content_block = {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            }

        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [content_block, {"type": "text", "text": _PARSE_PROMPT}],
            }],
        )

        raw = response.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)

    except json.JSONDecodeError as e:
        st.error(f"Napaka pri parsanju odgovora AI: {e}")
        return {}
    except Exception as e:
        st.error(f"Napaka pri klicu Claude API: {e}")
        return {}


# ─── Validacija ───────────────────────────────────────────────────────────────

def _validate(header: dict, rows: list) -> list:
    """Vrne seznam (tip, sporočilo) napak. tip = '❌' ali '⚠️'."""
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
                    errors.append((typ, f"Vrstica {i} ({row.get('item_name','?')}): {msg}"))
            elif not val:
                errors.append((typ, f"Vrstica {i} ({row.get('item_name','?')}): {msg}"))

    return errors


# ─── Kreiranje P/L ────────────────────────────────────────────────────────────

def _create_pl(cli: MinimaxClient, wh_id: int, header: dict, rows: list) -> dict:
    """Kreira P/L osnutek (StockEntryType=P, Subtype=L) v Minimaxu."""
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

    # ── Sidebar: credentials ──────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Nastavitve API")
        with st.expander("Minimax dostop", expanded=True):
            st.caption("Podatki odjemalca:")
            st.session_state["client_id"]     = st.text_input("Client ID",        value=_secret("MINIMAX_CLIENT_ID", ""))
            st.session_state["client_secret"] = st.text_input("Client Secret",    value=_secret("MINIMAX_CLIENT_SECRET", ""), type="password")
            st.caption("Podatki uporabnika:")
            st.session_state["username"]      = st.text_input("Uporabniško ime",  value=_secret("MINIMAX_USERNAME", ""))
            st.session_state["password"]      = st.text_input("Geslo aplikacije", value=_secret("MINIMAX_PASSWORD", ""), type="password")
            st.caption("Organizacija:")
            st.session_state["org_id"]        = st.text_input("ID organizacije",  value=_secret("MINIMAX_ORG_ID", "171038"))

        st.divider()
        if st.button("🔄 Naloži podatke iz Minimaxa", use_container_width=True, key="btn_load_prejem"):
            st.session_state["prejem_trigger_load"] = True
        if st.button("🗑️ Počisti cache", use_container_width=True, key="btn_clear_prejem"):
            _load_items.clear()
            _load_warehouses.clear()
            _load_suppliers.clear()
            for k in ["prejem_items", "prejem_suppliers", "prejem_wh_id", "prejem_data_ok"]:
                st.session_state.pop(k, None)
            st.sidebar.success("Cache počiščen!")

    # ── Nalaganje podatkov ────────────────────────────────────────────────────
    if st.session_state.get("prejem_trigger_load"):
        st.session_state.pop("prejem_trigger_load")
        username = st.session_state.get("username", "")
        org_id   = st.session_state.get("org_id", "171038")
        with st.spinner("Nalagam artikle, dobavitelje in skladišča iz Minimaxa …"):
            try:
                items      = _load_items(username, org_id)
                warehouses = _load_warehouses(username, org_id)
                suppliers  = _load_suppliers(username, org_id)
                wh_id      = _find_wh_id(warehouses, VP_CEN_CODE)
                st.session_state["prejem_items"]    = items
                st.session_state["prejem_suppliers"] = suppliers
                st.session_state["prejem_wh_id"]    = wh_id
                st.session_state["prejem_data_ok"]  = True
                st.success(
                    f"✅ {len(items)} artiklov · {len(suppliers)} dobaviteljev · "
                    f"VP-CEN ID = {wh_id if wh_id else '⚠️ NI NAJDEN'}"
                )
            except Exception as e:
                st.error(f"Napaka pri nalaganju: {e}")
                st.code(traceback.format_exc())

    if not st.session_state.get("prejem_data_ok"):
        st.info("👈 Kliknite **Naloži podatke iz Minimaxa** v stranski vrstici za začetek.")
        return

    items     = st.session_state["prejem_items"]
    suppliers = st.session_state["prejem_suppliers"]
    wh_id     = st.session_state["prejem_wh_id"]

    if not wh_id:
        st.error("⚠️ Veleprodajno skladišče VP-CEN ni najdeno v Minimaxu! Preverite šifro.")
        return

    # ── KORAK 1: Upload ───────────────────────────────────────────────────────
    st.subheader("1️⃣ Naloži dobavnico dobavitelja")
    uploaded = st.file_uploader(
        "Dobavnica — skenirana slika ali PDF",
        type=["jpg", "jpeg", "png", "pdf"],
        key="prejem_upload",
    )

    col_parse, col_reset = st.columns([2, 1])
    with col_parse:
        parse_disabled = uploaded is None
        parse_btn = st.button(
            "🤖 Preberi dobavnico z AI",
            type="primary",
            use_container_width=True,
            disabled=parse_disabled,
            key="btn_parse",
        )
    with col_reset:
        if st.button("↺ Začni znova", use_container_width=True, key="btn_reset"):
            for k in ["prejem_parsed", "prejem_rows"]:
                st.session_state.pop(k, None)
            st.rerun()

    if parse_btn and uploaded:
        with st.spinner("Claude bere dobavnico … (5–15 sekund)"):
            img_bytes = uploaded.read()
            media_map = {
                "image/jpeg": "image/jpeg",
                "image/jpg":  "image/jpeg",
                "image/png":  "image/png",
                "application/pdf": "application/pdf",
            }
            media_type = media_map.get(uploaded.type, "image/jpeg")
            parsed = _parse_invoice_claude(img_bytes, media_type)

        if parsed:
            # Supplier lookup
            sup_id, sup_name = _find_supplier(suppliers, parsed.get("supplier_name", ""))
            parsed["supplier_id"]   = sup_id
            parsed["supplier_name"] = sup_name or parsed.get("supplier_name", "")

            # Lot generacija
            lot = _lot_number(parsed.get("supplier_name", ""), parsed.get("invoice_date", ""))
            parsed["lot_number"] = lot

            # Matching
            matched_rows = []
            for inv_item in parsed.get("items", []):
                best, conf, reason, score = match_item(inv_item, items)
                matched_rows.append({
                    "inv_name":          inv_item.get("name", ""),
                    "item_id":           best["item_id"] if best else None,
                    "item_name":         best["name"]    if best else "",
                    "item_code":         best["code"]    if best else "",
                    "confidence":        conf,
                    "match_reason":      reason,
                    "match_score":       score,
                    "quantity":          float(inv_item.get("quantity") or 0),
                    "unit":              inv_item.get("unit", "kg"),
                    "price":             float(inv_item.get("price") or 0),
                    "selling_price":     float(best["selling_price"]) if best else 0.0,
                    "batch_number":      lot,
                    "country_of_origin": inv_item.get("country_of_origin", ""),
                    "tariff":            inv_item.get("tariff", "")
                                        or (best["tariff"] if best else ""),
                    "fao_zone":          inv_item.get("fao_zone", ""),
                })

            st.session_state["prejem_parsed"] = parsed
            st.session_state["prejem_rows"]   = matched_rows
            st.rerun()

    # ── KORAK 2: Pregled ──────────────────────────────────────────────────────
    parsed = st.session_state.get("prejem_parsed")
    rows   = st.session_state.get("prejem_rows", [])
    if not parsed:
        return

    st.divider()
    st.subheader("2️⃣ Pregled in korekcija podatkov")

    # Header
    col1, col2, col3 = st.columns(3)

    # Supplier dropdown
    sup_map   = {}
    for s in suppliers:
        sn = s.get("Name") or s.get("CompanyName") or ""
        si = s.get("SupplierId") or s.get("ID") or 0
        if sn:
            sup_map[sn] = si
    sup_names = sorted(sup_map.keys())

    with col1:
        curr_sup  = parsed.get("supplier_name", "")
        sup_idx   = sup_names.index(curr_sup) if curr_sup in sup_names else 0
        sel_sup   = st.selectbox("Dobavitelj", sup_names, index=sup_idx, key="sel_sup_prejem")
        parsed["supplier_id"]   = sup_map.get(sel_sup, 0)
        parsed["supplier_name"] = sel_sup

    with col2:
        inv_date = st.text_input("Datum dobavnice (YYYY-MM-DD)",
                                  value=parsed.get("invoice_date", ""), key="inp_date")
        parsed["invoice_date"] = inv_date
        # Posodobi lot če se datum ali dobavitelj spremenita
        new_lot = _lot_number(sel_sup, inv_date)
        if new_lot != parsed.get("lot_number", ""):
            parsed["lot_number"] = new_lot
            for row in rows:
                row["batch_number"] = new_lot

    with col3:
        inv_num = st.text_input("Številka dobavnice",
                                 value=parsed.get("invoice_number", ""), key="inp_invnum")
        parsed["invoice_number"] = inv_num

    st.info(f"🏷️ Generirana serija (lot): **{parsed.get('lot_number', '?')}**  "
            f"&nbsp;&nbsp;·&nbsp;&nbsp; Skladišče: **VP-CEN** (ID: {wh_id})")

    # ── Tabela artiklov ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("##### 🐟 Artikli dobavnice")

    # Opcije za dropdown artiklov
    item_map  = {f"({i['code']}) {i['name']}": i for i in items}
    item_opts = ["— izberi —"] + sorted(item_map.keys())

    low_conf_count = sum(1 for r in rows if r["confidence"] == "🔴 nizka")
    if low_conf_count:
        st.warning(f"⚠️ {low_conf_count} artikov z nizkim zaupanjem ujemanja — preverite ročno!")

    for idx, row in enumerate(rows):
        conf_color = {"🟢 visoka": "🟢", "🟡 srednja": "🟡", "🔴 nizka": "🔴"}.get(row["confidence"], "⚪")
        with st.expander(
            f"{conf_color} **{idx+1}.** `{row['inv_name']}` → "
            f"**{row['item_name'] or '⚠️ ni določen'}**",
            expanded=(row["confidence"] == "🔴 nizka" or not row["item_id"])
        ):
            st.caption(f"Ujemanje: {row['confidence']} · Razlog: {row['match_reason'] or 'ni'} · Score: {row['match_score']}")

            # Artikel dropdown
            curr_key = f"({row['item_code']}) {row['item_name']}" if row.get("item_code") else "— izberi —"
            curr_idx = item_opts.index(curr_key) if curr_key in item_opts else 0
            sel_art  = st.selectbox("Naš artikel v Minimaxu", item_opts,
                                     index=curr_idx, key=f"art_{idx}")
            if sel_art and sel_art != "— izberi —" and sel_art in item_map:
                sel_i = item_map[sel_art]
                row["item_id"]      = sel_i["item_id"]
                row["item_name"]    = sel_i["name"]
                row["item_code"]    = sel_i["code"]
                row["selling_price"] = sel_i["selling_price"]
                if not row.get("tariff"):
                    row["tariff"] = sel_i.get("tariff", "")
                if not row.get("country_of_origin"):
                    row["country_of_origin"] = (sel_i.get("country") or "")[:2]
            else:
                row["item_id"] = None

            # Detajlni podatki
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                row["quantity"] = st.number_input(
                    "Količina", value=float(row.get("quantity") or 0),
                    min_value=0.0, step=0.001, format="%.3f", key=f"qty_{idx}")
                row["unit"] = st.text_input("ME", value=row.get("unit", "kg"), key=f"unit_{idx}")
            with c2:
                row["price"] = st.number_input(
                    "Nabavna cena (€/kg)", value=float(row.get("price") or 0),
                    min_value=0.0, step=0.01, format="%.4f", key=f"price_{idx}")
                row["selling_price"] = st.number_input(
                    "Prodajna cena (€/kg)", value=float(row.get("selling_price") or 0),
                    min_value=0.0, step=0.01, format="%.4f", key=f"sell_{idx}")
            with c3:
                row["batch_number"] = st.text_input(
                    "Serija / Lot", value=row.get("batch_number", ""), key=f"batch_{idx}")
                row["country_of_origin"] = st.text_input(
                    "Država porekla (2 črkoven)", value=row.get("country_of_origin", ""),
                    key=f"country_{idx}")
            with c4:
                row["tariff"] = st.text_input(
                    "Carinska tarifa", value=row.get("tariff", ""), key=f"tariff_{idx}")
                row["fao_zone"] = st.text_input(
                    "FAO cona", value=row.get("fao_zone", ""), key=f"fao_{idx}")

    st.session_state["prejem_rows"] = rows

    # ── KORAK 3: Validacija ───────────────────────────────────────────────────
    st.divider()
    st.subheader("3️⃣ Validacija in kreiranje osnutka")

    errors = _validate(parsed, rows)

    if errors:
        critical = [e for e in errors if e[0] == "❌"]
        warnings = [e for e in errors if e[0] == "⚠️"]
        with st.expander(
            f"{'❌' if critical else '⚠️'} {len(errors)} opozoril/napak pred potrditvijo",
            expanded=True
        ):
            for typ, msg in errors:
                st.write(f"{typ} {msg}")
        if critical:
            st.error(f"Popravite {len(critical)} kritičnih napak (❌) preden kreirate osnutek.")

    # Preview tabela
    if rows:
        with st.expander("📋 Predogled P/L dokumenta", expanded=False):
            preview_data = []
            for r in rows:
                preview_data.append({
                    "Artikel":      r.get("item_name", "⚠️ ni določen"),
                    "Šifra":        r.get("item_code", ""),
                    "Količina":     r.get("quantity", 0),
                    "ME":           r.get("unit", "kg"),
                    "Nab. cena":    r.get("price", 0),
                    "Prod. cena":   r.get("selling_price", 0),
                    "Serija":       r.get("batch_number", ""),
                    "Država":       r.get("country_of_origin", ""),
                    "Tarifa":       r.get("tariff", ""),
                    "FAO":          r.get("fao_zone", ""),
                })
            df = pd.DataFrame(preview_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
            total_val = sum(
                float(r.get("quantity") or 0) * float(r.get("price") or 0)
                for r in rows
            )
            st.metric("Skupna nabavna vrednost", f"{total_val:.2f} €")

    # Kreacija
    can_create = not any(e[0] == "❌" for e in errors)
    col_ok, col_cancel = st.columns(2)

    with col_ok:
        if st.button(
            f"📥 Kreiraj P/L osnutek v Minimaxu ({len(rows)} artikov)",
            type="primary",
            use_container_width=True,
            disabled=not can_create,
            key="btn_create_pl",
        ):
            with st.spinner("Kreiram P/L osnutek v Minimaxu …"):
                try:
                    cli    = _get_client()
                    result = _create_pl(cli, wh_id, parsed, rows)
                    entry_id = result.get("StockEntryId") or result.get("ID") or "?"
                    st.success(f"✅ P/L osnutek kreiran! ID: **{entry_id}**  "
                               f"·  Dobavitelj: {parsed.get('supplier_name')}  "
                               f"·  Datum: {parsed.get('invoice_date')}")
                    # Počisti stanje
                    st.session_state.pop("prejem_parsed", None)
                    st.session_state.pop("prejem_rows", None)
                    st.balloons()
                except Exception as e:
                    st.error(f"Napaka pri kreiranju: {e}")
                    st.code(traceback.format_exc())

    with col_cancel:
        if st.button("✖ Zavrzi in začni znova", use_container_width=True, key="btn_cancel_pl"):
            st.session_state.pop("prejem_parsed", None)
            st.session_state.pop("prejem_rows", None)
            st.rerun()
