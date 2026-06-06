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

# ─── Poti do datotek ─────────────────────────────────────────────────────────
import pathlib as _pathlib
_DATA_DIR     = _pathlib.Path(__import__("os").environ.get("DATA_DIR", str(_pathlib.Path(__file__).parent)))
DRAFTS_FILE   = str(_DATA_DIR / "prejem_osnutki.json")
FILES_FILE    = str(_DATA_DIR / "prejem_files.json")
PRICES_FILE   = str(_DATA_DIR / "prejem_cene.json")
MAPPINGS_FILE = str(_DATA_DIR / "prejem_mappings.json")

# ─── Konstante ────────────────────────────────────────────────────────────────

# Intrastat podatki po dobaviteljih — dopolniti sproti
SUPPLIER_INTRASTAT = {
    "LIBO":            {"country_dispatch": "SI", "transaction": "11", "delivery": "CPT", "location": "1", "transport": "3"},
    "ALEMAR":          {"country_dispatch": "IT", "transaction": "11", "delivery": "CIF", "location": "1", "transport": "3"},
    "CERKVENIK":       {"country_dispatch": "SI", "transaction": "11", "delivery": "CPT", "location": "1", "transport": "3"},
    "ORADA ADRIATIC":  {"country_dispatch": "HR", "transaction": "11", "delivery": "CPT", "location": "1", "transport": "3"},
    "FIORITAL":        {"country_dispatch": "IT", "transaction": "11", "delivery": "CIF", "location": "1", "transport": "3"},
    "KVIBO":           {"country_dispatch": "SI", "transaction": "11", "delivery": "CPT", "location": "1", "transport": "3"},
    "FORMIO":          {"country_dispatch": "SI", "transaction": "11", "delivery": "CIF", "location": "1", "transport": "3"},
    "COST IN":         {"country_dispatch": "IT", "transaction": "11", "delivery": "CIF", "location": "1", "transport": "3"},
    "MARTINOVIC":      {"country_dispatch": "HR", "transaction": "11", "delivery": "CPT", "location": "1", "transport": "3"},
    "MARTINOVIĆ":      {"country_dispatch": "HR", "transaction": "11", "delivery": "CPT", "location": "1", "transport": "3"},
    "ROMICA":          {"country_dispatch": "HR", "transaction": "11", "delivery": "CPT", "location": "1", "transport": "3"},
    "RO-TRADE":        {"country_dispatch": "HR", "transaction": "11", "delivery": "CPT", "location": "1", "transport": "3"},
    "MADIA":           {"country_dispatch": "IT", "transaction": "11", "delivery": "CIF", "location": "1", "transport": "3"},
    "FRULPESCA":       {"country_dispatch": "IT", "transaction": "11", "delivery": "CIF", "location": "1", "transport": "3"},
}

# ─── FAO / Izvor rib (deklaracije) ──────────────────────────────────────────
FAO_AREAS = {
    # Gojeno
    "GOJ_SLADKA_SI":  "Gojeno v sladki vodi, Slovenija",
    "GOJ_SLADKA_IT":  "Gojeno v sladki vodi, Italija",
    "GOJ_SLADKA_HR":  "Gojeno v sladki vodi, Hrvaška",
    "GOJ_MORJE_HR":   "Gojeno v morju, Hrvaška",
    "GOJ_MORJE_GR":   "Gojeno v morju, Grčija",
    "GOJ_MORJE_TR":   "Gojeno v morju, Turčija",
    "GOJ_MORJE_NO":   "Gojeno v morju, Norveška",
    "GOJ_MORJE_IT":   "Gojeno v morju, Italija",
    "GOJ_MORJE_ES":   "Gojeno v morju, Španija",
    "GOJ_MORJE_PT":   "Gojeno v morju, Portugalska",
    "GOJ_MORJE_FR":   "Gojeno v morju, Francija",
    # Divje ulovljeno — Sredozemlje
    "37":      "37 – Sredozemsko morje",
    "37.1":    "37/1 – Sredozemsko morje – Zahodni del",
    "37.1.1":  "37/1.1 – Sredozemsko morje – Balearsko morje",
    "37.1.3":  "37/1.3 – Sredozemsko morje – Sardinija",
    "37.2.1":  "37/2.1 – Sredozemsko morje – Jadransko morje",
    "37.2.2":  "37/2.2 – Sredozemsko morje – Jonsko morje",
    "37.3.1":  "37/3.1 – Sredozemsko morje – Egejsko morje",
    # Divje — Atlantik
    "27":      "27 – Severovzhodni Atlantik",
    "27.IV":   "27/IV – SV Atlantik – Severno morje",
    "27.VI":   "27/VI – SV Atlantik – Keltsko morje sever",
    "27.VII":  "27/VII – SV Atlantik – Keltsko morje jug",
    "27.VIIa": "27/VIIa – SV Atlantik – Irsko morje",
    "27.VIIf": "27/VIIf – SV Atlantik – Bristolski kanal",
    "27.VIII": "27/VIII – SV Atlantik – Baskijski zaliv",
    "27.VIIIa":"27/VIIIa – SV Atlantik – Baskijski zaliv sever",
    "27.IX":   "27/IX – SV Atlantik – Portugalske vode",
    "27.X":    "27/X – SV Atlantik – Azori",
    "21":      "21 – Severozahodni Atlantik",
    "34":      "34 – Centralnovzhodni Atlantik",
    "41":      "41 – Jugozahodni Atlantik",
    "47":      "47 – Jugovzhodni Atlantik",
    # Divje — Indijski ocean
    "51":      "51 – Zahodni Indijski ocean",
    "57":      "57 – Vzhodni Indijski ocean",
    # Divje — Tihi ocean
    "61":      "61 – Severozahodni Tihi ocean",
    "67":      "67 – Severovzhodni Tihi ocean",
    "71":      "71 – Centralnovzhodni Tihi ocean",
    "77":      "77 – Centralozahodni Tihi ocean",
    "87":      "87 – Jugovzhodni Tihi ocean",
    # Sladkovoda
    "05":      "05 – Sladkovodna tla Evrope",
    # Predelani ribiški proizvodi (bakala, namazi, konzerve...)
    "PREL_SI": "Predelano v Sloveniji",
    "PREL_IT": "Predelano v Italiji",
    "PREL_HR": "Predelano v Hrvaški",
    "PREL_ES": "Predelano v Španiji",
    "PREL_PT": "Predelano v Portugalski",
    "PREL_NO": "Predelano v Norveški",
    "PREL_FR": "Predelano v Franciji",
}

def _fao_naziv(code: str) -> str:
    code = (code or "").strip()
    return FAO_AREAS.get(code, code)

def _temperatura(item_name: str) -> str:
    n = (item_name or "").lower()
    if any(w in n for w in ["zamrzn"]):
        return "–18°C ali hladneje"
    return "do +3°C"

def _save_mappings(extra: dict):
    """Shrani uvožene mappinge (poleg hardkodiranih) na disk."""
    try:
        with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(extra, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _load_mappings() -> dict:
    """Naloži uvožene mappinge z diska."""
    try:
        if os.path.exists(MAPPINGS_FILE):
            with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _merge_mappings():
    """Združi hardkodirane + uvožene mappinge."""
    extra = _load_mappings()
    for sup, items in extra.items():
        if sup not in SUPPLIER_ITEM_MAPPINGS:
            SUPPLIER_ITEM_MAPPINGS[sup] = {}
        for kw, data in items.items():
            SUPPLIER_ITEM_MAPPINGS[sup][kw] = data

def _get_effective_mappings() -> dict:
    """Vedno vrne hardkodirani + uvoženi iz datoteke — zanesljivo."""
    merged = {}
    for sup, items in SUPPLIER_ITEM_MAPPINGS.items():
        merged[sup] = dict(items)
    for sup, items in _load_mappings().items():
        if sup not in merged:
            merged[sup] = {}
        merged[sup].update(items)
    return merged

def _import_mappings_csv(csv_text: str) -> tuple:
    """Uvozi mappinge iz CSV teksta. Vrne (dodani, napake)."""
    import csv, io
    dodani, napake = [], []
    reader = csv.DictReader(io.StringIO(csv_text))
    rows_list = list(reader)

    # Najprej počisti obstoječe za dobavitelje ki so v CSV-ju
    extra = _load_mappings()
    suppliers_in_csv = set()
    for row in rows_list:
        sup = (row.get("supplier_name") or row.get("dobavitelj","")).strip().upper()
        if sup:
            suppliers_in_csv.add(sup)
    for sup in suppliers_in_csv:
        # Počisti vse variante tega dobavitelja v extra (ne hardkodiranih)
        for key in list(extra.keys()):
            core_key = key.upper().replace("S.R.L.","").replace("D.O.O.","").replace("SRL","").replace("DOO","").strip().rstrip("., ")
            core_sup = sup.replace("S.R.L.","").replace("D.O.O.","").replace("SRL","").replace("DOO","").strip().rstrip("., ")
            if core_key and core_sup and (core_key in core_sup or core_sup in core_key):
                del extra[key]
    _save_mappings(extra)

    for row in rows_list:
        try:
            sup   = (row.get("supplier_name") or row.get("dobavitelj","")).strip().upper()
            kw    = (row.get("inv_name") or row.get("naziv_dob","")).strip().upper()
            code  = (row.get("item_code") or row.get("mm_sifra","")).strip()
            name  = (row.get("item_name") or row.get("mm_naziv","")).strip()
            nc    = float((row.get("nc") or row.get("NC") or "0").replace(",",".").replace("€","").strip() or 0)
            pc    = float((row.get("pc") or row.get("PC") or "0").replace(",",".").replace("€","").strip() or 0)
            tariff   = (row.get("tariff") or row.get("tarifa","")).strip().replace(" ","")
            country  = (row.get("country_of_origin") or row.get("dz_porekla","")).strip().upper()
            latin    = (row.get("latin_name") or row.get("latinski_naziv","")).strip()
            fao      = (row.get("fao") or row.get("fao_izvor","")).strip()
            nacin    = (row.get("nacin_ulova","")).strip()
            dispatch = (row.get("country_dispatch") or row.get("dz_odposlj","")).strip().upper()
            delivery = (row.get("delivery_terms") or row.get("pogoji_dobave","")).strip().upper()

            if not sup or not kw or not code:
                napake.append(f"Manjka sup/kw/code: {row}")
                continue

            # Posodobi extra (datoteka) in SUPPLIER_ITEM_MAPPINGS (spomin)
            entry = {
                "item_code": code, "item_name": name,
                "latinski_naziv": latin, "fao_code": fao,
                "nacin_ulova": nacin, "tariff": tariff,
                "country_of_origin": country,
            }
            if sup not in extra:
                extra[sup] = {}
            # Če keyword že obstaja z drugim item_code → pretvori v split
            existing = extra[sup].get(kw)
            if existing and existing.get("item_code") and existing["item_code"] != code:
                if not existing.get("needs_split"):
                    extra[sup][kw] = {
                        "item_code": None,
                        "item_name": f"⚠️ Razdeliti: {existing['item_code']} / {code}",
                        "needs_split": True,
                        "split_options": [
                            {"item_code": existing["item_code"], "item_name": existing.get("item_name","")},
                            {"item_code": code, "item_name": name},
                        ],
                        "tariff": tariff or existing.get("tariff",""),
                        "country_of_origin": country or existing.get("country_of_origin",""),
                    }
                else:
                    # Dodaj v obstoječe split opcije
                    extra[sup][kw]["split_options"].append({"item_code": code, "item_name": name})
            else:
                extra[sup][kw] = entry
            if sup not in SUPPLIER_ITEM_MAPPINGS:
                SUPPLIER_ITEM_MAPPINGS[sup] = {}
            SUPPLIER_ITEM_MAPPINGS[sup][kw] = extra[sup][kw]

            # _DEFAULT_PRICES
            if code and nc > 0:
                if code not in _DEFAULT_PRICES:
                    _DEFAULT_PRICES[code] = {}
                sup_key = sup.title()
                _DEFAULT_PRICES[code][sup_key] = {
                    "price": nc, "discount_pct": 0, "selling_price": pc,
                    "updated": str(__import__("datetime").date.today())
                }

            # SUPPLIER_INTRASTAT
            if dispatch and sup not in SUPPLIER_INTRASTAT:
                SUPPLIER_INTRASTAT[sup.title()] = {
                    "country_dispatch": dispatch,
                    "transaction": "11",
                    "delivery": delivery or "CPT",
                    "location": "1",
                    "transport": "3",
                }

            dodani.append(f"{sup} / {kw} → {code}")
        except Exception as e:
            napake.append(f"Napaka v vrstici: {e} — {row}")
    # extra je že posodobljen med uvozom — samo shrani
    _save_mappings(extra)
    return dodani, napake

def _get_intrastat(supplier_name: str) -> dict:
    sup_up = supplier_name.upper()
    for key, val in SUPPLIER_INTRASTAT.items():
        if key.upper() in sup_up:
            return val
    return {"country_dispatch": "", "transaction": "11", "delivery": "CPT", "location": "1", "transport": "3"}

SUPPLIER_PREFIXES = {
    "ALEMAR": "AL", "CERKVENIK": "CE", "KVIBO": "KV",
    "FIORITAL": "FI", "FORMIO": "FO", "LIBO": "LI",
    "COST IN": "CI", "ORADA ADRIATIC": "OA",
    "MARTINOVIC": "MF", "MARTINOVIĆ": "MF",
    "ROMICA": "RO", "RO-TRADE": "RT", "MADIA": "MA", "FRULPESCA": "FP",
}

VP_CEN_CODE  = "VP-CEN"


STATUS_ICON = {
    "ready":   "🟢",
    "error":   "🔴",
    "sent":    "🔵",
    "warning": "🟡",
}
# Znani mappingi po dobaviteljih (dopolnjujemo sproti)

OLTREON_INFO = "OltreCon d.o.o., Orehovlje 2F, 5291 Miren"
VET_OZNAKA   = "SI-849 ES"

REQUIRED_HEADER = [
    ("supplier_name", "⚠️", "Ime dobavitelja manjka"),
    ("invoice_date",  "⚠️", "Datum manjka"),
    ("invoice_number","⚠️", "Številka dobavnice manjka"),
]
REQUIRED_ROW = [
    ("item_code",  "❌", "Šifra artikla manjka"),
    ("quantity",   "⚠️", "Količina ni določena"),
    ("price",      "⚠️", "Nabavna cena ni določena"),
]
SUPPLIER_ITEM_MAPPINGS = {
    "LIBO": {
        "OČIŠČENA": {
            "item_code": "POSSS0301",
            "item_name": "(POSSS0301) POSTRV (Šarenka), 300-400g, očiščena, sveža, Slovenija",
        },
        "FILE BEL": {
            "item_code": "POSSS0202",
            "item_name": "(POSSS0202) POSTRV (Šarenka), 160-200g, file, sveža, Slovenija",
        },
        "FILE RDEČ": {
            "item_code":  None,   # potrebna ročna delitev
            "item_name":  "⚠️ Razdeliti: (LPOSS0202) ali (LPOSS0102)",
            "needs_split": True,
            "split_options": [
                {"item_code": "LPOSS0202", "item_name": "(LPOSS0202) LOSOSOVA POSTRV file, 150-300g, svež, Slovenija"},
                {"item_code": "LPOSS0102", "item_name": "(LPOSS0102) LOSOSOVA POSTRV file, 300g+, svež, Slovenija"},
            ],
        },
    },
    "ALEMAR": {
        "DENTICE GIBBOSO":  {"item_code":"ZOBSM1000","item_name":"(ZOBSM1000) ZOBATEC (debeloglavi), 1000-2000g, svež, FAO 34",
                             "latinski_naziv":"Dentex gibbosus","fao_code":"34","nacin_ulova":"Parangal",
                             "tariff":"03028300","country_of_origin":"MA"},
        "BRANZINO CROAZIA": {"item_code":"BRASH0400","item_name":"(BRASH0400) BRANCIN, 400-600g, svež, Hrvaška",
                             "latinski_naziv":"Dicentrarchus labrax","fao_code":"GOJ_MORJE_HR","nacin_ulova":"",
                             "tariff":"03028410","country_of_origin":"HR"},
        "COZZA DI BOUCHOT": {"item_code":"PEDSB0000","item_name":"(PEDSB0000) KLAPAVICE, sveže, Bouchot, Francija",
                             "latinski_naziv":"Mytilus galloprovincialis","fao_code":"GOJ_MORJE_FR","nacin_ulova":"",
                             "tariff":"03073110","country_of_origin":"FR"},
        "COZZA ITALIA":     {"item_code":"PEDSI0000","item_name":"(PEDSI0000) KLAPAVICE, sveže, Italija",
                             "latinski_naziv":"Mytilus galloprovincialis","fao_code":"GOJ_MORJE_IT","nacin_ulova":"",
                             "tariff":"03073110","country_of_origin":"IT"},
        "FASOLARO":         {"item_code":"FAZSX0000","item_name":"(FAZSX0000) LEPOTKE, sveže, FAO 37.2.1",
                             "latinski_naziv":"Callista chione","fao_code":"37.2.1","nacin_ulova":"Vlečne mreže",
                             "tariff":"16055390","country_of_origin":"IT"},
        "SARDINA":          {"item_code":"SARSH0003","item_name":"(SARSH0003) SARDELE, sveže, FAO 37.1.3",
                             "latinski_naziv":"Sardina pilchardus","fao_code":"37.1.3","nacin_ulova":"Potegalke",
                             "tariff":"03024310","country_of_origin":"IT"},
        "FILONE TONNO":     {"item_code":"TUNSO0100","item_name":"(TUNSO0100) TUN (rumenoplavuti), filon, Premium, odtaljen, FAO 87",
                             "latinski_naziv":"Thunnus albacares","fao_code":"87","nacin_ulova":"Vlečne mreže",
                             "tariff":"03023290","country_of_origin":"ID"},
        "VONGOLE VERACI":   {"item_code":"VONSI0000","item_name":"(VONSI0000) KOČICE, sveže, Italija",
                             "latinski_naziv":"Ruditapes decussatus","fao_code":"GOJ_MORJE_IT","nacin_ulova":"",
                             "tariff":"16055390","country_of_origin":"IT"},
    },
}

def _apply_supplier_mapping(supplier_name: str, rows: list) -> list:
    """Aplicira znane mappinge po dobavitelju — združi VSE ujemajoče (ALEMAR + ALEMAR S.R.L.)."""
    sup_up    = supplier_name.upper()
    all_maps  = _get_effective_mappings()
    mapping   = {}
    for key, val in all_maps.items():
        key_up = key.upper()
        # Normaliziraj: odstrani pravne oblike in ločila
        def _norm(s):
            import re
            s = s.upper()
            for x in ["S.R.L.","D.O.O.","S.P.","SRL","DOO","SP","UNIPERSONALE","D.D."]:
                s = s.replace(x, " ")
            s = re.sub(r'[,.\-/\()+]', ' ', s)
            return set(w for w in s.split() if len(w) > 2)
        key_words = _norm(key_up)
        sup_words = _norm(sup_up)
        # Ujemanje: vsaj 1 skupna beseda daljša od 3 znakov
        common = key_words & sup_words
        if common and max(len(w) for w in common) > 3:
            mapping.update(val)
    if not mapping:
        return rows

    # Razvrsti po specifičnosti — daljši keyword ima prioriteto
    sorted_kw = sorted(mapping.items(),
                       key=lambda x: len([w for w in x[0].split() if len(w) > 2]),
                       reverse=True)

    for row in rows:
        inv_name_up = row.get("inv_name", "").upper()
        for keyword, data in sorted_kw:
            kw_words = [w for w in keyword.upper().split() if len(w) > 2]
            if kw_words and all(w in inv_name_up for w in kw_words):
                row["item_code"] = data.get("item_code") or ""
                row["item_name"] = data.get("item_name") or ""
                if data.get("latinski_naziv") and not row.get("latinski_naziv"):
                    row["latinski_naziv"] = data["latinski_naziv"]
                if data.get("fao_code") and not row.get("fao_code"):
                    row["fao_code"]  = data["fao_code"]
                    row["fao_naziv"] = FAO_AREAS.get(data["fao_code"], data["fao_code"])
                if "nacin_ulova" in data and not row.get("nacin_ulova"):
                    row["nacin_ulova"] = data["nacin_ulova"]
                # Tarifa in poreklo samo za tuje dobavitelje (ne SI)
                _intra = _get_intrastat(supplier_name)
                if _intra.get("country_dispatch","").upper() != "SI":
                    if data.get("tariff") and not row.get("tariff"):
                        row["tariff"] = data["tariff"]
                    if data.get("country_of_origin") and not row.get("country_of_origin"):
                        row["country_of_origin"] = data["country_of_origin"]
                else:
                    row["tariff"]            = ""
                    row["country_of_origin"] = ""
                if data.get("needs_split"):
                    row["_needs_split_hint"] = True
                    row["_split_options"]    = data.get("split_options", [])
                break
    return rows

def _save_prices(prices: dict):
    try:
        with open(PRICES_FILE, "w", encoding="utf-8") as f:
            json.dump(prices, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# Začetne znane cene — se dopolnjuje sproti
_DEFAULT_PRICES = {
    # Libo
    "POSSS0301": {"RIBOGOJNICA LIBO D.O.O.": {"price": 6.50,  "discount_pct": 0, "selling_price": 8.50,  "updated": "2026-03-26"}},
    "POSSS0202": {"RIBOGOJNICA LIBO D.O.O.": {"price": 11.00, "discount_pct": 0, "selling_price": 15.66, "updated": "2026-03-26"}},
    "LPOSS0202": {"RIBOGOJNICA LIBO D.O.O.": {"price": 12.00, "discount_pct": 0, "selling_price": 15.60, "updated": "2026-03-26"}},
    "LPOSS0102": {"RIBOGOJNICA LIBO D.O.O.": {"price": 12.00, "discount_pct": 0, "selling_price": 15.60, "updated": "2026-03-26"}},
    # Alemar
    "ZOBSM1000": {"ALEMAR S.R.L.": {"price": 18.33, "discount_pct": 0, "selling_price": 27.32, "updated": "2026-05-21"}},
    "BRASH0400": {"ALEMAR S.R.L.": {"price": 9.41,  "discount_pct": 0, "selling_price": 11.76, "updated": "2026-05-21"}},
    "PEDSI0000": {"ALEMAR S.R.L.": {"price": 2.33,  "discount_pct": 0, "selling_price": 5.91,  "updated": "2026-05-21"}},
    "PEDSB0000": {"ALEMAR S.R.L.": {"price": 5.14,  "discount_pct": 0, "selling_price": 5.20,  "updated": "2026-05-21"}},
    "FAZSX0000": {"ALEMAR S.R.L.": {"price": 14.55, "discount_pct": 0, "selling_price": 18.00, "updated": "2026-05-21"}},
    "SARSH0003": {"ALEMAR S.R.L.": {"price": 5.34,  "discount_pct": 0, "selling_price": 5.50,  "updated": "2026-05-21"}},
    "TUNSO0100": {"ALEMAR S.R.L.": {"price": 18.82, "discount_pct": 0, "selling_price": 23.16, "updated": "2026-05-21"}},
    "VONSI0000": {"ALEMAR S.R.L.": {"price": 16.98, "discount_pct": 0, "selling_price": 22.80, "updated": "2026-05-21"}},
}

def _load_prices() -> dict:
    """Naloži cene: DEFAULT_PRICES kot baza + merge s shranjenimi (shranjene imajo prioriteto)."""
    merged = {k: dict(v) for k, v in _DEFAULT_PRICES.items()}
    try:
        if os.path.exists(PRICES_FILE):
            with open(PRICES_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for code, sups in saved.items():
                if code not in merged:
                    merged[code] = {}
                merged[code].update(sups)
    except Exception:
        pass
    _save_prices(merged)
    return merged

def _get_price(prices: dict, item_code: str, supplier: str) -> dict:
    """Vrne zadnje znane cene za artikel+dobavitelj ali {}.
    Fuzzy matching — iščemo po delnem ujemanju imena dobavitelja."""
    art_prices = prices.get(item_code, {})
    if not art_prices:
        return {}
    sup_up = supplier.upper()
    # Točno ujemanje
    if sup_up in art_prices:
        return art_prices[sup_up]
    # Delno ujemanje — iščemo ali je katerikoli ključ vsebovan v imenu ali obratno
    for key in art_prices:
        key_words = [w for w in key.split() if len(w) > 3]
        if any(w in sup_up for w in key_words):
            return art_prices[key]
    return {}

def _set_price(prices: dict, item_code: str, supplier: str,
               price: float, discount_pct: float,
               selling_price: float, date_str: str) -> dict:
    """Shrani cene za artikel+dobavitelj."""
    if item_code not in prices:
        prices[item_code] = {}
    prices[item_code][supplier.upper()] = {
        "price":        price,
        "discount_pct": discount_pct,
        "selling_price": selling_price,
        "updated":      date_str,
    }
    return prices

def _save_drafts(drafts: dict):
    """Shrani osnutke v JSON datoteko — preživi reboot in osvežitev strani."""
    try:
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

def _save_files(file_store: dict):
    """Shrani seznam čakajočih datotek (brez bytes)."""
    try:
        slim = {k: {"name": v["name"], "type": v["type"]} for k, v in file_store.items()}
        with open(FILES_FILE, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _load_files() -> dict:
    """Naloži seznam čakajočih datotek (brez bytes — bytes se izgubijo na reboot)."""
    try:
        if os.path.exists(FILES_FILE):
            with open(FILES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Vrni brez bytes (bytes se morajo ponovno naložiti)
            return {k: {**v, "bytes": None} for k, v in data.items()}
    except Exception:
        pass
    return {}

# ─── Pomožne funkcije ─────────────────────────────────────────────────────────

def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        pass
    import os
    return os.environ.get(key, default)

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

_PARSE_PROMPT = """Ti si strokovnjak za branje dobavnic rib in morskih sadežev.
Dokument je lahko DDT (Italia), dobavnica (HR, SI) ali račun v kateremkoli jeziku.
Vrni SAMO čist JSON brez markdown, brez komentarjev.

{
  "supplier_name": "polno ime dobavitelja",
  "invoice_number": "številka DDT/računa/dobavnice",
  "invoice_date": "YYYY-MM-DD",
  "datum_izlova": "YYYY-MM-DD če je naveden",
  "items": [
    {
      "name": "naziv artikla kot piše na dokumentu",
      "latin_name": "latinsko ime vrste — poišči iz opisa ali po lastnem znanju",
      "quantity": 0.000,
      "unit": "kg",
      "price": 0.00,
      "discount_pct": 0.00,
      "country_of_origin": "2-črkovna ISO koda",
      "tariff": "carinska tarifa samo cifre",
      "fao_zone": "FAO cona npr. 37.2.1 ali 34",
      "nacin_ulova": "metoda v slovenščini",
      "rok_trajanja": "DD.MM.YYYY ali prazno",
      "lot_dobavitelja": "lot/serija iz dokumenta"
    }
  ]
}

NAVODILA ZA BRANJE:

Količina in cena:
- quantity = dejanska TEŽA v kg — na italijanskih DDT je to stolpec "Qtà", ne "Colli"
- "Colli" = število embalaž → prezri za quantity
- price = cena NA ENOTO (€/kg), ne skupna vrednost
- discount_pct = popust točno kot piše na dokumentu, ne predpostavljaj

Rok trajanja:
- Iščeš "scadenza", "consumare entro", "best before", "porabiti do" — datumski podatek na živilu
- "30 giorni", "60gg" pri plačilnih pogojih = ROK PLAČILA, to ni rok trajanja živila
- Sveže ribe nimajo 30-dnevnega roka — tipično 3-7 dni od datuma izlova/dobave
- Zamrznjene: rok je naveden na embalaži, pustite prazno če ni na dokumentu
- Če rok trajanja ni eksplicitno naveden za živilo: pusti prazno

Latinski naziv:
- Poišči v opisu ali po lastnem znanju
- Brancin=Dicentrarchus labrax, Orada=Sparus aurata, Klapavice=Mytilus galloprovincialis,
  Tun rumenoplavuti=Thunnus albacares, Sardele=Sardina pilchardus, Zobatec=Dentex gibbosus,
  Kočice=Ruditapes decussatus, Lepotke=Callista chione, Postrv=Oncorhynchus mykiss,
  Losos=Salmo salar, Hobotnica=Octopus vulgaris, Skuša=Scomber scombrus

FAO cona:
- Preberi iz opisa artikla ali iz legende na dokumentu (A=Pescato/lovljeno, C=Allevato/gojeno)
- Jadransko morje=37.2.1, Sredozemlje=37, Atlantik centro-orientale=34, Pacifik JV=87

Način ulova (v slovenščini):
- Palangari/Ami=Parangal, Reti da traino/Draghe=Vlečne mreže, Lampara/Circuizione=Potegalke,
  Reti/Rete=Mreže, Allevato/Allevamento/Gojeno=pusti prazno (gojene ribe nimajo načina ulova)

Lot dobavitelja: preberi iz stolpca "Lotte", "Lot", "Serija", "Batch"
Carinska tarifa: preberi iz dokumenta ali po lastnem znanju za vrsto ribe
Država porekla: 2-črkovna ISO koda (IT, HR, MA, ID, NO...)"""

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
    """Kreira deklaracije — ena na unikaten artikel+lot."""
    lot      = header.get("lot_number","")
    seen     = set()
    decls    = []
    for r in rows:
        code = r.get("item_code","")
        if not code or code in seen:
            continue
        seen.add(code)
        item_name = r.get("item_name","") or code
        decls.append({
            "item_code":       code,
            "naziv_artikla":   item_name,
            "latinski_naziv":  r.get("latinski_naziv",""),
            "lot_ours":        r.get("batch_number","") or lot,
            "lot_supplier":    r.get("lot_dobavitelja",""),
            "fao_code":        r.get("fao_code",""),
            "fao_naziv":       _fao_naziv(r.get("fao_code","")),
            "nacin_ulova":     r.get("nacin_ulova",""),
            "rok_trajanja":    r.get("rok_trajanja",""),
            "temperatura":     _temperatura(item_name),
        })
    return decls


def _generate_zpl(decl: dict) -> str:
    """ZPL II za Zebra GK420t — 8cm × 5cm @ 203dpi (639×406 pik)."""
    def esc(s): return (s or "").replace("^","").replace("~","")[:55]

    naziv  = esc(decl.get("naziv_artikla",""))
    lat    = esc(decl.get("latinski_naziv",""))
    lot    = esc(decl.get("lot_ours",""))
    fao    = esc(decl.get("fao_naziv",""))
    nacin  = esc(decl.get("nacin_ulova",""))
    rok    = esc(decl.get("rok_trajanja",""))
    temp   = esc(decl.get("temperatura","do +3\xb0C"))

    nacin_line = f"^FO8,120^A0N,18,18^FDNacin ulova: {nacin}^FS\n" if nacin else ""

    return (
        "^XA\n"
        "^PW639\n"
        "^LL406\n"
        "^CI28\n"
        f"^FO8,5^A0N,15,15^FDProdaja: OltreCon d.o.o., Orehovlje 2F, 5291 Miren^FS\n"
        "^FO8,22^GB623,1,1^FS\n"
        f"^FO8,26^A0N,22,22^FD{naziv}^FS\n"
        f"^FO8,52^A0N,16,16^FD{lat}^FS\n"
        "^FO8,72^GB623,1,1^FS\n"
        f"^FO8,76^A0N,18,18^FDLOT: {lot}^FS\n"
        f"^FO8,98^A0N,18,18^FDFAO: {fao}^FS\n"
        + nacin_line +
        f"^FO8,142^A0N,18,18^FDRok trajanja: {rok}^FS\n"
        f"^FO8,164^A0N,18,18^FDHraniti pri temperaturi: {temp}^FS\n"
        "^FO391,232^GE240,162,3,B^FS\n"
        "^FO415,276^A0N,22,22^FDSI-849^FS\n"
        "^FO432,302^A0N,22,22^FDES^FS\n"
        "^XZ"
    )





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

@st.cache_data(ttl=1800, show_spinner=False)
def _load_items_map(username, org_id):
    """Naloži vse artikle tipa B (blago) in vrne {Code: ItemId} mapo."""
    from minimax_client import MinimaxClient
    cli = MinimaxClient(
        username=username,
        password=_secret("MINIMAX_PASSWORD",""),
        client_id=_secret("MINIMAX_CLIENT_ID",""),
        client_secret=_secret("MINIMAX_CLIENT_SECRET",""),
        org_id=int(org_id),
    )
    result = {}
    page   = 1
    while True:
        data = cli._get("/items", params={"CurrentPage": page, "PageSize": 500})
        # /items lahko vrne seznam direktno ali dict z Rows
        if isinstance(data, list):
            rows  = data
            total = len(data)
        else:
            rows  = data.get("Rows", [])
            total = data.get("TotalRows", 0)
        for r in rows:
            if r.get("ItemType","") == "S":
                continue
            code = (r.get("Code") or "").strip()
            iid  = r.get("ItemId") or 0
            mc   = float(r.get("MassPerUnit") or 1.0)
            if code and iid:
                result[code.upper()] = {"item_id": iid, "mass_converter": mc}
        fetched = (page - 1) * 500 + len(rows)
        if fetched >= total or not rows:
            break
        page += 1
    return result

def _get_item_data(cli, code: str) -> dict:
    """Vrne {"item_id": int, "mass_converter": float} za artikel po šifri."""
    username = _secret("MINIMAX_USERNAME", st.session_state.get("username",""))
    org_id   = _secret("MINIMAX_ORG_ID",  st.session_state.get("org_id","171038"))
    items_map = _load_items_map(username, org_id)
    found = items_map.get(code.upper().strip())
    if found:
        return found
    return {"item_id": 0, "mass_converter": 1.0}

def _get_item_id_by_code(cli, code: str) -> int:
    """Backwards compatible wrapper."""
    return _get_item_data(cli, code)["item_id"]

def _get_wh_id(cli):
    try:
        for wh in cli.get_warehouses():
            if wh.get("Code","") == VP_CEN_CODE:
                return wh.get("WarehouseId") or wh.get("ID") or 0
    except: pass
    return 0

def _get_supplier_id(cli, name):
    # 1. Preveri ročno vnesene ID-je
    manual = st.session_state.get("manual_sup_ids", {})
    name_up = name.upper()
    for key, sid in manual.items():
        if key in name_up or name_up in key:
            return sid

    # Paginiraj skozi vse stranke in poišči po imenu
    # CustomerId = pravilno ime polja (Minimax SI API)
    try:
        page = 1
        while True:
            data = cli._get("/customers", params={"CurrentPage": page, "PageSize": 100})
            rows = data.get("Rows", [])
            for s in rows:
                sn  = (s.get("Name") or "").upper()
                sid = s.get("CustomerId") or 0
                if sid and (name_up in sn or sn in name_up):
                    return sid
            total   = data.get("TotalRows", 0)
            fetched = (page - 1) * 100 + len(rows)
            if fetched >= total or not rows:
                break
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
        h          = draft["header"]
        intra      = _get_intrastat(h.get("supplier_name",""))
        is_foreign = intra.get("country_dispatch","SI").upper() != "SI"
        stock_rows = []
        for row in draft["rows"]:
            if row.get("_split_child"):
                continue
            rows_to_process = row.get("_split_rows", []) if row.get("_split") else [row]
            for r in rows_to_process:
                item_data = _get_item_data(cli, r.get("item_code",""))
                item_id   = item_data["item_id"]
                mass_conv = item_data["mass_converter"]
                if not item_id: return None, f"Artikel '{r.get('item_code')}' ni najden"
                qty   = float(r.get("quantity") or 0)
                price = float(r.get("price") or 0)
                disc  = float(r.get("discount_pct") or 0)
                nc            = round(price * (1 - disc / 100), 6) if disc else price
                nv            = round(nc * qty, 4)
                sell_price    = float(r.get("selling_price") or 0)
                sell_vrednost = round(sell_price * qty, 4) if sell_price > 0 else 0

                # Serija — fallback na LOT iz headerja če je vrstica prazna
                batch = r.get("batch_number","") or h.get("lot_number","")

                sr = {
                    "Item":                    {"ID": item_id},
                    "WarehouseTo":             {"ID": wh_id},
                    "Quantity":                qty,
                    "Price":                   price,
                    "DiscountPercent":          disc,
                    "Value":                   nv,
                    "SellingPrice":            sell_price if sell_price > 0 else 0,
                    "SellingPriceIncludesVAT": "N",
                    "MarginPercent":           0,
                    "BatchNumber":             batch,
                    "SerialNumber":            "",
                    "Mass":                    round(qty * mass_conv, 4),
                }
                # Intrastat samo za tuje dobavitelje
                if is_foreign:
                    if r.get("tariff"):
                        sr["CustomsTariffNumber"] = r["tariff"]
                    if r.get("country_of_origin"):
                        sr["CountryOfOrigin"] = r["country_of_origin"]
                stock_rows.append(sr)
        body = {
            "StockEntryType":    "P",
            "StockEntrySubtype": "S",
            "Status":            "O",
            "Date":              h["invoice_date"] + "T00:00:00",
            "Description":       h.get("invoice_number",""),
            "Customer":          {"ID": sup_id},
            "StockEntryRows":    stock_rows,
        }
        if is_foreign:
            body["CountryOfDispatch"] = intra["country_dispatch"]
            body["TransactionType"]   = intra["transaction"]
            body["DeliveryTerms"]     = intra["delivery"]
            body["PlaceOfDelivery"]   = intra["location"]
            body["TransportType"]     = intra["transport"]
        # Korak 1: Ustvari dokument brez BatchNumber
        body_no_batch = dict(body)
        rows_no_batch = []
        for sr in body["StockEntryRows"]:
            r_copy = dict(sr)
            r_copy.pop("BatchNumber", None)
            rows_no_batch.append(r_copy)
        body_no_batch["StockEntryRows"] = rows_no_batch

        result = cli._post("/stockentry", body_no_batch)

        # Korak 2: Poišči novo ustvarjen dokument — zadnji PS osnutek
        found_id = None
        for status in ["O", "V", ""]:
            params = {
                "StockEntryType":    "P",
                "StockEntrySubtype": "S",
                "CurrentPage":       1,
                "PageSize":          10,
            }
            if status:
                params["Status"] = status
            search   = cli._get("/stockentry", params=params)
            doc_rows = search.get("Rows", [])
            if doc_rows:
                # Vzemi prvega (najnovejšega)
                found_id = doc_rows[0].get("StockEntryId")
                break

        # Korak 3: Posodobi z BatchNumber via PUT
        if found_id:
            detail   = cli._get(f"/stockentry/{found_id}")
            old_rows = detail.get("StockEntryRows", [])
            for i, sr in enumerate(old_rows):
                if i < len(body["StockEntryRows"]):
                    sr["BatchNumber"] = body["StockEntryRows"][i].get("BatchNumber","")
            detail["StockEntryRows"] = old_rows
            cli._put(f"/stockentry/{found_id}", detail)
            return found_id, None
        return "?", None
    except Exception as e:
        return None, str(e)

# ─── Pomožne funkcije za UI ──────────────────────────────────────────────────

def _flabel(label: str, val) -> str:
    """Označi polje z 🔴 če je vrednost 0 ali prazna."""
    if val is None or val == "" or val == 0 or val == 0.0:
        return f"🔴 {label}"
    return f"✅ {label}"

def _art_status(row: dict) -> tuple:
    """Vrne (ujemanje_ok, podatki_ok) za prikaz dveh statusnih ikon."""
    matched   = bool(row.get("item_code")) or bool(row.get("_needs_split_hint"))
    data_ok   = (
        float(row.get("quantity") or 0) > 0 and
        float(row.get("price") or 0) > 0 and
        bool(row.get("batch_number"))
    )
    return matched, (matched and data_ok)

# ─── Iskanje artiklov ─────────────────────────────────────────────────────────

def _get_article_options() -> list:
    """Vrne vse znane artikle iz mappingov za iskanje."""
    articles, seen = [], set()
    for sup_mapping in _get_effective_mappings().values():
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
    """Filtrira artikle po ključnih besedah — ločene z / ali presledkom.
    Primer: 'postrv/150/svež' najde vse artikle ki vsebujejo vse tri besede."""
    if not query.strip():
        return options
    # Ločimo po "/" ali presledku, ignoriramo prazne
    raw = query.replace("/", " ")
    words = [w.strip().lower() for w in raw.split() if w.strip()]
    if not words:
        return options
    result = []
    for opt in options:
        text = f"{opt.get('item_code','')} {opt.get('item_name','')}".lower()
        if all(w in text for w in words):
            result.append(opt)
    return result

# ─── RENDER ───────────────────────────────────────────────────────────────────

def render():
    st.caption("Skeniranje dobavnic dobavitelja → P/L osnutek v VP-CEN + deklaracije")

    # Skrij +/- gumbe na number inputih + auto-select ob kliku
    st.markdown("""
    <style>
    button[data-testid="stNumberInputStepDown"],
    button[data-testid="stNumberInputStepUp"] {
        display: none !important;
    }
    /* Večja pisava v expander naslovih osnutkov */
    [data-testid="stExpander"] summary p {
        font-size: 1.05rem !important;
        font-weight: 500 !important;
        line-height: 1.5 !important;
    }
    /* Poudarjen rob expanders */
    [data-testid="stExpander"] {
        border-left: 3px solid #e0e0e0 !important;
        margin-bottom: 4px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    import streamlit.components.v1 as _components
    _components.html("""
    <script>
    function attachSelectAll() {
        var inputs = parent.document.querySelectorAll('input[type="number"]');
        inputs.forEach(function(inp) {
            if (!inp.dataset.selectAllAttached) {
                inp.addEventListener('focus', function() { this.select(); });
                inp.dataset.selectAllAttached = 'true';
            }
        });
    }
    // Ob zagonu in ob vsaki spremembi DOM
    attachSelectAll();
    var observer = new MutationObserver(attachSelectAll);
    observer.observe(parent.document.body, { childList: true, subtree: true });
    </script>
    """, height=0, scrolling=False)

    with st.sidebar:
        st.header("⚙️ Nastavitve")
        prices_loaded = st.session_state.get("prejem_prices", {})
        if prices_loaded:
            st.caption(f"💰 Cene v bazi: {len(prices_loaded)} artiklov")
        else:
            st.caption("💰 Cenovna baza: prazna")
        # Path debug
        eff = _get_effective_mappings()
        n_file = sum(len(v) for v in _load_mappings().values())
        st.caption(f"📦 Mappingi: {sum(len(v) for v in eff.values())} kw ({n_file} iz datoteke)")
        st.caption(f"📁 {MAPPINGS_FILE}")
        uploaded_prices = st.file_uploader(
        "Naloži prejem_cene.json",
        type=["json"],
        key="upload_cene",
        label_visibility="collapsed",
        )
        if uploaded_prices:
            try:
                data = json.loads(uploaded_prices.read().decode("utf-8"))
                _save_prices(data)
                st.session_state["prejem_prices"] = data
                st.sidebar.success(f"✅ Cene naložene: {len(data)} artiklov")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")
                st.divider()
        if st.button("🗑️ Počisti uvožene mappinge", use_container_width=True, key="btn_clear_mappings"):
            try:
                if os.path.exists(MAPPINGS_FILE):
                    os.remove(MAPPINGS_FILE)
                # Ponastavi na samo hardkodirane
                pass  # datoteka je bila že zbrisana
                st.sidebar.success("✅ Uvoženi mappingi počiščeni — ostanejo samo hardkodirani")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")

        with st.expander("📥 Uvozi mappinge (CSV)", expanded=False):
            st.caption("CSV iz Connections chata — stolpci: supplier_name, inv_name, item_code, item_name, nc, pc, tariff, country_of_origin, latin_name, fao, nacin_ulova, country_dispatch, delivery_terms")
            csv_file = st.file_uploader("CSV datoteka", type=["csv"], key="csv_mappings")
            if csv_file:
                try:
                    csv_text = csv_file.read().decode("utf-8-sig")
                    dodani, napake = _import_mappings_csv(csv_text)
                    if dodani:
                        st.success(f"✅ Uvoženo {len(dodani)} artiklov")
                        for d in dodani: st.write(f"  {d}")
                    if napake:
                        for n in napake: st.error(n)
                except Exception as e:
                    st.error(f"Napaka: {e}")

        st.divider()
        tc1, tc2 = st.sidebar.columns(2)
        test_sup = tc1.text_input("Dobavitelj", value="ALEMAR", key="inp_test_sup")
        test_art = tc2.text_input("Naziv artikla", value="BRANZINO CROAZIA 1000/1500", key="inp_test_art")
        if st.button("🔍 Testiraj keyword", use_container_width=True, key="btn_test_kw"):
            sup_up = test_sup.upper()
            mapping = {}
            for key, val in _get_effective_mappings().items():
                core = key.upper().replace("S.R.L.","").replace("D.O.O.","").replace("SRL","").replace("DOO","").strip().rstrip("., ")
                if core and (core in sup_up or sup_up in key.upper()):
                    mapping.update(val)
            inv_up = test_art.upper()
            sorted_kw = sorted(mapping.items(), key=lambda x: len([w for w in x[0].split() if len(w)>2]), reverse=True)
            found = None
            for kw, data in sorted_kw:
                kw_words = [w for w in kw.upper().split() if len(w) > 2]
                if kw_words and all(w in inv_up for w in kw_words):
                    found = (kw, data)
                    break
            if found:
                st.sidebar.success(f"✅ `{found[0]}` → **{found[1].get('item_code')}** {found[1].get('item_name','')[:40]}")
            else:
                st.sidebar.error(f"❌ Ni ujemanja za '{test_art}' pri {test_sup}")
                st.sidebar.caption(f"Dobavitelj ima {len(mapping)} keywordov")

        if st.button("📋 Znani artikli za Connections chat", use_container_width=True, key="btn_known_arts"):
            lines = ["Ze znani artikli - ne porocaj znova:"]
            for supplier, items in _get_effective_mappings().items():
                lines.append(f"{supplier}:")
                for kw, data in items.items():
                    if data.get("needs_split"):
                        opts = " / ".join(o["item_code"] for o in data.get("split_options",[]))
                        lines.append(f"  {kw} → {opts} (ročna delitev)")
                    else:
                        lines.append(f"  {kw} → {data.get('item_code','?')}")
                lines.append("")
            lines.append("Poroci SAMO artikle ki niso na tem seznamu.")
            st.sidebar.code("\n".join(lines), language=None)

        with st.expander("Minimax dostop", expanded=False):
            st.session_state["client_id"]     = st.text_input("Client ID",        value=_secret("MINIMAX_CLIENT_ID",""))
            st.session_state["client_secret"] = st.text_input("Client Secret",    value=_secret("MINIMAX_CLIENT_SECRET",""), type="password")
            st.session_state["username"]      = st.text_input("Uporabniško ime",  value=_secret("MINIMAX_USERNAME",""))
            st.session_state["password"]      = st.text_input("Geslo aplikacije", value=_secret("MINIMAX_PASSWORD",""), type="password")
            st.session_state["org_id"]        = st.text_input("ID organizacije",  value=_secret("MINIMAX_ORG_ID","171038"))


        st.divider()
        if st.button("🔍 Debug: Obstoječ PS", use_container_width=True, key="btn_debug_pl"):
            try:
                cli  = _get_client()
                data = cli._get("/stockentry", params={
                    "StockEntryType":    "P",
                    "StockEntrySubtype": "S",
                    "Status":            "P",
                    "CurrentPage":       1,
                    "PageSize":          3,
                })
                rows = data.get("Rows", [])
                if rows:
                    eid    = rows[0].get("StockEntryId")
                    detail = cli._get(f"/stockentry/{eid}")
                    sr     = (detail.get("StockEntryRows") or [{}])[0]
                    st.sidebar.write(f"**PS dokument ID={eid}, prva vrstica:**")
                    st.sidebar.json(sr)
                else:
                    st.sidebar.warning("Ni PS dokumentov")
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")

        if st.button("🔍 Debug: Poišči artikel", use_container_width=True, key="btn_debug_item"):
            try:
                cli  = _get_client()
                koda = st.session_state.get("debug_item_koda", "POSSS0301")
                data = cli._get("/items", params={"ItemCode": koda, "CurrentPage": 1, "PageSize": 5})
                st.sidebar.write(f"**Odgovor /items?ItemCode={koda}:**")
                st.sidebar.json(data)
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")
        st.session_state["debug_item_koda"] = st.sidebar.text_input(
            "Šifra artikla", value="POSSS0301", key="inp_debug_item"
        )

        if st.button("🔍 Debug: Poišči stranko", use_container_width=True, key="btn_debug_stranka"):
            try:
                cli  = _get_client()
                ime  = st.session_state.get("debug_stranka_ime", "LIBO")
                # Poskusi /customers z Search
                data = cli._get("/customers", params={"Search": ime, "PageSize": 10})
                st.sidebar.write("**Odgovor /customers:**")
                st.sidebar.json(data)
            except Exception as e:
                st.sidebar.error(f"Napaka: {e}")
        st.session_state["debug_stranka_ime"] = st.sidebar.text_input(
            "Ime za iskanje", value="LIBO", key="inp_debug_stranka"
        )

        with st.expander("🔧 Ročni ID dobavitelja", expanded=False):
            st.caption("Če iskanje dobavitelja ne deluje, vnesite ID ročno.")
            manual_sup_name = st.text_input("Ime dobavitelja", key="manual_sup_name",
                                             placeholder="RIBOGOJNICA LIBO d.o.o.")
            manual_sup_id   = st.number_input("Supplier ID (iz Minimaxa)", min_value=0,
                                               value=0, key="manual_sup_id")
            if st.button("💾 Shrani", key="btn_save_sup_id") and manual_sup_name and manual_sup_id > 0:
                if "manual_sup_ids" not in st.session_state:
                    st.session_state["manual_sup_ids"] = {}
                st.session_state["manual_sup_ids"][manual_sup_name.upper()] = manual_sup_id
                st.success(f"✅ {manual_sup_name} → ID: {manual_sup_id}")
    if "prejem_drafts" not in st.session_state:
        st.session_state["prejem_drafts"] = _load_drafts()


    if "prejem_file_store" not in st.session_state:
        st.session_state["prejem_file_store"] = _load_files()
    if "prejem_prices" not in st.session_state:
        st.session_state["prejem_prices"] = _load_prices()

    drafts     = st.session_state["prejem_drafts"]
    file_store = st.session_state["prejem_file_store"]

    # ═══════════════════════════════════════════════════════════
    # UPLOAD + OBDELAVA
    # ═══════════════════════════════════════════════════════════
    with st.expander("📤 Naloži in obdelaj dobavnice", expanded=not bool(drafts)):
        # Key reset trick — po nalaganju resetiramo widget (pobriše datoteke iz widgeta)
        upload_key = f"prejem_uploader_{st.session_state.get('upload_reset_n', 0)}"
        uploaded_files = st.file_uploader(
            "Izberite dobavnice (slike ali PDF)",
            type=["jpg","jpeg","png","pdf"],
            accept_multiple_files=True,
            key=upload_key,
            label_visibility="collapsed",
        )
        # Ko so datoteke naložene → shrani bytes in takoj resetiraj widget
        if uploaded_files:
            added = False
            for f in uploaded_files:
                if f.name not in file_store:
                    file_store[f.name] = {"bytes": f.read(), "type": f.type, "name": f.name}
                    added = True
            if added:
                st.session_state["prejem_file_store"] = file_store
                _save_files(file_store)
                st.session_state["upload_reset_n"] = st.session_state.get("upload_reset_n", 0) + 1
                st.rerun()

        # Prikaži samo neobdelane datoteke iz file_store
        unprocessed = [
            fname for fname in file_store
            if not any(d.get("fname") == fname for d in drafts.values())
        ]

        if not file_store:
            st.caption("Naložite dobavnice z gumbom zgoraj.")
        elif not unprocessed:
            st.info("Vse naložene datoteke so že obdelane.")
        else:
            selected_files = []
            for fname in unprocessed:
                fc1, fc2 = st.columns([9, 1])
                with fc1:
                    if st.checkbox(f"📄 {fname}", value=True, key=f"chk_f_{fname}"):
                        selected_files.append(fname)
                with fc2:
                    if st.button("✕", key=f"rm_f_{fname}", help="Odstrani datoteko"):
                        file_store.pop(fname, None)
                        st.session_state["prejem_file_store"] = file_store
                        _save_files(file_store)
                        st.rerun()

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
                            file_store.pop(fname, None)
                            _save_files(file_store)
                            continue

                        lot      = _lot_number(parsed.get("supplier_name",""), parsed.get("invoice_date",""))
                        rows_out = []
                        for item in parsed.get("items",[]):
                            rows_out.append({
                                "inv_name":          item.get("name",""),
                                "item_code":         "",
                                "item_name":         "",
                                "latinski_naziv":    item.get("latin_name",""),
                                "quantity":          float(item.get("quantity") or 0),
                                "unit":              item.get("unit","kg"),
                                "price":             float(item.get("price") or 0),
                                "selling_price":     0.0,
                                "batch_number":      lot,
                                "country_of_origin": item.get("country_of_origin",""),
                                "tariff":            item.get("tariff",""),
                                "fao_zone":          item.get("fao_zone",""),
                                "nacin_ulova":       item.get("nacin_ulova",""),
                                "rok_trajanja":      item.get("rok_trajanja",""),
                                "kategorija":        item.get("kategorija","sveže"),
                                "datum_izlova":      item.get("datum_izlova", parsed.get("datum_izlova","")),
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
                        # Odstrani iz file_store — obdelana datoteka ne potrebuje ostati
                        file_store.pop(fname, None)
                        _save_files(file_store)
                    prog.empty()
                    st.session_state["prejem_file_store"] = file_store
                    st.session_state["prejem_drafts"] = drafts
                    _save_drafts(drafts)
                    st.rerun()


    if not drafts:
        st.info("Naloži dobavnice zgoraj za začetek.")
        return

    # ═══════════════════════════════════════════════════════════
    # SEZNAM OSNUTKOV
    # ═══════════════════════════════════════════════════════════
    st.markdown("## 📋 Osnutki")
    st.markdown(f"{STATUS_ICON['ready']} Pripravljen &nbsp;&nbsp;"
                f"{STATUS_ICON['error']} Pomanjkljiv &nbsp;&nbsp;"
                f"{STATUS_ICON['sent']} Poslan v Minimax", unsafe_allow_html=True)

    # Preberemo trenutno vrednost master checkboxa iz session_state (nova vrednost je
    # že tam ob začetku rerun-a ker jo je Streamlit shranil ob kliku)
    current_master   = st.session_state.get("master_sel_all_drafts", False)
    prev_master_peek = st.session_state.get("prev_master_drafts", None)

    # Izračunamo efektivno selekcijo — upoštevamo če se je master ravnokar spremenil
    if prev_master_peek is not None and current_master != prev_master_peek:
        # Master se je spremenil → vsi ali nobeden
        effective_selected = list(drafts.keys()) if current_master else []
    else:
        # Beremo posamezne checkboxe iz session_state
        effective_selected = [did for did in drafts if st.session_state.get(f"sel_d_{did}", False)]

    # Gumb Izbriši dobavnice — zdaj vedno točen
    if st.button(
        f"🗑️ Izbriši dobavnice  ({len(effective_selected)} izbranih)" if effective_selected
        else "🗑️ Izbriši dobavnice  (označi za brisanje)",
        use_container_width=True,
        disabled=not effective_selected,
        key="btn_del_top",
    ):
        for did in effective_selected:
            drafts.pop(did, None)
        st.session_state["prejem_drafts"] = drafts
        _save_drafts(drafts)
        st.rerun()

    # Master checkbox za izbiro vseh osnutkov
    prev_master_drafts = st.session_state.get("prev_master_drafts", None)
    master_sel_drafts  = st.checkbox(
        "☑ Izberi / odzberi vse osnutke",
        key="master_sel_all_drafts",
    )
    # Ob spremembi → posodobi vse posamezne PRED renderiranjem posameznih
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
            lbl = (f"{icon} **{h.get('supplier_name') or fname}**"
                   f"  ·  {h.get('invoice_date','?')}"
                   f"  ·  #{h.get('invoice_number','?')}"
                   f"  ·  {len(draft.get('rows',[]))} artikov"
                   f"  ·  {len(draft.get('declarations',[]))} deklaracij"
                   + (f"  ·  ✅ Minimax ID: {draft.get('minimax_entry_id')}" if draft.get("sent_to_minimax") else ""))

            # Drži expander odprt po form submitu
            # Validacija PRED expander — potrebujemo za expanded parameter
            if draft.get("parse_error"):
                errors = [("❌", f"Napaka branja: {draft['parse_error']}")]  # za bool(errors)
            else:
                errors = _validate(h, draft.get("rows", []))
                if draft.get("send_error"):
                    errors = [("❌", f"Napaka Minimax: {draft['send_error']}")] + errors

            draft_exp_open = st.session_state.get(f"draft_exp_{draft_id}", bool(errors))
            with st.expander(lbl, expanded=draft_exp_open):
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
                    all_opts = _get_article_options()

                    for idx, row in enumerate(draft["rows"]):
                        # Preskoči split pod-vrstice (legacy — ne bi smelo biti)
                        if row.get("_split_child"):
                            continue

                        # Apliciraj mapping: ko ni artikla ALI ko manjka _needs_split_hint
                        _needs_remap = (
                            not row.get("item_code") or
                            not row.get("_split") and not row.get("_needs_split_hint")
                        ) and not row.get("_split")
                        if _needs_remap:
                            _sup = draft["header"].get("supplier_name","")
                            _upd = _apply_supplier_mapping(_sup, [dict(row)])
                            if _upd:
                                _r = _upd[0]
                                if _r.get("_needs_split_hint") or (not row.get("item_code") and _r.get("item_code")):
                                    row.update(_r)
                                    drafts[draft_id]["rows"][idx] = row
                                    _save_drafts(drafts)

                        matched, data_ok = _art_status(row)
                        s1       = "🟢" if matched  else "🔴"
                        s2       = "🟢" if data_ok  else "🔴"
                        qty_disp = float(row.get("quantity") or 0)
                        mm_naziv = row.get("item_name","")
                        mm_label = (f"   ·—·   {mm_naziv}" if mm_naziv else f"  ({row.get('item_code','')})") if matched else "   — artikel manjka"

                        exp_col, del_col = st.columns([20, 1])
                        with del_col:
                            if st.button("✕", key=f"del_row_{draft_id}_{idx}",
                                         help="Odstrani ta artikel iz osnutka"):
                                drafts[draft_id]["rows"].pop(idx)
                                st.session_state["prejem_drafts"] = drafts
                                _save_drafts(drafts)
                                st.rerun()
                        with exp_col:
                         with st.expander(
                            f"{s1}{s2} {idx+1}. {row['inv_name']}  ({qty_disp} {row.get('unit','kg')}){mm_label}",
                            expanded=False
                         ):
                            if row.get("latin_name"):
                                st.caption(f"🔬 *{row['latin_name']}*")

                            # Shrani original za Opusti
                            orig_key = f"orig_{draft_id}_{idx}"
                            if orig_key not in st.session_state:
                                st.session_state[orig_key] = {k:v for k,v in row.items() if not k.startswith("_")}


                            # Auto-fill cen iz zadnjega prejema
                            _prices  = st.session_state.get("prejem_prices", {})
                            _sup     = draft["header"].get("supplier_name","")
                            if row.get("item_code"):
                                _cached = _get_price(_prices, row["item_code"], _sup)
                                if _cached:
                                    if float(row.get("price") or 0) == 0:
                                        row["price"]        = _cached.get("price", 0)
                                        row["discount_pct"] = _cached.get("discount_pct", 0)
                                        # Sinhroniziraj session_state widget
                                        st.session_state[f"price_{draft_id}_{idx}"] = float(_cached.get("price", 0))
                                        st.session_state[f"disc_{draft_id}_{idx}"]  = float(_cached.get("discount_pct", 0))
                                    if float(row.get("selling_price") or 0) == 0:
                                        row["selling_price"] = _cached.get("selling_price", 0)
                                        st.session_state[f"sell_{draft_id}_{idx}"] = float(_cached.get("selling_price", 0))
                                    st.session_state["prejem_drafts"] = drafts

                            # Split UI — razširi v dve normalni vrstici z iskalnikoma
                            if row.get("_needs_split_hint") and not row.get("_split"):
                                split_opts = row.get("_split_options", [])
                                orig_qty   = float(row.get("quantity") or 0)
                                st.info(f"⚡ Razdelite {orig_qty} kg na {len(split_opts)} artikla — izpolnite spodaj in potrdite:")
                                if st.button("✅ Ustvari vrstice za delitev", key=f"split_create_{draft_id}_{idx}", type="primary"):
                                    # Zamenjaj originalno vrstico z dvema sub-vrsticama
                                    new_rows = []
                                    for si, opt in enumerate(split_opts):
                                        nr = dict(row)
                                        nr.update({
                                            "item_code":      opt["item_code"],
                                            "item_name":      opt.get("item_name",""),
                                            "quantity":       orig_qty if si == 0 else 0.0,
                                            "_needs_split_hint": False,
                                            "_split_parent":  True,
                                            "_split_group":   idx,
                                        })
                                        new_rows.append(nr)
                                    # Vstavi novi vrstici na mesto originalne
                                    before = drafts[draft_id]["rows"][:idx]
                                    after  = drafts[draft_id]["rows"][idx+1:]
                                    drafts[draft_id]["rows"] = before + new_rows + after
                                    st.session_state["prejem_drafts"] = drafts
                                    _save_drafts(drafts)
                                    st.rerun()

                            # ── Iskanje artikla — ZUNAJ forme (Enter ne zapre vrstice) ──
                            search_q = st.text_input(
                                "Minimax artikel — ključne besede, loči z  /",
                                value="",
                                placeholder="npr: postrv/file/svež  ali  LPOSS  ali  150-300",
                                key=f"sq_{draft_id}_{idx}",
                            )
                            filtered = _search_articles(search_q, all_opts)
                            f_labels = ["— izberi —"] + [
                                f"{o['item_code']}  {o['item_name']}" for o in filtered
                            ]
                            curr_code = row.get("item_code","")
                            curr_idx  = next(
                                (i+1 for i,o in enumerate(filtered) if o["item_code"]==curr_code), 0
                            )
                            sel_art = st.selectbox(
                                "Izberi artikel iz rezultatov",
                                f_labels, index=curr_idx,
                                key=f"sel_{draft_id}_{idx}",
                                label_visibility="collapsed",
                            )

                            with st.form(key=f"form_art_{draft_id}_{idx}"):
                                # ── Polja ────────────────────────────────
                                cc1,cc2,cc3,cc4 = st.columns(4)
                                cc1,cc2,cc3,cc4 = st.columns(4)
                                with cc1:
                                    f_qty      = st.number_input(_flabel("Količina",         row.get("quantity")),       value=float(row.get("quantity") or 0),       min_value=0.0, step=0.001, format="%.3f", key=f"qty_{draft_id}_{idx}")
                                    f_unit     = st.selectbox(_flabel("ME", row.get("unit")),
                                                    options=["kg","kos","zaboj","l","kom"],
                                                    index=["kg","kos","zaboj","l","kom"].index(row.get("unit","kg")) if row.get("unit","kg") in ["kg","kos","zaboj","l","kom"] else 0,
                                                    key=f"unit_{draft_id}_{idx}")
                                with cc2:
                                    f_price    = st.number_input(_flabel("Cena €/enoto",     row.get("price")),          value=float(row.get("price") or 0),          min_value=0.0, step=0.01,  format="%.4f", key=f"price_{draft_id}_{idx}")
                                    f_discount = st.number_input("% popusta",                                            value=float(row.get("discount_pct") or 0),   min_value=0.0, max_value=100.0, step=0.01, format="%.2f", key=f"disc_{draft_id}_{idx}")
                                with cc3:
                                    f_sell     = st.number_input(_flabel("Prod. cena €",     row.get("selling_price")),  value=float(row.get("selling_price") or 0),  min_value=0.0, step=0.01,  format="%.4f", key=f"sell_{draft_id}_{idx}")
                                    f_batch    = st.text_input( _flabel("Serija / Lot",      row.get("batch_number")),   value=row.get("batch_number",""),                                        key=f"batch_{draft_id}_{idx}")
                                with cc4:
                                    f_country  = st.text_input( _flabel("Država (2 črkoven)",row.get("country_of_origin")), value=row.get("country_of_origin",""),                               key=f"cntry_{draft_id}_{idx}")
                                    f_tariff   = st.text_input( _flabel("Carinska tarifa",   row.get("tariff")),         value=row.get("tariff",""),                                              key=f"tariff_{draft_id}_{idx}")
                                # ── Gumbi ────────────────────────────────
                                gb1, gb2 = st.columns(2)
                                with gb1:
                                    do_confirm = st.form_submit_button("✅ Potrdi", type="primary", use_container_width=True)
                                with gb2:
                                    do_revert  = st.form_submit_button("↩ Opusti spremembe", use_container_width=True)

                                if do_confirm:
                                    # Apliciraj izbiro artikla
                                    if sel_art and sel_art != "— izberi —":
                                        code      = sel_art.split("  ")[0].strip()
                                        name_part = sel_art[len(code):].strip()
                                        row["item_code"] = code
                                        row["item_name"] = name_part
                                    row["quantity"]          = f_qty
                                    row["unit"]              = f_unit
                                    row["price"]             = f_price
                                    row["discount_pct"]      = f_discount
                                    row["selling_price"]     = f_sell
                                    row["batch_number"]      = f_batch
                                    row["country_of_origin"] = f_country
                                    row["tariff"]            = f_tariff
                                    row["discount_pct"]      = f_discount
                                    # Posodobi snapshot
                                    st.session_state[orig_key] = {k:v for k,v in row.items() if not k.startswith("_")}
                                    # Shrani cene za prihodnje prejeme
                                    if row.get("item_code") and f_price > 0:
                                        prices   = st.session_state.get("prejem_prices", {})
                                        supplier = draft["header"].get("supplier_name","")
                                        date_str = draft["header"].get("invoice_date","")
                                        prices   = _set_price(prices, row["item_code"], supplier,
                                                              f_price, f_discount, f_sell, date_str)
                                        st.session_state["prejem_prices"] = prices
                                        _save_prices(prices)
                                    st.session_state[f"draft_exp_{draft_id}"] = True
                                    st.session_state["prejem_drafts"] = drafts
                                    _save_drafts(drafts)
                                    st.rerun()

                                if do_revert:
                                    # Povrni podatke vrstice
                                    orig = st.session_state.get(orig_key, {})
                                    for k, v in orig.items():
                                        row[k] = v
                                    st.session_state.pop(f"sq_{draft_id}_{idx}", None)
                                    st.session_state.pop(f"sel_{draft_id}_{idx}", None)
                                    st.session_state[f"draft_exp_{draft_id}"] = True
                                    st.session_state["prejem_drafts"] = drafts
                                    _save_drafts(drafts)
                                    st.rerun()

                            # ➕ Dodaj vrstico (za split skupino)
                            if row.get("_split_parent"):
                                if st.button("➕ Dodaj vrstico", key=f"add_row_{draft_id}_{idx}",
                                             help="Dodaj še eno vrstico v to split skupino"):
                                    nr = dict(row)
                                    nr.update({
                                        "item_code": "",
                                        "item_name": "",
                                        "quantity":  0.0,
                                        "_split_parent": True,
                                        "_split_group": row.get("_split_group", idx),
                                    })
                                    drafts[draft_id]["rows"].insert(idx + 1, nr)
                                    st.session_state["prejem_drafts"] = drafts
                                    _save_drafts(drafts)
                                    st.rerun()

                    # Skupna vrednost
                    if draft["rows"]:
                        total = sum(
                            float(r.get("quantity") or 0) * float(r.get("price") or 0)
                            for r in draft["rows"] if not r.get("_split_child")
                        )
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
                                decl_title = decl.get('naziv_artikla') or decl.get('item_code','')
                                decl_code  = decl.get('item_code','')
                                decl_label = f"🏷️ {decl_title}" + (f"  `{decl_code}`" if decl_code else "")
                                with st.expander(decl_label, expanded=False):
                                    dc1, dc2 = st.columns(2)
                                    with dc1:
                                        decl["naziv_artikla"]  = st.text_input("Naziv artikla",    value=decl.get("naziv_artikla",""),  key=f"dna_{draft_id}_{di}")
                                        decl["latinski_naziv"] = st.text_input("Latinski naziv",   value=decl.get("latinski_naziv",""), key=f"dln_{draft_id}_{di}")
                                        decl["lot_ours"]       = st.text_input("LOT (naš)",        value=decl.get("lot_ours",""),       key=f"dlo_{draft_id}_{di}")
                                        decl["rok_trajanja"]   = st.text_input("Rok trajanja",     value=decl.get("rok_trajanja",""),   key=f"drt_{draft_id}_{di}")
                                        decl["temperatura"]    = st.text_input("Hraniti pri temp.",value=decl.get("temperatura", _temperatura(decl.get("naziv_artikla",""))), key=f"dtp_{draft_id}_{di}")
                                    with dc2:
                                        fao_codes  = list(FAO_AREAS.keys())
                                        cur_code   = decl.get("fao_code","")
                                        fao_idx    = fao_codes.index(cur_code) if cur_code in fao_codes else 0
                                        sel_fao    = st.selectbox("FAO / Izvor", options=fao_codes,
                                                        format_func=lambda k: FAO_AREAS.get(k,k),
                                                        index=fao_idx, key=f"dfao_{draft_id}_{di}")
                                        decl["fao_code"]    = sel_fao
                                        decl["fao_naziv"]   = FAO_AREAS.get(sel_fao, sel_fao)
                                        # Način ulova — prazno pri gojenih
                                        je_gojen = sel_fao.startswith("GOJ_")
                                        decl["nacin_ulova"] = st.text_input(
                                            "Način ulova",
                                            value="" if je_gojen else decl.get("nacin_ulova",""),
                                            disabled=je_gojen,
                                            help="Pri gojenih ribah prazno" if je_gojen else "",
                                            key=f"dnu_{draft_id}_{di}"
                                        )
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
    st.divider()

    to_act = selected_draft_ids if selected_draft_ids else list(drafts.keys())
    ready_ids = [
        did for did in to_act
        if not drafts[did].get("parse_error")
        and not drafts[did].get("sent_to_minimax")
        and not _has_critical(_validate(drafts[did].get("header",{}), drafts[did].get("rows",[])))
    ]

    if st.button(
        f"📤 Pošlji v Minimax  ({len(ready_ids)} osnutkov)",
        type="primary", use_container_width=True,
        disabled=not ready_ids, key="btn_send",
    ):
        prog = st.progress(0)
        errors_send = []
        for i, did in enumerate(ready_ids):
            prog.progress((i+1)/len(ready_ids), text="Prenašam …")
            entry_id, err = _send_draft(drafts[did])
            if err:
                errors_send.append((did, err))
                drafts[did]["send_error"] = err
                st.session_state[f"draft_exp_{did}"] = True
            else:
                drafts[did]["sent_to_minimax"]  = True
                drafts[did]["minimax_entry_id"] = entry_id
                drafts[did].pop("send_error", None)
                st.success(f"✅ {drafts[did]['header'].get('supplier_name','?')} → ID: {entry_id}")
        prog.empty()
        st.session_state["prejem_drafts"] = drafts
        _save_drafts(drafts)
        if errors_send:
            for _did, _err in errors_send:
                sup = drafts[_did]["header"].get("supplier_name","?")
                st.error(f"❌ NAPAKA MINIMAX — {sup}: {_err}")
            st.warning("⚠️ Popravite napake in poskusite znova.")
        # Debug POST body + response
        if "last_post_body" in st.session_state:
            with st.expander("🔍 Debug: POST vrstice (BatchNumber)"):
                st.code(st.session_state["last_post_body"])
        if "last_post_response" in st.session_state:
            with st.expander("🔍 Debug: POST odgovor (Minimax)"):
                st.code(st.session_state["last_post_response"])
        else:
            st.rerun()


    if selected_draft_ids:
        st.caption(f"Izbrano: {len(selected_draft_ids)} osnutkov")
    else:
        st.caption("Brez izbora = akcija velja za vse osnutke.")
