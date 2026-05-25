"""
Tab: Prejem blaga
Tok: Naloži dobavnice → AI prebere → pregled v Streamlitu → pošlji v Minimax
Minimax se pokliče SAMO pri prenosu osnutkov.
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
    ("supplier_name",  "❌", "Dobavitelj ni vpisan"),
    ("invoice_date",   "❌", "Datum dobavnice manjka"),
    ("invoice_number", "❌", "Številka dobavnice manjka"),
]
REQUIRED_ROW = [
    ("item_code",         "❌", "Šifra artikla manjka"),
    ("quantity",          "❌", "Količina mora biti > 0"),
    ("batch_number",      "❌", "Serija (lot) manjka"),
    ("price",             "⚠️", "Nabavna cena ni določena"),
    ("country_of_origin", "⚠️", "Država porekla manjka"),
    ("tariff",            "⚠️", "Carinska tarifa manjka"),
]

# ─── Pomožne funkcije ─────────────────────────────────────────────────────────

def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return default

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
  "items": [
    {
      "name": "naziv artikla kot piše na dobavnici",
      "latin_name": "latinsko ime vrste če je navedeno",
      "quantity": 0.000,
      "unit": "kg",
      "price": 0.00,
      "country_of_origin": "2-črkovna ISO koda (HR, IT, NO, PT, ES...)",
      "tariff": "carinska tarifa samo cifre brez presledkov",
      "fao_zone": "FAO cona če je navedena",
      "notes": ""
    }
  ]
}

Pravila:
- invoice_date: YYYY-MM-DD
- quantity: samo decimalno število
- price: nabavna cena na enoto mere
- country_of_origin: SAMO 2 črkovna koda
- tariff: samo cifre, brez pik in presledkov
- Manjkajoči podatki: prazen string ali 0"""

def _parse_claude(image_bytes: bytes, media_type: str = "image/jpeg"):
    try:
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {}, "ANTHROPIC_API_KEY ni v st.secrets"
        client = anthropic.Anthropic(api_key=api_key)
        b64    = base64.b64encode(image_bytes).decode()
        if media_type == "application/pdf":
            block = {"type": "document", "source": {"type": "base64", "media_type": media_type, "data": b64}}
        else:
            block = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}
        resp = client.messages.create(
            model="claude-opus-4-5", max_tokens=2048,
            messages=[{"role": "user", "content": [block, {"type": "text", "text": _PARSE_PROMPT}]}],
        )
        raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return {}, f"JSON napaka: {e}"
    except Exception as e:
        return {}, str(e)

# ─── Validacija ───────────────────────────────────────────────────────────────

def _validate(header: dict, rows: list) -> list:
    errors = []
    for field, typ, msg in REQUIRED_HEADER:
        val = header.get(field)
        if not val:
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

def _has_critical(errors: list) -> bool:
    return any(t == "❌" for t, _ in errors)

# ─── Prenos v Minimax ─────────────────────────────────────────────────────────

def _get_item_id_by_code(cli: MinimaxClient, code: str) -> int:
    """Poišče item ID po šifri — kliče se samo pri prenosu."""
    try:
        data = cli._get("/items", params={"Code": code, "CurrentPage": 1, "PageSize": 5})
        rows = data.get("Rows", [])
        for r in rows:
            if r.get("Code", "").upper() == code.upper():
                return r.get("ItemId") or 0
    except Exception:
        pass
    return 0

def _get_wh_id(cli: MinimaxClient) -> int:
    """Poišče warehouse ID za VP-CEN — kliče se samo pri prenosu."""
    try:
        warehouses = cli.get_warehouses()
        for wh in warehouses:
            if wh.get("Code", "") == VP_CEN_CODE:
                return wh.get("WarehouseId") or wh.get("ID") or 0
    except Exception:
        pass
    return 0

def _get_supplier_id(cli: MinimaxClient, name: str) -> int:
    """Poišče supplier ID — kliče se samo pri prenosu."""
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
            if len(rows) < 100:
                break
            page += 1
    except Exception:
        pass
    return 0

def _send_to_minimax(header: dict, rows: list) -> tuple:
    """Kreira P/L osnutek. Vrne (entry_id, error_msg)."""
    try:
        cli   = _get_client()
        wh_id = _get_wh_id(cli)
        if not wh_id:
            return None, f"Skladišče VP-CEN ni najdeno"

        sup_id = _get_supplier_id(cli, header.get("supplier_name", ""))
        if not sup_id:
            return None, f"Dobavitelj '{header.get('supplier_name')}' ni najden v Minimaxu"

        stock_rows = []
        for row in rows:
            item_id = _get_item_id_by_code(cli, row.get("item_code", ""))
            if not item_id:
                return None, f"Artikel s šifro '{row.get('item_code')}' ni najden v Minimaxu"
            sr = {
                "Item":              {"ID": item_id},
                "Quantity":          float(row.get("quantity") or 0),
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
            "Supplier":          {"ID": sup_id},
            "WarehouseTo":       {"ID": wh_id},
            "StockEntryRows":    stock_rows,
        }
        result   = cli._post("/stockentry", body)
        entry_id = result.get("StockEntryId") or result.get("ID") or "?"
        return entry_id, None
    except Exception as e:
        return None, str(e)

# ─── RENDER ───────────────────────────────────────────────────────────────────

def render():
    st.caption("Skeniranje dobavnic dobavitelja → P/L osnutek v Veleprodajnem skladišču (VP-CEN)")

    # Sidebar — samo credentials
    with st.sidebar:
        st.header("⚙️ Nastavitve")
        with st.expander("Minimax dostop", expanded=False):
            st.session_state["client_id"]     = st.text_input("Client ID",        value=_secret("MINIMAX_CLIENT_ID", ""))
            st.session_state["client_secret"] = st.text_input("Client Secret",    value=_secret("MINIMAX_CLIENT_SECRET", ""), type="password")
            st.session_state["username"]      = st.text_input("Uporabniško ime",  value=_secret("MINIMAX_USERNAME", ""))
            st.session_state["password"]      = st.text_input("Geslo aplikacije", value=_secret("MINIMAX_PASSWORD", ""), type="password")
            st.session_state["org_id"]        = st.text_input("ID organizacije",  value=_secret("MINIMAX_ORG_ID", "171038"))
        if st.button("↺ Začni znova", use_container_width=True, key="btn_sidebar_reset"):
            for k in ["prejem_file_store", "prejem_drafts"]:
                st.session_state.pop(k, None)
            st.rerun()

    # ═══════════════════════════════════════════════════════════
    # KORAK 1: Naloži dobavnice
    # ═══════════════════════════════════════════════════════════
    st.subheader("1️⃣ Naloži dobavnice")

    uploaded_files = st.file_uploader(
        "Izberite eno ali več dobavnic (slike ali PDF)",
        type=["jpg", "jpeg", "png", "pdf"],
        accept_multiple_files=True,
        key="prejem_uploader",
        label_visibility="collapsed",
    )

    # Shrani bytes v session_state
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

    # ═══════════════════════════════════════════════════════════
    # KORAK 2: Izbor in obdelava z AI
    # ═══════════════════════════════════════════════════════════
    st.divider()
    st.subheader("2️⃣ Izberite dokumente za obdelavo")

    drafts = st.session_state.get("prejem_drafts", {})

    selected = []
    for fname in file_store:
        is_done = fname in drafts
        label   = f"{'✅' if is_done else '📄'} {fname}"
        if st.checkbox(label, value=not is_done, key=f"chk_{fname}"):
            selected.append(fname)

    col_obdelaj, col_pocisti = st.columns([2, 1])
    with col_obdelaj:
        if st.button(
            f"🤖 Obdelaj z AI ({len(selected)} dok.)",
            type="primary", use_container_width=True,
            disabled=(len(selected) == 0), key="btn_obdelaj",
        ):
            if "prejem_drafts" not in st.session_state:
                st.session_state["prejem_drafts"] = {}

            prog = st.progress(0)
            for i, fname in enumerate(selected):
                prog.progress((i + 1) / len(selected), text=f"Berem {fname} …")
                fdata = file_store[fname]
                media_map = {
                    "image/jpeg": "image/jpeg", "image/jpg": "image/jpeg",
                    "image/png": "image/png", "application/pdf": "application/pdf",
                }
                mtype  = media_map.get(fdata["type"], "image/jpeg")
                parsed, err = _parse_claude(fdata["bytes"], mtype)

                if err or not parsed:
                    st.session_state["prejem_drafts"][fname] = {
                        "parse_error": err or "AI ni vrnil podatkov",
                        "header": {}, "rows": [],
                    }
                    continue

                lot  = _lot_number(parsed.get("supplier_name", ""), parsed.get("invoice_date", ""))
                rows = []
                for item in parsed.get("items", []):
                    rows.append({
                        "inv_name":          item.get("name", ""),
                        "item_code":         "",            # user bo vpisal šifro
                        "quantity":          float(item.get("quantity") or 0),
                        "unit":              item.get("unit", "kg"),
                        "price":             float(item.get("price") or 0),
                        "selling_price":     0.0,
                        "batch_number":      lot,
                        "country_of_origin": item.get("country_of_origin", ""),
                        "tariff":            item.get("tariff", ""),
                        "fao_zone":          item.get("fao_zone", ""),
                        "latin_name":        item.get("latin_name", ""),
                    })

                st.session_state["prejem_drafts"][fname] = {
                    "parse_error": None,
                    "header": {
                        "supplier_name":  parsed.get("supplier_name", ""),
                        "invoice_number": parsed.get("invoice_number", ""),
                        "invoice_date":   parsed.get("invoice_date", ""),
                        "lot_number":     lot,
                    },
                    "rows": rows,
                }

            prog.empty()
            st.rerun()

    with col_pocisti:
        if st.button("↺ Počisti vse", use_container_width=True, key="btn_reset_main"):
            for k in ["prejem_file_store", "prejem_drafts"]:
                st.session_state.pop(k, None)
            st.rerun()

    drafts = st.session_state.get("prejem_drafts", {})
    if not drafts:
        return

    # ═══════════════════════════════════════════════════════════
    # KORAK 3: Pregled in korekcija osnutkov
    # ═══════════════════════════════════════════════════════════
    st.divider()
    st.subheader("3️⃣ Pregled in korekcija osnutkov")

    all_valid = True

    for fname, draft in drafts.items():

        if draft.get("parse_error"):
            st.error(f"❌ **{fname}**: {draft['parse_error']}")
            all_valid = False
            continue

        header = draft["header"]
        rows   = draft["rows"]
        errors = _validate(header, rows)
        crit   = _has_critical(errors)
        if crit:
            all_valid = False

        icon = "✅" if not errors else ("❌" if crit else "⚠️")
        with st.expander(
            f"{icon} **{fname}** — "
            f"{header.get('supplier_name') or '?'} · "
            f"{header.get('invoice_date') or '?'} · "
            f"#{header.get('invoice_number') or '?'} · "
            f"{len(rows)} artikov",
            expanded=bool(errors),
        ):
            # Napake
            if errors:
                for typ, msg in errors:
                    st.write(f"{typ} {msg}")
                st.divider()

            # Header
            c1, c2, c3 = st.columns(3)
            with c1:
                header["supplier_name"]  = st.text_input("Dobavitelj", value=header.get("supplier_name", ""),  key=f"sup_{fname}")
            with c2:
                new_date = st.text_input("Datum (YYYY-MM-DD)", value=header.get("invoice_date", ""), key=f"dt_{fname}")
                if new_date != header.get("invoice_date", ""):
                    header["invoice_date"] = new_date
                    new_lot = _lot_number(header.get("supplier_name", ""), new_date)
                    header["lot_number"] = new_lot
                    for row in rows:
                        row["batch_number"] = new_lot
                else:
                    header["invoice_date"] = new_date
            with c3:
                header["invoice_number"] = st.text_input("Številka dobavnice", value=header.get("invoice_number", ""), key=f"num_{fname}")

            st.info(f"🏷️ Serija: **{header.get('lot_number', '?')}**  ·  Skladišče: **VP-CEN**")

            # Artikli
            st.markdown("**Artikli:**")
            for idx, row in enumerate(rows):
                with st.expander(
                    f"{'❌' if not row.get('item_code') else '✅'} "
                    f"**{idx+1}.** {row['inv_name']}"
                    + (f" — šifra: `{row['item_code']}`" if row.get('item_code') else " — ⚠️ šifra manjka"),
                    expanded=not row.get("item_code"),
                ):
                    if row.get("latin_name"):
                        st.caption(f"🔬 Latinsko ime: *{row['latin_name']}*")

                    cc1, cc2, cc3, cc4 = st.columns(4)
                    with cc1:
                        row["item_code"] = st.text_input(
                            "Minimax šifra ⚠️", value=row.get("item_code", ""),
                            key=f"code_{fname}_{idx}",
                            help="Vnesite šifro artikla iz Minimaxa (npr. ORASH0800)"
                        )
                        row["quantity"] = st.number_input(
                            "Količina", value=float(row.get("quantity") or 0),
                            min_value=0.0, step=0.001, format="%.3f", key=f"qty_{fname}_{idx}"
                        )
                    with cc2:
                        row["unit"]  = st.text_input("ME", value=row.get("unit", "kg"), key=f"unit_{fname}_{idx}")
                        row["price"] = st.number_input(
                            "Nab. cena €", value=float(row.get("price") or 0),
                            min_value=0.0, step=0.01, format="%.4f", key=f"price_{fname}_{idx}"
                        )
                    with cc3:
                        row["selling_price"] = st.number_input(
                            "Prod. cena €", value=float(row.get("selling_price") or 0),
                            min_value=0.0, step=0.01, format="%.4f", key=f"sell_{fname}_{idx}"
                        )
                        row["batch_number"] = st.text_input(
                            "Serija / Lot", value=row.get("batch_number", ""), key=f"batch_{fname}_{idx}"
                        )
                    with cc4:
                        row["country_of_origin"] = st.text_input(
                            "Država (2 črkoven)", value=row.get("country_of_origin", ""), key=f"cntry_{fname}_{idx}"
                        )
                        row["tariff"] = st.text_input(
                            "Carinska tarifa", value=row.get("tariff", ""), key=f"tariff_{fname}_{idx}"
                        )

            # Skupna vrednost
            if rows:
                total = sum(float(r.get("quantity") or 0) * float(r.get("price") or 0) for r in rows)
                st.metric("Skupna nabavna vrednost", f"{total:.2f} €")

        drafts[fname]["header"] = header
        drafts[fname]["rows"]   = rows

    st.session_state["prejem_drafts"] = drafts

    # ═══════════════════════════════════════════════════════════
    # KORAK 4: Prenos v Minimax
    # ═══════════════════════════════════════════════════════════
    st.divider()

    ready = [
        fname for fname, d in drafts.items()
        if not d.get("parse_error")
        and not _has_critical(_validate(d["header"], d["rows"]))
    ]
    total_docs = len([d for d in drafts.values() if not d.get("parse_error")])

    if not all_valid:
        st.warning(
            f"⚠️ {total_docs - len(ready)} od {total_docs} dokumentov ima kritične napake (❌). "
            "Popravite napake da aktivirate prenos v Minimax."
        )

    if st.button(
        f"📤 Prenos osnutkov v Minimax  ({len(ready)} / {total_docs})",
        type="primary",
        use_container_width=True,
        disabled=not all_valid,
        key="btn_prenos",
    ):
        prog = st.progress(0)
        for i, fname in enumerate(ready):
            prog.progress((i + 1) / len(ready), text=f"Prenašam {fname} …")
            d = drafts[fname]
            entry_id, err = _send_to_minimax(d["header"], d["rows"])
            if err:
                st.error(f"❌ **{fname}**: {err}")
            else:
                st.success(
                    f"✅ **{fname}** → ID: {entry_id} · "
                    f"{d['header'].get('supplier_name')} · "
                    f"{d['header'].get('invoice_date')}"
                )
                drafts.pop(fname, None)

        prog.empty()
        st.session_state["prejem_drafts"] = drafts
        if not drafts:
            st.session_state.pop("prejem_file_store", None)
        if any(not d.get("parse_error") for d in drafts.values()):
            pass
        else:
            st.balloons()
