"""
Tab: Ceniki
Tok: Naloži cenike dobaviteljev (PDF/Excel/CSV) → AI prebere → poveži artikle → HIT / HoReCa
"""

import streamlit as st
import json
import os
import uuid
import base64
import pathlib
from datetime import datetime, date

# ─── Poti ────────────────────────────────────────────────────────────────────
_DATA_DIR   = pathlib.Path(os.environ.get("DATA_DIR", str(pathlib.Path(__file__).parent)))
CENIKI_FILE = str(_DATA_DIR / "ceniki.json")

# ─── Konstante ────────────────────────────────────────────────────────────────
NASI_CENIKI = ["HIT", "HoReCa"]
SKLOPI      = ["Gojeno", "Divjaki", "Lokalna riba"]
PODSKOPI    = ["Cele ribe", "Fileji"]
GOJENO_DRZAVE = {
    "HR": "Hrvaška", "IT": "Italija", "TR": "Turčija",
    "NO": "Norveška", "GR": "Grčija", "ES": "Španija", "FR": "Francija",
}
SKLOP_IKONA = {"Gojeno": "🐟", "Divjaki": "🌊", "Lokalna riba": "🏔️"}
PODSKLOP_IKONA = {"Cele ribe": "🐠", "Fileji": "🔪"}

# ─── Pomožne funkcije ─────────────────────────────────────────────────────────

def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


def _prazen_nas_cenik() -> dict:
    return {
        sklop: {podsklop: [] for podsklop in PODSKOPI}
        for sklop in SKLOPI
    }


def _load_ceniki() -> list:
    try:
        if os.path.exists(CENIKI_FILE):
            with open(CENIKI_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.sort(key=lambda t: t.get("datum_od", ""))
            return data
    except Exception:
        pass
    return []


def _save_ceniki(tedni: list):
    try:
        with open(CENIKI_FILE, "w", encoding="utf-8") as f:
            json.dump(tedni, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"Napaka shranjevanja: {e}")


def _nov_teden(datum_od: str, datum_do: str) -> dict:
    return {
        "id":          str(uuid.uuid4())[:8],
        "datum_od":    datum_od,
        "datum_do":    datum_do,
        "ustvarjen":   datetime.now().isoformat()[:10],
        "ceniki_dob":  [],
        "nasi_ceniki": {ime: _prazen_nas_cenik() for ime in NASI_CENIKI},
    }


def _fmt_datum(d) -> str:
    if not d:
        return ""
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        return str(d)


def _parse_datum_input(d) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, str):
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(d.strip(), fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
    return str(d)


def _sklop_label(sklop: str, poreklo: str) -> str:
    if sklop == "Gojeno":
        drzava = GOJENO_DRZAVE.get(poreklo.upper(), poreklo)
        return f"Gojeno — {drzava}" if drzava else "Gojeno"
    return sklop


def _prestej_artiklov(teden: dict) -> dict:
    n_dob = sum(len(c.get("artikli", [])) for c in teden.get("ceniki_dob", []))
    nasi  = {}
    for ime in NASI_CENIKI:
        nc = teden.get("nasi_ceniki", {}).get(ime, {})
        total = 0
        for sklop_data in nc.values():
            if isinstance(sklop_data, dict):
                for arts in sklop_data.values():
                    total += len(arts)
            elif isinstance(sklop_data, list):
                total += len(sklop_data)
        nasi[ime] = total
    return {"dobavitelji": n_dob, **nasi}


def _migracija_stari_format(nas_cenik: dict) -> dict:
    """Migrira star format {sklop: [artikli]} v nov {sklop: {podsklop: [artikli]}}."""
    for sklop in SKLOPI:
        if sklop in nas_cenik and isinstance(nas_cenik[sklop], list):
            stari = nas_cenik[sklop]
            nas_cenik[sklop] = {ps: [] for ps in PODSKOPI}
            for art in stari:
                ps = _dolocii_podsklop(art)
                nas_cenik[sklop][ps].append(art)
    return nas_cenik


def _prerazporedi_podskope(nas_cenik: dict) -> dict:
    """Prerazporedi VSE artikle v pravilne podskope glede na naziv — popravi napačne razvrstitve."""
    for sklop in SKLOPI:
        sklop_data = nas_cenik.get(sklop, {})
        if isinstance(sklop_data, list):
            continue
        # Zberi vse artikle tega sklopa
        vsi = []
        for ps in PODSKOPI:
            vsi.extend(sklop_data.get(ps, []))
        # Počisti in razporedi na novo
        for ps in PODSKOPI:
            sklop_data[ps] = []
        for art in vsi:
            ps = _dolocii_podsklop(art)
            art["podsklop"] = ps
            sklop_data[ps].append(art)
        nas_cenik[sklop] = sklop_data
    return nas_cenik
    return nas_cenik

# ─── HTML izvoz ───────────────────────────────────────────────────────────────

def _logo_b64() -> str:
    logo_path = _DATA_DIR / "logo.png"
    if logo_path.exists():
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""


def _glava_html(naslov: str, podnaslov: str, logo_b64: str = "") -> str:
    logo_tag = (f'<img src="data:image/png;base64,{logo_b64}" style="height:48px;width:auto;margin-right:12px;" alt="logo">'
                if logo_b64 else "")
    return (f'<div style="display:flex;align-items:flex-start;gap:0;margin-bottom:10px;'
            f'padding-bottom:8px;border-bottom:2px solid #e8742a;">'
            f'{logo_tag}'
            f'<div style="line-height:1.5;font-size:11px;color:#444;">'
            f'<strong style="font-size:13px;color:#222;display:block;">Oltre Con d.o.o.</strong>'
            f'Orehovlje 2/f, 5291 Miren<br>Davčna št.: SI19211210</div></div>'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">'
            f'<div style="font-size:14px;font-weight:500;color:#222;">{naslov}</div>'
            f'<div style="font-size:10px;color:#777;">{podnaslov}</div></div>')


def _sklop_html_izvoz(sklop_naziv: str, artikli: list) -> str:
    if not artikli:
        return ""
    sortirani = sorted(artikli, key=lambda a: (a.get("naziv_slo") or a.get("naziv","")).lower())
    vrstice = ""
    for art in sortirani:
        naziv_prikaz = art.get("naziv_slo") or art.get("naziv","")
        lat = art.get("latinski_naziv","")
        lat_txt = f' <span style="color:#777;font-size:9px;font-style:italic;">({lat})</span>' if lat else ""
        por = f' <span style="color:#999;font-size:9px;">{art.get("poreklo","")}</span>' if art.get("poreklo") else ""
        cena = float(art.get("cena_prodajna") or art.get("cena") or 0)
        cena_str = f"{cena:.2f} €".replace(".", ",") if cena > 0 else "—"
        vrstice += (f'<tr style="border-bottom:0.5px solid #eee;">'
                    f'<td style="padding:2px 4px;color:#222;">{naziv_prikaz}{lat_txt}{por}</td>'
                    f'<td style="padding:2px 4px;text-align:right;color:#222;white-space:nowrap;">{cena_str}</td>'
                    f'</tr>')
    return (f'<div style="font-size:10px;font-weight:500;color:#e8742a;text-transform:uppercase;'
            f'letter-spacing:0.07em;padding:3px 0 2px;border-bottom:1px solid #f5c9a0;margin-bottom:2px;">{sklop_naziv}</div>'
            f'<table style="width:100%;border-collapse:collapse;margin-bottom:6px;"><tbody>{vrstice}</tbody></table>')

# ─── Parsanje dokumentov ──────────────────────────────────────────────────────

def _parse_prompt() -> str:
    return """Ti si strokovnjak za branje cenikov rib in morskih sadežev.
Vrni SAMO čist JSON brez markdown, brez komentarjev.

{
  "dobavitelj": "ime dobavitelja",
  "datum": "YYYY-MM-DD ali prazen niz",
  "valuta": "EUR",
  "artikli": [
    {
      "naziv": "naziv artikla kot piše v ceniku",
      "naziv_slo": "slovenski prevod — kratek, jasen, za slovenskega kupca. Primeri: 'Brancin 400-600g, svež, Hrvaška', 'Tun rumenoplavuti, filon, svež', 'Lososov file, brez kože'. Šarun=Šur, Totano=Liganj, Anello=Obroček lignja, Ricciola=Pisana limača, Ombrina=Senčar, Pagello=Rdeči ribon, Dentice=Zobatec, Spigola=Brancin, Orata=Orada, Sgombro=Skuša, Acciuga=Sardon, Cefalo=Cipal, Rombo=Morska plošča, Astice=Jastog, Coda di rospo=Rep morskega vraga, Anguilla=Jegulja",
      "latinski_naziv": "latinsko ime vrste",
      "cena": 0.00,
      "enota": "kg",
      "poreklo": "2-črkovna ISO koda",
      "sklop": "Gojeno ali Divjaki ali Lokalna riba",
      "podsklop": "Fileji ali Cele ribe",
      "komentar": ""
    }
  ]
}

Sklop: Gojeno=ribogojnice, Divjaki=divje ulovljene, Lokalna riba=slovensko poreklo.

PRAVILO ZA PODSKLOP — KRITIČNO:
podsklop="Fileji" SAMO če naziv vsebuje besede: file, filé, filet, filone, trancio, anello, suprema, lomo, darnes, steak, trance
podsklop="Cele ribe" za VSE ostalo.

Primeri Fileji: "FILONE DI TONNO", "FILE DI BRANZINO", "ANELLO DI TOTANO GIGANTE", "TRANCIO DI SALMONE", "SUPREMA DI ORATA"
Primeri Cele ribe: "CODA DI ROSPO" (rep, ne file!), "BRANZINO INTERO", "ASTICE VIVO", "TOTANO" (brez anello), "COZZE", "VONGOLE", "DENTICE PESCATO"

Cena=vedno za 1kg brez DDV.
Na italijanskih cenikih (Listino): stolpec "Prezzo" = cena/kg. Če je "Prezzo" prazen ali nič, vzami "Prezzo al collo" deljeno s "Peso netto Conf." (kg) = cena/kg.
Artikle brez cene (0 ali prazen) VSEENO vključi z cena=0.
Poreklo=2-črkovna ISO koda (HR,IT,NO,TR,GR,SI,ES,MA...)."""


_FILEJI_KW = {
    "file", "filé", "filet", "filone", "trancio", "anello",
    "suprema", "lomo", "darnes", "steak", "trance",
    "fillet", "fille", "fillets"
}

def _dolocii_podsklop(art: dict) -> str:
    """Določi podsklop na podlagi naziva — preveri originalni in SLO naziv."""
    # Preveri vse možne nazive
    naziv_orig = art.get("naziv","").lower()
    naziv_slo  = art.get("naziv_slo","").lower()
    naziv_lat  = art.get("latinski_naziv","").lower()
    skupaj     = f"{naziv_orig} {naziv_slo}"

    # Preveri ključne besede za filelje
    for kw in _FILEJI_KW:
        if kw in skupaj:
            return "Fileji"

    # Preveri s presledki za krajše besede (prepreči false positive)
    for kw in ["file", "filé"]:
        if f" {kw} " in f" {skupaj} " or skupaj.startswith(kw) or skupaj.endswith(kw):
            return "Fileji"

    return "Cele ribe"


def _repair_json(raw: str) -> str:
    """Poskusi popraviti odrezan JSON."""
    raw = raw.strip().replace("```json", "").replace("```", "").strip()
    try:
        json.loads(raw)
        return raw
    except Exception:
        pass
    for pattern in ["}\n  ]", "},\n    {", "},\n  {", "},"]:
        idx = raw.rfind(pattern)
        if idx > 0:
            candidate = raw[:idx+1].rstrip(",\n ") + "\n  ]\n}"
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                continue
    idx = raw.rfind("}")
    if idx > 0:
        candidate = raw[:idx+1]
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass
    return raw


def _parse_pdf_claude(pdf_bytes: bytes) -> tuple:
    try:
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {}, "ANTHROPIC_API_KEY ni nastavljen"
        client = anthropic.Anthropic(api_key=api_key)
        b64    = base64.b64encode(pdf_bytes).decode()
        for max_tok in [8192, 16000]:
            resp = client.messages.create(
                model="claude-opus-4-6", max_tokens=max_tok,
                messages=[{"role": "user", "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                    {"type": "text", "text": _parse_prompt()},
                ]}],
            )
            raw = _repair_json(resp.content[0].text.strip())
            try:
                result = json.loads(raw)
                # Preveri da ima artikle
                if result.get("artikli"):
                    return result, None
                # Prazen seznam — poskusi z večjim tokenjem
                if max_tok == 16000:
                    return result, None
                continue
            except json.JSONDecodeError:
                if max_tok == 16000:
                    return {}, "JSON napaka: odgovor prekinjen pri obeh poskusih."
                continue
        return {}, "JSON napaka."
    except Exception as e:
        return {}, str(e)


def _tabela_v_tekst(df) -> str:
    df = df.dropna(how="all").dropna(axis=1, how="all").fillna("")
    try:
        return df.to_markdown(index=False)
    except Exception:
        return df.to_string(index=False)


def _parse_excel_claude(file_bytes: bytes, fname: str) -> tuple:
    try:
        import pandas as pd, io
        xf = pd.ExcelFile(io.BytesIO(file_bytes))
        izbran_df, izbran_list = None, None
        for list_ime in xf.sheet_names:
            try:
                df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=list_ime, header=None)
            except Exception:
                continue
            df = df.dropna(how="all").dropna(axis=1, how="all")
            if len(df) < 2 or len(df.columns) < 2:
                continue
            glava_idx = 0
            for hi in range(min(8, len(df))):
                row = df.iloc[hi]
                non_empty = row.dropna().astype(str).str.strip()
                if non_empty.str.contains(r'[a-zA-ZčšžČŠŽ]', regex=True).any() and len(non_empty) >= 2:
                    glava_idx = hi
                    break
            df.columns = df.iloc[glava_idx].astype(str).str.strip()
            df = df.iloc[glava_idx + 1:].reset_index(drop=True).dropna(how="all").fillna("")
            if len(df) >= 1:
                izbran_list, izbran_df = list_ime, df
                break
        if izbran_df is None:
            return {}, f"Excel '{fname}': ni ustreznih listov (listi: {xf.sheet_names})"
        prompt = _parse_prompt() + f"\n\nDatoteka: {fname} (list: {izbran_list})\n\n{_tabela_v_tekst(izbran_df)}"
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {}, "ANTHROPIC_API_KEY ni nastavljen"
        client = anthropic.Anthropic(api_key=api_key)
        for max_tok in [8192, 16000]:
            resp = client.messages.create(model="claude-opus-4-6", max_tokens=max_tok,
                messages=[{"role": "user", "content": prompt}])
            raw = _repair_json(resp.content[0].text.strip())
            try:
                result = json.loads(raw)
                if result.get("artikli"):
                    return result, None
                if max_tok == 16000:
                    return result, None
                continue
            except json.JSONDecodeError:
                if max_tok == 16000:
                    return {}, "JSON napaka: Excel cenik je morda prevelik."
                continue
        return {}, "JSON napaka."
    except ImportError:
        return {}, "Manjka openpyxl"
    except Exception as e:
        return {}, f"Excel napaka: {str(e)}"


def _parse_csv_claude(file_bytes: bytes, fname: str) -> tuple:
    try:
        import pandas as pd, io
        df = None
        for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1250"]:
            for sep in [",", ";", "\t", "|"]:
                try:
                    df = pd.read_csv(io.BytesIO(file_bytes), sep=sep, encoding=enc, on_bad_lines="skip")
                    if len(df.columns) >= 2 and len(df) >= 2:
                        break
                except Exception:
                    continue
            if df is not None and len(df.columns) >= 2:
                break
        if df is None or len(df.columns) < 2:
            return {}, f"CSV '{fname}' ni bilo mogoče prebrati"
        df = df.dropna(how="all").dropna(axis=1, how="all").fillna("")
        prompt = _parse_prompt() + f"\n\nDatoteka: {fname}\n\n{_tabela_v_tekst(df)}"
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {}, "ANTHROPIC_API_KEY ni nastavljen"
        client = anthropic.Anthropic(api_key=api_key)
        for max_tok in [8192, 16000]:
            resp = client.messages.create(model="claude-opus-4-6", max_tokens=max_tok,
                messages=[{"role": "user", "content": prompt}])
            raw = _repair_json(resp.content[0].text.strip())
            try:
                result = json.loads(raw)
                if result.get("artikli"):
                    return result, None
                if max_tok == 16000:
                    return result, None
                continue
            except json.JSONDecodeError:
                if max_tok == 16000:
                    return {}, "JSON napaka: CSV je morda prevelik."
                continue
        return {}, "JSON napaka."
    except Exception as e:
        return {}, str(e)


# ─── Slovar za prevajanje (IT/HR → SLO) ─────────────────────────────────────

_PREVOD_SLOVAR = {
    # Italijanščina → slovenščina (ključi UPPERCASE)
    "ANGUILLA": "Jegulja", "ANELLO DI TOTANO GIGANTE DEL PACIFICO": "Obroček velikega pacifiškega lignja",
    "ANELLO DI TOTANO GIGANTE": "Obroček velikega lignja", "ANELLO DI TOTANO": "Obroček lignja",
    "ARROSTO DI SALMONE E MERLUZZO": "Pečenka lososa in osliča",    "ASTICE AMERICANO CANADA": "Ameriški jastog Kanada", "ASTICE AMERICANO": "Ameriški jastog",
    "ASTICE EUROPEO": "Evropski jastog", "ASTICE JUMBO": "Jastog jumbo",
    "BRANZINO CROAZIA": "Brancin Hrvaška", "BRANZINO GRECIA": "Brancin Grčija",
    "BRANZINO SPAGNA": "Brancin Španija", "BRANZINO": "Brancin",
    "CALAMARO FARCITO": "Polnjeni liganj", "CALAMARO": "Liganj",
    "CAPPASANTA ATLANTICA": "Atlantska pokrovača", "CAPPASANTA": "Pokrovača",
    "CERNIA GIALLA": "Rumeni kiranj", "CERNIA": "Kiranj",
    "CODA DI ROSPO": "Rep morskega vraga",
    "CUORE DI MERLUZZO NORDICO": "Srce nordijskega osliča",
    "DENTICE GIBBOSO": "Grbasti zobatec", "DENTICE": "Zobatec",
    "FILETTO DI SALMONE NORVEGIA": "File norveškega lososa",
    "FILETTO DI SARDINA": "File sardinele",
    "FILETTO DI STOCCAFISSO AMMOLLATO": "File namočene polenovke",
    "FILETTO EGLEFINO": "File vahnje", "FILETTO HALIBUT": "File halibuta",
    "FILETTO PERSICO AFRICANO": "File afriškega ostriža",
    "FILETTO PLATESSA": "File plešca", "FILETTO SALMONE": "File lososa",
    "FILETTO TROTA NORMALE": "File navadne postrvi", "FILETTO TROTA SALMONATA": "File lososove postrvi",
    "FILONE DI TONNO OBESO": "Filon debelega tuna", "FILONE DI TONNO ROSSO": "Filon rdečega tuna",
    "FILONE TONNO A PINNE GIALLE": "Filon rumenoplavutega tuna",
    "FILONE TONNO": "Filon tuna", "FILONE DI TONNO": "Filon tuna",
    "FISH BURGER DI TROTA": "Fish burger iz postrvi",
    "GRANCEOLA FEMMINA": "Samica rakovice", "GRANCEOLA MASCHIO": "Samec rakovice", "GRANCEOLA": "Rakovica",
    "GRANCIPORRO ATLANTICO": "Atlantska rakovica",
    "MERLUZZO NORDICO": "Nordijski oslič", "MERLUZZO": "Oslič",
    "MOLO INTERO": "Cel mol", "MOLO": "Mol",
    "MOSCARDINO ESTERO": "Muškatni hobotničnik", "MOSCARDINO": "Hobotničnik",
    "OMBRINA BOCCADORO": "Senčar zlata usta", "OMBRINA OCELLATA": "Pikasta senčarka", "OMBRINA": "Senčar",
    "ORATA CROAZIA": "Orada Hrvaška", "ORATA GRECIA": "Orada Grčija", "ORATA": "Orada",
    "PAGELLO FRAGOLINO": "Rdeči ribon", "PAGRO MAGGIORE": "Veliki pagr", "PAGRO": "Pagr",
    "PESCE SAN PIETRO": "Svetopeterska riba", "PESCE SPADA": "Mečarica",
    "POLPA DI GRANCHIO": "Rakova mezga",
    "POLPO COMUNE": "Navadna hobotnica", "POLPO DECONGELATO": "Odmrznjena hobotnica", "POLPO": "Hobotnica",
    "RANA PESCATRICE": "Morski vrag",
    "RICCIOLA OCEANICA": "Oceanska pisana limača", "RICCIOLA": "Pisana limača",
    "ROMBO CHIODATO": "Trnja morska plošča", "ROMBO": "Morska plošča",
    "SALMONE SCOZIA": "Škotski losos", "SALMONE": "Losos",
    "SEPPIA GROSSA PULITA": "Očiščena velika sipa", "SEPPIA NERA": "Črna sipa",
    "SEPPIA PICCOLA PULITA": "Očiščena mala sipa", "SEPPIA": "Sipa",
    "SGOMBRO": "Skuša", "SOASO ESTERO": "Komarča", "SOGLIOLA ALLEVATA": "Gojena morska plošča",
    "SPIEDINO GHIOTTO": "Ribji ražnjič",
    "STOCCAFISSO AMMOLLATO": "Namočena polenovka", "STOCCAFISSO": "Polenovka",
    "STRISCE DI TOTANO GIGANTE": "Trakovi velikega lignja",
    "TENTACOLI DI TOTANO": "Lovke lignja",
    "TONNETTO": "Mala tuna", "TONNO": "Tun",
    "TOTANO GIGANTE": "Veliki liganj", "TOTANO": "Liganj",
    "TRACINA": "Pauk riba",
    "TRIGLIA DI SCOGLIO": "Skalnati barbun", "TRIGLIA": "Barbun",
    "TROTA NORMALE EVISCERATA": "Navadna postrv, očiščena", "TROTA NORMALE INTERA": "Navadna postrv, cela",
    "TROTA SALMONATA EVISCERATA": "Lososova postrv, očiščena", "TROTA SALMONATA INTERA": "Lososova postrv, cela",
    "TROTA": "Postrv", "UOVA DI SEPPIA": "Jajca sipe",
    # Hrvaščina → slovenščina
    "Skuša": "Skuša", "Trupac": "Trupec", "Tuna BLUEFIN": "Modroplavuta tuna",
    "Tuna žutoperajna": "Rumenoplavuta tuna", "Tuna dugoperajna ALALUNGA": "Dolgoplavutna tuna (alalunga)",
    "Šarun": "Šur", "Palamida": "Palamida", "Luc": "Luc", "Gavun": "Gavun",
    "Srdela": "Sardela", "Inćun": "Sardon", "Lokarda": "Lokarda",
    "Haringa": "Sled", "Strijelka": "Strijelka", "Lica": "Lica",
    "Brancin": "Brancin", "Orada": "Orada", "Losos": "Losos",
    "Filet lososa": "File lososa", "Pastrva": "Postrv",
    "Pastrva dužičasta": "Dužičasta postrv", "Filet dužičaste pastrve": "File dužičaste postrvi",
    "Smuđ": "Smuč", "Jastog": "Jastog", "Škamp": "Škamp",
    "Hobotnica": "Hobotnica", "Liganj": "Liganj", "Sipa": "Sipa",
    "Dagnja": "Klapavica", "Kamenica": "Ostriga", "Kapesanta": "Pokrovača",
    "Kozica": "Kozica", "Grgeč": "Ostriž", "Som": "Som",
    "Kirnja": "Kiranj", "Oslić": "Oslič", "List": "Morska plošča",
    "Kovač": "Kovač", "Pic": "Pic", "Špar": "Špar",
    "Šur": "Šur", "Arbun": "Arbun", "Salpa": "Salpa",
    "Fratar": "Fratar", "Pirka": "Pirka", "Pagar": "Pagr",
    "Ušata": "Ušata", "Šnjur": "Šnjur", "Cipol": "Cipal",
    "Zubatac": "Zobatec", "Murina": "Murena",
}

def _prevedi_naziv(naziv: str) -> str:
    """Prevede naziv ribe IT/HR → SLO z uporabo slovarja."""
    naziv_up = naziv.upper().strip()
    # Poišči najdaljše ujemanje
    best_key, best_val = "", ""
    for kljuc, prevod in _PREVOD_SLOVAR.items():
        kljuc_up = kljuc.upper()
        if kljuc_up in naziv_up and len(kljuc_up) > len(best_key):
            best_key, best_val = kljuc_up, prevod
    if best_val:
        # Ohrani samo velikostni razred (številke in /) iz originalnega naziva
        import re as _re2
        stevke = _re2.findall(r'\d+[/+]?\d*', naziv)
        if stevke:
            return f"{best_val} {'/'.join(stevke)}".strip()
        return best_val
    # Hrvaški slovar (case-sensitive)
    for kljuc, prevod in _PREVOD_SLOVAR.items():
        if kljuc in naziv and len(kljuc) > len(best_key):
            best_key, best_val = kljuc, prevod
    if best_val:
        import re as _re2
        stevke = _re2.findall(r'\d+[/+]?\d*', naziv)
        if stevke:
            return f"{best_val} {'/'.join(stevke)}".strip()
        return best_val
    return naziv


def _dolocii_sklop_iz_naziva(naziv: str, latinski: str) -> str:
    """Določi sklop na podlagi latinskega/originalnega naziva."""
    lat = latinski.lower()
    naz = naziv.lower()
    # Gojene ribe po latinskem imenu
    gojeni_latinski = {
        "dicentrarchus labrax", "sparus aurata", "salmo salar",
        "oncorhynchus mykiss", "mytilus galloprovincialis",
        "sander lucioperca", "silurus glanis", "cyprinus carpio",
    }
    if any(g in lat for g in gojeni_latinski):
        return "Gojeno"
    # Lokalna riba
    if "hr" in naz or "slovenija" in naz or "si" in naz:
        if any(w in lat for w in ["oncorhynchus", "salmo trutta"]):
            return "Lokalna riba"
    # Divjaki — vse ostalo
    return "Divjaki"


def _parse_alemar_pdf(pdf_bytes: bytes) -> tuple:
    """Prebere Alemar PDF cenik z pdfplumber — brez AI."""
    try:
        import pdfplumber, io
        artikli = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            dobavitelj = "ALEMAR"
            datum = ""
            for page in pdf.pages:
                # Izvleci datum iz prve strani
                if not datum:
                    tekst = page.extract_text() or ""
                    import re
                    m = re.search(r'(\d{2}/\d{2}/\d{4})', tekst)
                    if m:
                        try:
                            from datetime import datetime
                            datum = datetime.strptime(m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
                        except:
                            pass
                    # Izvleci ime dobavitelja
                    if "ALEMAR" in tekst:
                        dobavitelj = "ALEMAR"

                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or not row[0]:
                            continue
                        if row[0] == 'Articolo':
                            continue
                        naziv = (row[1] or "").replace('\n', ' ').strip()
                        if not naziv:
                            continue
                        prezzo      = (row[6] or "").strip()
                        prezzo_collo = (row[7] or "").strip() if len(row) > 7 else ""
                        peso        = (row[5] or "1").strip()
                        # Izračunaj ceno/kg
                        cena = 0.0
                        if prezzo:
                            try:
                                cena = float(prezzo.replace(',', '.'))
                            except:
                                pass
                        elif prezzo_collo and peso:
                            try:
                                cena = round(float(prezzo_collo.replace(',','.')) /
                                             float(peso.replace(',','.')), 2)
                            except:
                                pass
                        if cena <= 0:
                            continue
                        # Določi poreklo iz naziva
                        import re as _re
                        poreklo = ""
                        for p_kw, p_iso in [("CROAZIA","HR"),("GRECIA","GR"),("SPAGNA","ES"),
                                             ("NORVEGIA","NO"),("SCOZIA","GB"),("SICILIA","IT"),
                                             ("ITALIA","IT"),("OLANDA","NL"),("CANADA","CA"),("ESTERO","")]:
                            if p_kw in naziv.upper():
                                poreklo = p_iso
                                break
                        latinski = ""
                        sklop    = _dolocii_sklop_iz_naziva(naziv, latinski)
                        naziv_slo = _prevedi_naziv(naziv)
                        artikli.append({
                            "naziv":          naziv,
                            "naziv_slo":      naziv_slo,
                            "latinski_naziv": latinski,
                            "cena":           cena,
                            "enota":          "kg",
                            "poreklo":        poreklo,
                            "sklop":          sklop,
                            "podsklop":       _dolocii_podsklop({"naziv": naziv, "naziv_slo": naziv_slo}),
                        })
        return {
            "dobavitelj": dobavitelj,
            "datum":      datum,
            "valuta":     "EUR",
            "artikli":    artikli,
        }, None
    except Exception as e:
        return {}, f"PDF napaka: {str(e)}"


def _parse_fiorital_excel(file_bytes: bytes, fname: str) -> tuple:
    """Prebere Fiorital Excel cenik — brez AI. Vzame zadnjo ne-nič ceno."""
    try:
        import pandas as pd, io
        df = pd.read_excel(io.BytesIO(file_bytes), header=None)
        artikli = []
        kategorija_sklopi = {
            "PLAVA RIBA": "Divjaki", "MORSKA RIBA IZ UZGOJA": "Gojeno",
            "SLATKOVODNA RIBA IZ UZGOJA": "Gojeno", "MEKUŠCI": "Divjaki",
            "ŠKOLJKE": "Divjaki", "RAKOVI": "Divjaki", "OSTALO": "Divjaki",
        }
        cur_sklop = "Divjaki"
        skip_kw = set(kategorija_sklopi.keys()) | {"nan",""}

        for idx, row in df.iterrows():
            if idx < 3:
                continue
            naziv = str(row[2]).strip() if pd.notna(row[2]) else ""
            if not naziv or naziv == "nan":
                continue
            # Kategorija = sklop
            naziv_up = naziv.upper()
            if naziv_up in {k.upper() for k in kategorija_sklopi}:
                for k, v in kategorija_sklopi.items():
                    if k.upper() == naziv_up:
                        cur_sklop = v
                continue
            latinski = str(row[3]).strip() if pd.notna(row[3]) else ""
            if latinski == "nan":
                latinski = ""
            poreklo = str(row[4]).strip() if pd.notna(row[4]) else ""
            if poreklo == "nan":
                poreklo = ""
            # Zadnja ne-nič vrednost iz cenovnih stolpcev (6+)
            cena = 0.0
            for val in reversed(list(row[6:])):
                if pd.notna(val) and val != 0:
                    try:
                        v = float(val)
                        if v > 0:
                            cena = round(v, 2)
                            break
                    except:
                        pass
            if cena <= 0:
                continue
            sklop = _dolocii_sklop_iz_naziva(naziv, latinski) if cur_sklop == "Divjaki" else cur_sklop
            naziv_slo = _prevedi_naziv(naziv)
            artikli.append({
                "naziv":          naziv,
                "naziv_slo":      naziv_slo,
                "latinski_naziv": latinski,
                "cena":           cena,
                "enota":          "kg",
                "poreklo":        poreklo.split("/")[0] if "/" in poreklo else poreklo,
                "sklop":          sklop,
                "podsklop":       _dolocii_podsklop({"naziv": naziv, "naziv_slo": naziv_slo}),
            })
        return {
            "dobavitelj": "FIORITAL",
            "datum":      "",
            "valuta":     "EUR",
            "artikli":    artikli,
        }, None
    except Exception as e:
        return {}, f"Excel napaka: {str(e)}"


def _parse_genericni_excel(file_bytes: bytes, fname: str) -> tuple:
    """Generični Excel parser z AI — za dobavitelje ki niso Alemar/Fiorital."""
    try:
        import pandas as pd, io
        xf = pd.ExcelFile(io.BytesIO(file_bytes))
        izbran_df, izbran_list = None, None
        for list_ime in xf.sheet_names:
            try:
                df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=list_ime, header=None)
                df = df.dropna(how="all").dropna(axis=1, how="all")
                if len(df) >= 3 and len(df.columns) >= 2:
                    for hi in range(min(8, len(df))):
                        row = df.iloc[hi]
                        non_empty = row.dropna().astype(str).str.strip()
                        if non_empty.str.contains(r'[a-zA-ZčšžČŠŽ]', regex=True).any() and len(non_empty) >= 2:
                            df.columns = df.iloc[hi].astype(str).str.strip()
                            df = df.iloc[hi+1:].reset_index(drop=True).dropna(how="all").fillna("")
                            break
                    izbran_list, izbran_df = list_ime, df
                    break
            except:
                continue
        if izbran_df is None:
            return {}, f"Excel '{fname}': ni ustreznih listov"
        tabela_txt = _tabela_v_tekst(izbran_df)
        prompt = _parse_prompt() + f"\n\nDatoteka: {fname}\n\n{tabela_txt}"
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY","")
        if not api_key:
            return {}, "ANTHROPIC_API_KEY ni nastavljen"
        client = anthropic.Anthropic(api_key=api_key)
        for max_tok in [8192, 16000]:
            resp = client.messages.create(model="claude-opus-4-6", max_tokens=max_tok,
                messages=[{"role":"user","content":prompt}])
            raw = _repair_json(resp.content[0].text.strip())
            try:
                result = json.loads(raw)
                if result.get("artikli"):
                    return result, None
                if max_tok == 16000:
                    return result, None
                continue
            except json.JSONDecodeError:
                if max_tok == 16000:
                    return {}, "JSON napaka."
                continue
        return {}, "JSON napaka."
    except ImportError:
        return {}, "Manjka openpyxl"
    except Exception as e:
        return {}, str(e)


def _zaznaj_format(file_bytes: bytes, ext: str) -> str:
    """Zazna dobavitelja/format iz vsebine dokumenta — ne iz imena datoteke."""
    try:
        if ext == "pdf":
            import pdfplumber, io
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                tekst = (pdf.pages[0].extract_text() or "").upper()
            if "ALEMAR" in tekst or "LISTINO" in tekst:
                return "alemar_pdf"
            return "pdf_neznan"
        elif ext in ("xlsx", "xls"):
            import pandas as pd, io
            df = pd.read_excel(io.BytesIO(file_bytes), header=None, nrows=5)
            tekst = " ".join(str(v) for v in df.values.flatten() if str(v) != "nan").upper()
            if "FIORITAL" in tekst or "CJENIK" in tekst:
                return "fiorital_excel"
            return "excel_neznan"
        elif ext == "csv":
            return "csv_neznan"
    except Exception:
        pass
    return "neznan"


def _parse_cenik(file_bytes: bytes, fname: str, ftype: str) -> tuple:
    """Router — prepozna dobavitelja iz vsebine dokumenta, ne iz imena datoteke."""
    ft  = ftype.lower()
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
    if "pdf" in ft:      ext = "pdf"
    elif "excel" in ft or "spreadsheet" in ft: ext = "xlsx"
    elif "csv" in ft:    ext = "csv"

    format_tip = _zaznaj_format(file_bytes, ext)

    if format_tip == "alemar_pdf":
        return _parse_alemar_pdf(file_bytes)
    elif format_tip == "fiorital_excel":
        return _parse_fiorital_excel(file_bytes, fname)
    elif format_tip == "pdf_neznan":
        return {}, "Neznan PDF format — pošlji vzorec cenika Gazdi da doda parser za tega dobavitelja."
    elif format_tip == "excel_neznan":
        return {}, "Neznan Excel format — pošlji vzorec cenika Gazdi da doda parser za tega dobavitelja."
    else:
        return {}, f"Neznan format: {fname}"

# ─── Kronološki filter ────────────────────────────────────────────────────────

def _najnovejsi_ceniki(ceniki_dob: list) -> list:
    po_dob: dict = {}
    for cenik in ceniki_dob:
        dob   = cenik.get("dobavitelj", "").strip().upper()
        kljuc = cenik.get("datum") or cenik.get("uvozeno", "")
        if dob and (dob not in po_dob or kljuc > po_dob[dob]["_kljuc"]):
            po_dob[dob] = {**cenik, "_kljuc": kljuc}
    return list(po_dob.values())

# ─── Analiza cen ─────────────────────────────────────────────────────────────

def _zberi_zgodovino_cen(tedni: list, trenutni_idx: int, n_tednov: int = 4) -> dict:
    pretekli_idx  = list(range(max(0, trenutni_idx - n_tednov), trenutni_idx))
    pretekle_cene: dict = {}
    for t_idx in pretekli_idx:
        for cenik in tedni[t_idx].get("ceniki_dob", []):
            for art in cenik.get("artikli", []):
                lat  = (art.get("latinski_naziv") or art.get("naziv","")).lower().strip()
                cena = float(art.get("cena", 0) or 0)
                if not lat or cena <= 0:
                    continue
                if lat not in pretekle_cene:
                    pretekle_cene[lat] = {}
                if t_idx not in pretekle_cene[lat] or cena < pretekle_cene[lat][t_idx]:
                    pretekle_cene[lat][t_idx] = cena
    trenutne: dict = {}
    for cenik in tedni[trenutni_idx].get("ceniki_dob", []):
        for art in cenik.get("artikli", []):
            lat  = (art.get("latinski_naziv") or art.get("naziv","")).lower().strip()
            cena = float(art.get("cena", 0) or 0)
            if not lat or cena <= 0:
                continue
            if lat not in trenutne or cena < trenutne[lat]["cena"]:
                trenutne[lat] = {
                    "cena": cena, "naziv": art.get("naziv_slo") or art.get("naziv", lat.title()),
                    "dobavitelj": cenik.get("dobavitelj",""),
                    "sklop": art.get("sklop","Divjaki"),
                    "podsklop": art.get("podsklop","Cele ribe"),
                    "poreklo": art.get("poreklo",""),
                }
    rezultat = {}
    for lat, curr in trenutne.items():
        hist = [pretekle_cene.get(lat,{}).get(t_idx, None) for t_idx in pretekli_idx]
        rezultat[lat] = {**curr, "hist": hist}
    return rezultat


def _izracunaj_trend(cena: float, hist: list) -> dict:
    cena_1t = next((c for c in reversed(hist) if c is not None), None)
    znane   = [c for c in hist if c is not None]
    avg_4t  = round(sum(znane)/len(znane), 4) if znane else None
    return {
        "trend_1t":  round((cena/cena_1t  - 1)*100, 1) if cena_1t  and cena_1t  > 0 else None,
        "trend_avg": round((cena/avg_4t   - 1)*100, 1) if avg_4t   and avg_4t   > 0 else None,
        "avg_4t": avg_4t, "cena_1t": cena_1t,
    }


def _trend_ikona(pct) -> str:
    if pct is None: return "—"
    if pct <= -10:  return f"🟢🟢 {pct:+.1f}%"
    if pct <    0:  return f"🟢 {pct:+.1f}%"
    if pct ==   0:  return f"⬜ {pct:+.1f}%"
    if pct <=   5:  return f"🔴 {pct:+.1f}%"
    return f"🔴🔴 {pct:+.1f}%"


def _render_analiza(tedni: list, trenutni_idx: int, teden_id: str):
    N = 4
    if len(tedni) < 2:
        st.info("Za analizo cen potrebuješ vsaj 2 tedna podatkov.")
        return
    zgodovina = _zberi_zgodovino_cen(tedni, trenutni_idx, N)
    if not zgodovina:
        st.info("V trenutnem tednu ni cenikov za analizo.")
        return
    pretekli_idx = list(range(max(0, trenutni_idx - N), trenutni_idx))
    hist_labeli  = ["—"] * (N - len(pretekli_idx)) + [_fmt_datum(tedni[i].get("datum_od","")) for i in pretekli_idx]

    col_f1, col_f2, col_f3 = st.columns([2, 2, 3])
    with col_f1:
        prag_push = st.number_input("Push lista prag %", value=-5.0, max_value=0.0, step=0.5,
                                     format="%.1f", key=f"prag_{teden_id}")
    with col_f2:
        filter_sklop = st.selectbox("Sklop", ["Vsi"] + SKLOPI, key=f"fsk_{teden_id}")
    with col_f3:
        pokazi_samo_spr = st.checkbox("Samo artikli s spremembo", value=False, key=f"samo_spr_{teden_id}")
    st.divider()

    def _sort_key(item):
        lat, d = item
        tr = _izracunaj_trend(d["cena"], d["hist"])
        return (SKLOPI.index(d["sklop"]) if d["sklop"] in SKLOPI else 99,
                tr["trend_avg"] if tr["trend_avg"] is not None else 999)

    sorted_items = sorted(zgodovina.items(), key=_sort_key)
    tab_hist, tab_push = st.tabs(["📈 Gibanje cen", "📣 Push lista"])

    with tab_hist:
        col_w = [2.5, 1.5, 1.2] + [1.0]*N + [1.2, 1.2, 1.2]
        cols_h = st.columns(col_w)
        for i, h in enumerate(["Artikel","Dobavitelj","Sklop"] + hist_labeli + ["Trenutna €","Trend (1t)","Trend (avg 4t)"]):
            cols_h[i].markdown(f"**{h}**")
        st.markdown("---")
        for lat, d in sorted_items:
            if filter_sklop != "Vsi" and d["sklop"] != filter_sklop:
                continue
            tr = _izracunaj_trend(d["cena"], d["hist"])
            if pokazi_samo_spr and tr["trend_1t"] is None and tr["trend_avg"] is None:
                continue
            cols_r = st.columns(col_w)
            cols_r[0].markdown(f"**{d['naziv']}**")
            cols_r[1].caption(d["dobavitelj"])
            cols_r[2].caption(f"{d['sklop']} / {d.get('podsklop','')}")
            hist_full = ([None]*(N - len(d["hist"]))) + d["hist"]
            for i, hc in enumerate(hist_full):
                cols_r[3+i].caption(f"{hc:.2f}" if hc is not None else "—")
            cols_r[3+N].markdown(f"**{d['cena']:.2f} €**")
            cols_r[3+N+1].caption(_trend_ikona(tr["trend_1t"]))
            cols_r[3+N+2].caption(_trend_ikona(tr["trend_avg"]))
        st.divider()
        st.caption("🟢🟢 padec >10%  ·  🟢 padec  ·  🔴 rast  ·  🔴🔴 rast >5%")

    with tab_push:
        teden_cur = next((t for t in tedni if t["id"] == teden_id), {})
        push_artikli = []
        for lat, d in sorted_items:
            if filter_sklop != "Vsi" and d["sklop"] != filter_sklop:
                continue
            tr = _izracunaj_trend(d["cena"], d["hist"])
            if tr["trend_avg"] is not None and tr["trend_avg"] <= prag_push:
                push_artikli.append((d, tr))
        if not push_artikli:
            st.info(f"Ni artiklov z avg trendom ≤ {prag_push:.0f}%.")
        else:
            ph = st.columns([3, 1.5, 1.2, 1.2, 1.5, 1.5])
            for col, h in zip(ph, ["Artikel","Dobavitelj","Trenutna €","Povp. 4t €","Trend (avg)","Trend (1t)"]):
                col.markdown(f"**{h}**")
            st.markdown("---")
            for d, tr in push_artikli:
                pc = st.columns([3, 1.5, 1.2, 1.2, 1.5, 1.5])
                pc[0].markdown(f"**{d['naziv']}**  \n*{d.get('sklop','')}*")
                pc[1].caption(d["dobavitelj"])
                pc[2].markdown(f"**{d['cena']:.2f} €**")
                pc[3].caption(f"{tr['avg_4t']:.2f} €" if tr["avg_4t"] else "—")
                pc[4].markdown(_trend_ikona(tr["trend_avg"]))
                pc[5].caption(_trend_ikona(tr["trend_1t"]))
            st.divider()
            lines = [
                f"🐟 TEDNA AKCIJA — POCENI RIBE ({_fmt_datum(teden_cur.get('datum_od','?'))} – {_fmt_datum(teden_cur.get('datum_do','?'))})", "",
            ]
            for d, tr in push_artikli:
                lines.append(f"✅ {d['naziv']}  {d['cena']:.2f} €/kg  ({_trend_ikona(tr['trend_avg'])} vs povp. {tr['avg_4t']:.2f} €)  — {d['dobavitelj']}")
            lines += ["", "Zaloge omejene. Za naročila nas kontaktirajte."]
            st.text_area("Besedilo za WhatsApp / email", value="\n".join(lines), height=200, key=f"push_txt_{teden_id}")

# ─── Naročilo dobavitelju ─────────────────────────────────────────────────────

def _render_narocilo(teden: dict, tedni: list):
    st.caption("Izberi artikle za naročilo — sistem grupira po dobaviteljih in pripravi dokumente.")
    ceniki_dob = teden.get("ceniki_dob", [])
    if not ceniki_dob:
        st.info("Najprej naloži cenike dobaviteljev.")
        return

    aktivni = _najnovejsi_ceniki(ceniki_dob)

    # ── Filtri ────────────────────────────────────────────────────────────
    nc1, nc2, nc3, nc4 = st.columns([3, 2, 2, 2])
    with nc1:
        iskanje_n      = st.text_input("🔍 Išči artikel", key=f"nar_isk_{teden['id']}", placeholder="npr. brancin...")
    with nc2:
        filter_dob_n   = st.selectbox("Dobavitelj", ["Vsi"] + [c["dobavitelj"] for c in aktivni], key=f"nar_dob_{teden['id']}")
    with nc3:
        filter_sklop_n = st.selectbox("Sklop", ["Vsi"] + SKLOPI, key=f"nar_sklop_{teden['id']}")
    with nc4:
        filter_ps_n    = st.selectbox("Tip", ["Vsi", "Cele ribe", "Fileji"], key=f"nar_ps_{teden['id']}")

    # ── Najugodnejši artikel po latinskem imenu (fallback: orig naziv) ───
    najboljsi: dict = {}
    for cenik in aktivni:
        dob = cenik.get("dobavitelj","")
        for art in cenik.get("artikli", []):
            cena = float(art.get("cena", 0) or 0)
            if cena <= 0:
                continue
            kljuc = (art.get("latinski_naziv") or art.get("naziv","")).lower().strip()
            if not kljuc:
                continue
            if kljuc not in najboljsi or cena < najboljsi[kljuc]["cena"]:
                najboljsi[kljuc] = {
                    "naziv_orig":     art.get("naziv",""),
                    "naziv_slo":      art.get("naziv_slo",""),
                    "latinski_naziv": art.get("latinski_naziv",""),
                    "cena":           cena,
                    "enota":          art.get("enota","kg"),
                    "poreklo":        art.get("poreklo",""),
                    "sklop":          art.get("sklop","Divjaki"),
                    "podsklop":       _dolocii_podsklop(art),
                    "dobavitelj":     dob,
                }

    # ── Filtriraj in sortiraj ─────────────────────────────────────────────
    filtrirani = []
    for art in najboljsi.values():
        if filter_dob_n != "Vsi" and art["dobavitelj"] != filter_dob_n:
            continue
        if filter_sklop_n != "Vsi" and art["sklop"] != filter_sklop_n:
            continue
        if filter_ps_n != "Vsi" and art["podsklop"] != filter_ps_n:
            continue
        naziv = art.get("naziv_slo") or art.get("naziv_orig","")
        if iskanje_n and iskanje_n.lower() not in naziv.lower() and iskanje_n.lower() not in art.get("naziv_orig","").lower():
            continue
        filtrirani.append(art)

    filtrirani.sort(key=lambda a: (
        SKLOPI.index(a["sklop"]) if a["sklop"] in SKLOPI else 99,
        PODSKOPI.index(a["podsklop"]) if a["podsklop"] in PODSKOPI else 99,
        (a.get("naziv_slo") or a.get("naziv_orig","")).lower()
    ))

    if not filtrirani:
        st.info("Ni artiklov za prikaz.")
        return

    # ── Izberi vse ────────────────────────────────────────────────────────
    master_nar = st.checkbox("☑ Izberi vse", key=f"nar_master_{teden['id']}")
    prev_mk    = f"nar_prev_m_{teden['id']}"
    prev_m     = st.session_state.get(prev_mk, None)
    if prev_m is not None and master_nar != prev_m:
        for i in range(len(filtrirani)):
            st.session_state[f"nar_sel_{teden['id']}_{i}"] = master_nar
    st.session_state[prev_mk] = master_nar
    st.markdown("---")

    # ── Tabela artiklov po sklopih/podsklopih ────────────────────────────
    # Količina je LEVO — minimalni premiki miške
    gh = st.columns([0.5, 0.7, 2.5, 2, 1.5, 1.5, 1, 1])
    for col, h in zip(gh, ["", "Kol.", "Orig. naziv", "SLO prevod", "Latinski naziv", "Dobavitelj", "Cena €", "Sklop/tip"]):
        col.markdown(f"**{h}**")
    st.markdown("---")

    cur_sklop, cur_ps = None, None
    izbrani = []
    for i, art in enumerate(filtrirani):
        sklop    = art["sklop"]
        podsklop = art["podsklop"]
        if sklop != cur_sklop or podsklop != cur_ps:
            if podsklop == "Fileji":
                sep = f"🔪 {sklop} — fileji"
            else:
                sep = f"{SKLOP_IKONA.get(sklop,'')} {sklop} — cele ribe"
            st.markdown(f"**{sep}**")
            cur_sklop, cur_ps = sklop, podsklop

        rc = st.columns([0.5, 0.7, 2.5, 2, 1.5, 1.5, 1, 1])
        sel = rc[0].checkbox("", key=f"nar_sel_{teden['id']}_{i}")
        kolicina = rc[1].number_input(
            "kol", min_value=0.0, value=0.0, step=1.0, format="%.0f",
            key=f"nar_kol_{teden['id']}_{i}", label_visibility="collapsed"
        )
        rc[2].caption(art["naziv_orig"])
        rc[3].caption(art.get("naziv_slo","—"))
        rc[4].caption(art.get("latinski_naziv","—"))
        rc[5].caption(art["dobavitelj"])
        rc[6].caption(f"{art['cena']:.2f} €")
        rc[7].caption(f"{'file' if podsklop=='Fileji' else 'cele'}")
        if sel:
            izbrani.append({**art, "kolicina": kolicina})

    st.markdown("---")
    if not izbrani:
        st.caption("Izberi artikle zgoraj za pripravo naročila.")
        return

    # ── Grupiraj po dobavitelju ───────────────────────────────────────────
    po_dob: dict = {}
    for art in izbrani:
        po_dob.setdefault(art["dobavitelj"], []).append(art)
    st.success(f"Izbrano: {len(izbrani)} artiklov pri {len(po_dob)} dobaviteljih")

    for dob, arts in po_dob.items():
        with st.expander(f"📄 Naročilo — {dob} ({len(arts)} artiklov)", expanded=True):
            # Prikaz v Streamlitu
            nh = st.columns([3.5, 2, 1, 1])
            for col, h in zip(nh, ["Orig. naziv", "Latinski naziv", "Kol.", "Enota"]):
                col.markdown(f"**{h}**")
            st.markdown("---")
            for art in arts:
                kol = float(art.get("kolicina") or 0)
                nc  = st.columns([3.5, 2, 1, 1])
                nc[0].write(art.get("naziv_orig",""))
                nc[1].caption(art.get("latinski_naziv",""))
                nc[2].write(f"{kol:.1f}")
                nc[3].caption(art.get("enota","kg"))
            st.markdown("---")

            # Excel — samo orig naziv, latinski naziv, količina
            try:
                import pandas as pd, io
                df_nar = pd.DataFrame([{
                    "Naziv":           a.get("naziv_orig",""),
                    "Latinski naziv":  a.get("latinski_naziv",""),
                    "Količina":        float(a.get("kolicina") or 0),
                    "Enota":           a.get("enota","kg"),
                } for a in arts])
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    df_nar.to_excel(writer, index=False, sheet_name="Narocilo")
                    ws = writer.sheets["Narocilo"]
                    for col_l, w in zip(["A","B","C","D"], [38, 22, 12, 8]):
                        ws.column_dimensions[col_l].width = w
                st.download_button(
                    f"⬇️ Naročilo — {dob}",
                    data=buf.getvalue(),
                    file_name=f"narocilo_{dob.replace(' ','_')}_{teden['datum_od']}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_nar_{teden['id']}_{dob}",
                )
            except ImportError:
                st.warning("Manjka pandas/openpyxl.")

def _auto_prevedi_cenik(nas_cenik: dict, tid: str, ime_cenika: str, tedni: list) -> bool:
    """Samodejno prevede vse artikle brez naziv_slo. Vrne True če je kaj prevedel."""
    # Zberi vse neprevedene
    neprevedeni_art = []
    lokacije = []  # (sklop, podsklop, idx)
    for sklop in SKLOPI:
        sklop_data = nas_cenik.get(sklop, {})
        if isinstance(sklop_data, list):
            continue
        for ps in PODSKOPI:
            for idx, art in enumerate(sklop_data.get(ps, [])):
                naziv_slo = (art.get("naziv_slo","") or "").strip()
                naziv_orig = (art.get("naziv","") or "").strip()
                # Prevedi če: prazno, ali enako kot original
                if not naziv_slo or naziv_slo == naziv_orig:
                    neprevedeni_art.append(art)
                    lokacije.append((sklop, ps, idx))

    if not neprevedeni_art:
        return False

    try:
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY","")
        if not api_key:
            return False
        client = anthropic.Anthropic(api_key=api_key)
        seznam = "\n".join([
            f"{i+1}. {a.get('naziv','')} (lat: {a.get('latinski_naziv','')})"
            for i, a in enumerate(neprevedeni_art)
        ])
        prompt = f"""Prevedi nazive rib in morskih sadežev v slovenščino. Kratek, jasen prevod.

Slovar: Šarun=Šur, Totano=Liganj, Anello=Obroček, Ricciola=Pisana limača,
Ombrina=Senčar, Pagello=Rdeči ribon, Dentice=Zobatec, Spigola/Branzino=Brancin,
Orata=Orada, Sgombro=Skuša, Acciuga=Sardon, Cefalo=Cipal, Rombo=Morska plošča,
Astice=Jastog, Coda di rospo=Rep morskega vraga, Anguilla=Jegulja,
Merluzzo=Oslič, Salmone=Losos, Trota=Postrv, Polpo=Hobotnica, Seppia=Sipa,
Calamaro=Liganj, Vongole=Kočice, Cozze=Klapavice, Capasanta=Pokrovača,
Gamberi=Kozice, Scampi=Škampi, Aragosta=Jastog, Filone=Filon,
Trancio=Tranča, Arrosto=Pečenka, Merluzzo=Oslič, Pesce spada=Mečarica,
Tonno=Tun, Halibut=Morska plošča, Salmone=Losos, SUP=vrhunski

Vrni SAMO JSON, brez markdown:
[{{"idx": 1, "naziv_slo": "prevod"}}, ...]

Artikli:
{seznam}"""
        resp = client.messages.create(
            model="claude-opus-4-6", max_tokens=4096,
            messages=[{"role":"user","content":prompt}]
        )
        raw = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
        prevodi = json.loads(raw)
        prevodi_map = {p["idx"]: p.get("naziv_slo","") for p in prevodi}
        for i, art in enumerate(neprevedeni_art):
            prevod = prevodi_map.get(i+1,"").strip()
            if prevod:
                art["naziv_slo"] = prevod
        return True
    except Exception:
        return False




def _ai_povezi_artikle(artikli: list) -> list:
    """
    AI poveže iste artikle od različnih dobaviteljev v grupe.
    Vrne seznam grup — vsaka grupa je seznam artiklov ki predstavljajo isti produkt.
    Kjer AI ni siguren, pusti artikel v svoji grupi.
    """
    if not artikli:
        return []
    try:
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY","")
        if not api_key:
            return [[a] for a in artikli]
        seznam = "\n".join([
            f"{i}: [{a['dobavitelj']}] {a['naziv']} | lat: {a.get('latinski_naziv','')} | {a['cena']:.2f}€"
            for i, a in enumerate(artikli)
        ])
        prompt = f"""Imaš seznam artiklov rib od različnih dobaviteljev. Poveži artikle ki so ISTI produkt v grupe.

PRAVILA:
- Isti artikel = ista vrsta ribe + podobna velikost/teža + ista oblika (cela riba, file, obroček...)
- Različne velikosti so RAZLIČNI artikli (Brancin 200/300 ≠ Brancin 600/800)
- Če nisi siguren → pusti v svoji grupi (seznam z enim elementom)
- Latinski naziv je zanesljiv pokazatelj vrste

Vrni SAMO JSON brez markdown:
{{"grupe": [[0,3,7],[1],[2,5],[4],[6]]}}

Vsaka podlista = indeksi artiklov ki so isti produkt.

Artikli:
{seznam}"""
        client = anthropic.Anthropic(api_key=api_key)
        resp   = client.messages.create(
            model="claude-opus-4-6", max_tokens=4096,
            messages=[{"role":"user","content":prompt}]
        )
        raw    = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
        result = json.loads(raw)
        grupe_idx = result.get("grupe", [])
        grupe = []
        pokrite = set()
        for grupa_idx in grupe_idx:
            grupa = []
            for idx in grupa_idx:
                if 0 <= idx < len(artikli):
                    grupa.append(artikli[idx])
                    pokrite.add(idx)
            if grupa:
                grupe.append(grupa)
        # Nepokrite → svoja grupa
        for i, art in enumerate(artikli):
            if i not in pokrite:
                grupe.append([art])
        return grupe
    except Exception:
        return [[a] for a in artikli]


def _render_nas_cenik(ime_cenika: str, teden: dict, tedni: list):
    nas_cenik = teden["nasi_ceniki"][ime_cenika]
    nas_cenik = _migracija_stari_format(nas_cenik)
    nas_cenik = _prerazporedi_podskope(nas_cenik)
    teden["nasi_ceniki"][ime_cenika] = nas_cenik
    logo_b64  = _logo_b64()
    tid       = teden["id"]

    # ── Apliciranje skupinske marže iz session_state ─────────────────────
    for sklop in SKLOPI:
        for podsklop in PODSKOPI:
            sm_key = f"skupna_marza_{tid}_{ime_cenika}_{sklop}_{podsklop}"
            m = st.session_state.get(sm_key, 0.0)
            if m and m > 0:
                artikli_sm = nas_cenik.get(sklop,{}).get(podsklop,[])
                arts_sm    = sorted(artikli_sm, key=lambda a: (a.get("naziv_slo") or a.get("naziv","")).lower())
                for a_idx, art in enumerate(arts_sm):
                    nc_v = float(art.get("cena",0))
                    if nc_v > 0:
                        pc   = round(nc_v*(1+m/100), 2)
                        art["marza_pct"]     = m
                        art["cena_prodajna"] = pc
                        # Posodobi session_state polj da se osvežijo v UI
                        uid = f"{tid}_{ime_cenika}_{sklop}_{podsklop}_{a_idx}"
                        st.session_state[f"marza_{uid}"] = float(m)
                        st.session_state[f"prod_{uid}"]  = float(pc)

    # ── Apliciranje posameznih marž iz session_state ─────────────────────
    for sklop in SKLOPI:
        sklop_data = nas_cenik.get(sklop,{})
        if isinstance(sklop_data, list):
            continue
        for podsklop in PODSKOPI:
            artikli = sklop_data.get(podsklop,[])
            arts_s  = sorted(artikli, key=lambda a: (a.get("naziv_slo") or a.get("naziv","")).lower())
            for a_idx, art in enumerate(arts_s):
                uid    = f"{tid}_{ime_cenika}_{sklop}_{podsklop}_{a_idx}"
                nc_key = f"cena_{uid}"
                m_key  = f"marza_{uid}"
                pc_key = f"prod_{uid}"
                # NC sprememba
                if nc_key in st.session_state:
                    new_nc = float(st.session_state[nc_key])
                    if new_nc != float(art.get("cena",0)):
                        art["cena"] = new_nc
                        m = float(art.get("marza_pct",0))
                        if new_nc > 0 and m > 0:
                            art["cena_prodajna"] = round(new_nc*(1+m/100), 2)
                # Marža sprememba
                if m_key in st.session_state:
                    new_m = float(st.session_state[m_key])
                    if new_m != float(art.get("marza_pct",0)):
                        art["marza_pct"] = new_m
                        nc_v = float(art.get("cena",0))
                        if nc_v > 0:
                            art["cena_prodajna"] = round(nc_v*(1+new_m/100), 2)
                # PC sprememba
                if pc_key in st.session_state:
                    new_pc = float(st.session_state[pc_key])
                    if new_pc != float(art.get("cena_prodajna",0)):
                        art["cena_prodajna"] = new_pc
                        nc_v = float(art.get("cena",0))
                        if nc_v > 0 and new_pc > 0:
                            art["marza_pct"] = round((new_pc/nc_v - 1)*100, 1)

    # Shrani po aplikaciji
    st.session_state["ceniki_tedni"] = tedni
    _save_ceniki(tedni)

    # ── Avtomatsko prevajanje ob prvem prikazu ───────────────────────────
    prevedi_key = f"prevedeno_{tid}_{ime_cenika}"
    if not st.session_state.get(prevedi_key, False):
        with st.spinner("🌐 Prevajam nazive..."):
            if _auto_prevedi_cenik(nas_cenik, tid, ime_cenika, tedni):
                st.session_state["ceniki_tedni"] = tedni
                _save_ceniki(tedni)
        st.session_state[prevedi_key] = True

    # ── Iskalnik + filter ────────────────────────────────────────────────
    sc1, sc2, sc3 = st.columns([3, 2, 2])
    with sc1:
        iskanje  = st.text_input("🔍 Išči artikel", key=f"isk_{tid}_{ime_cenika}", placeholder="npr. brancin...")
    with sc2:
        filter_s = st.selectbox("Sklop", ["Vsi"] + SKLOPI, key=f"fs_{tid}_{ime_cenika}")
    with sc3:
        filter_ps = st.selectbox("Tip", ["Vsi", "Cele ribe", "Fileji"], key=f"fps_{tid}_{ime_cenika}")

    st.markdown("---")

    st.caption("🤖 Samodejno sestavi: vzame vse artikle, med dobavitelji izbere najugodnejšo ceno za isti artikel.")
    if st.button(f"🤖 Samodejno sestavi {ime_cenika}",
                 key=f"auto_{tid}_{ime_cenika}",
                 disabled=not teden.get("ceniki_dob")):
        aktivni = _najnovejsi_ceniki(teden["ceniki_dob"])
        vse: dict = {}
        for cenik in aktivni:
            dob = cenik.get("dobavitelj","")
            for art in cenik.get("artikli",[]):
                cena = float(art.get("cena",0) or 0)
                if cena <= 0:
                    continue  # ni dobavljivo
                naziv = (art.get("naziv","") or "").strip()
                if not naziv:
                    continue

                # Ključ = latinski naziv + poreklo + velikost iz naziva
                # Tako: Brancin 200/300 Grčija ≠ Brancin 200/300 Hrvaška (različna)
                #       Brancin 200/300 Grčija od Alemarja = Brancin 200/300 Grčija od Fioritala (isti → cenejši)
                lat     = (art.get("latinski_naziv","") or "").lower().strip()
                poreklo = (art.get("poreklo","") or "").upper().strip()
                # Izvleci velikostni razred iz naziva (npr. "200/300", "1000/1500", "4/5")
                import re as _re
                velikost = "/".join(_re.findall(r'\d+', naziv))
                kljuc = f"{lat}|{poreklo}|{velikost}" if lat else f"{naziv.upper()}|{poreklo}"

                if kljuc not in vse or cena < float(vse[kljuc]["cena"]):
                    vse[kljuc] = {
                        "naziv":          naziv,
                        "naziv_slo":      art.get("naziv_slo","") or naziv,
                        "latinski_naziv": art.get("latinski_naziv",""),
                        "cena":           cena,
                        "enota":          art.get("enota","kg"),
                        "poreklo":        art.get("poreklo",""),
                        "sklop":          art.get("sklop","Divjaki"),
                        "podsklop":       _dolocii_podsklop(art),
                        "cena_prodajna":  0.0,
                        "marza_pct":      0.0,
                        "dobavitelj":     dob,
                    }

        nas_cenik = _prazen_nas_cenik()
        for art_data in vse.values():
            sklop    = art_data.get("sklop","Divjaki")
            podsklop = art_data.get("podsklop","Cele ribe")
            if sklop    not in SKLOPI:    sklop    = "Divjaki"
            if podsklop not in PODSKOPI:  podsklop = "Cele ribe"
            nas_cenik[sklop][podsklop].append(art_data)
        teden["nasi_ceniki"][ime_cenika] = nas_cenik
        st.session_state.pop(f"prevedeno_{tid}_{ime_cenika}", None)
        st.session_state["ceniki_tedni"] = tedni
        _save_ceniki(tedni)
        st.rerun()

    # ── Ročno dodajanje ──────────────────────────────────────────────────
    with st.expander("➕ Ročno dodaj artikel", expanded=False):
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            r_naziv  = st.text_input("SLO naziv", key=f"rn_{tid}_{ime_cenika}")
            r_lat    = st.text_input("Latinski naziv", key=f"rl_{tid}_{ime_cenika}")
        with rc2:
            r_cena   = st.number_input("Nakupna €/kg", min_value=0.0, step=0.01, key=f"rc_{tid}_{ime_cenika}")
            r_prod   = st.number_input("Prodajna €/kg", min_value=0.0, step=0.01, key=f"rp_{tid}_{ime_cenika}")
        with rc3:
            r_sklop  = st.selectbox("Sklop", SKLOPI, key=f"rs_{tid}_{ime_cenika}")
            r_ps     = st.selectbox("Podsklop", PODSKOPI, key=f"rps_{tid}_{ime_cenika}")
            r_por    = st.text_input("Poreklo (ISO)", key=f"ro_{tid}_{ime_cenika}")
            r_dob    = st.text_input("Dobavitelj", key=f"rd_{tid}_{ime_cenika}")
        if st.button("Dodaj", key=f"radd_{tid}_{ime_cenika}") and r_naziv:
            nas_cenik[r_sklop][r_ps].append({
                "naziv_slo": r_naziv, "naziv": r_naziv,
                "latinski_naziv": r_lat, "cena": r_cena,
                "cena_prodajna": r_prod,
                "marza_pct": round((r_prod/r_cena - 1)*100, 1) if r_cena > 0 else 0,
                "enota": "kg", "poreklo": r_por, "sklop": r_sklop, "podsklop": r_ps,
                "dobavitelj": r_dob,
            })
            st.session_state["ceniki_tedni"] = tedni
            _save_ceniki(tedni)
            st.rerun()

    # ── Prikaz po sklopih / podsklopih ──────────────────────────────────
    total_art = sum(
        len(nas_cenik.get(s,{}).get(ps,[]))
        for s in SKLOPI for ps in PODSKOPI
    )
    if total_art == 0:
        st.info("Cenik je prazen. Uporabi 'Samodejno sestavi' ali dodaj ročno.")
        return

    vse_cene_cache: dict = {}
    for sklop in SKLOPI:
        if filter_s != "Vsi" and sklop != filter_s:
            continue
        sklop_data = nas_cenik.get(sklop, {})
        if isinstance(sklop_data, list):
            sklop_data = {"Cele ribe": sklop_data}

        for podsklop in PODSKOPI:
            if filter_ps != "Vsi" and podsklop != filter_ps:
                continue
            artikli_sklop = sklop_data.get(podsklop, [])
            artikli_sort  = sorted(
                artikli_sklop,
                key=lambda a: (a.get("naziv_slo") or a.get("naziv","")).lower()
            )
            if iskanje:
                artikli_sort = [
                    a for a in artikli_sort
                    if iskanje.lower() in (a.get("naziv_slo") or a.get("naziv","")).lower()
                    or iskanje.lower() in a.get("naziv","").lower()
                ]
            if not artikli_sort:
                continue

            # Header podsklopa
            if podsklop == "Fileji":
                ps_label = f"🔪 {sklop} — fileji"
            else:
                ps_label = f"{SKLOP_IKONA.get(sklop,'')} {sklop} — cele ribe"
            st.markdown(f"#### {ps_label}")

            # Skupinska marža + glava tabele z izvoz checkboxom
            sm_key = f"skupna_marza_{tid}_{ime_cenika}_{sklop}_{podsklop}"
            # Izberi vse za izvoz v tem podsklopu
            master_izvoz_key = f"izvoz_master_{tid}_{ime_cenika}_{sklop}_{podsklop}"
            prev_mik = f"izvoz_prev_{tid}_{ime_cenika}_{sklop}_{podsklop}"
            h0,h1,h2,h3,h4,h5,h6,h7,h8 = st.columns([0.5,2.5,2,1.5,1.2,1.2,1.2,1.5,0.5])
            with h0:
                master_izvoz = st.checkbox("☑", key=master_izvoz_key,
                                           help="Izberi vse za izvoz")
                prev_mi = st.session_state.get(prev_mik, None)
                if prev_mi is not None and master_izvoz != prev_mi:
                    for ai in range(len(artikli_sort)):
                        st.session_state[f"izvoz_sel_{tid}_{ime_cenika}_{sklop}_{podsklop}_{ai}"] = master_izvoz
                st.session_state[prev_mik] = master_izvoz
            h1.markdown("**SLO naziv**")
            h2.markdown("**Latinski naziv**")
            h3.markdown("**Poreklo**")
            h4.markdown("**Nakupna €**")
            with h5:
                st.number_input(
                    "Marža %", min_value=0.0, max_value=500.0,
                    value=0.0, step=0.5, format="%.1f",
                    key=sm_key,
                    help="Skupna marža za vse v tem sklopu — vpišeš in pritisni Enter"
                )
            h6.markdown("**Prod. €**")
            h7.markdown("**Dobavitelj ↙**")
            h8.markdown("")
            st.markdown("---")

            for a_idx, art in enumerate(artikli_sort):
                lat_key = (art.get("latinski_naziv") or art.get("naziv","")).lower().strip()
                if lat_key not in vse_cene_cache:
                    prim = []
                    for cenik in teden.get("ceniki_dob",[]):
                        for a2 in cenik.get("artikli",[]):
                            l2 = (a2.get("latinski_naziv") or a2.get("naziv","")).lower().strip()
                            if l2 == lat_key:
                                prim.append(f"{cenik['dobavitelj']}: {a2.get('cena',0):.2f} €")
                    vse_cene_cache[lat_key] = prim
                prim = vse_cene_cache[lat_key]
                uid  = f"{tid}_{ime_cenika}_{sklop}_{podsklop}_{a_idx}"
                c0,c1,c2,c3,c4,c5,c6,c7,c8 = st.columns([0.5,2.5,2,1.5,1.2,1.2,1.2,1.5,0.5])
                with c0:
                    st.checkbox("", key=f"izvoz_sel_{tid}_{ime_cenika}_{sklop}_{podsklop}_{a_idx}",
                                help="Vključi v izvoz za stranke")
                with c1:
                    naziv_val = art.get("naziv_slo") or art.get("naziv","")
                    art["naziv_slo"] = st.text_input(
                        "slo", value=naziv_val,
                        key=f"nslo_{uid}", label_visibility="collapsed")
                with c2:
                    st.caption(art.get("latinski_naziv","—"))
                with c3:
                    st.caption(art.get("poreklo","—"))
                with c4:
                    st.number_input("nc", value=float(art.get("cena",0)), min_value=0.0,
                        format="%.2f", key=f"cena_{uid}", label_visibility="collapsed")
                with c5:
                    st.number_input("m", value=float(art.get("marza_pct",0)), min_value=0.0,
                        max_value=500.0, format="%.1f", key=f"marza_{uid}", label_visibility="collapsed")
                with c6:
                    st.number_input("pc", value=float(art.get("cena_prodajna",0)), min_value=0.0,
                        format="%.2f", key=f"prod_{uid}", label_visibility="collapsed")
                with c7:
                    dob = art.get("dobavitelj","")
                    if prim and len(prim) > 1:
                        st.caption(f"✅ {dob}", help="\n".join(prim))
                    else:
                        st.caption(dob)
                with c8:
                    if st.button("✕", key=f"rm_{uid}", help="Odstrani"):
                        art_id = id(art)
                        orig   = next((i for i,a in enumerate(artikli_sklop) if id(a)==art_id), None)
                        if orig is not None:
                            artikli_sklop.pop(orig)
                        st.session_state["ceniki_tedni"] = tedni
                        _save_ceniki(tedni)
                        st.rerun()

    if st.button(f"💾 Shrani {ime_cenika}", key=f"save_{tid}_{ime_cenika}",
                 type="primary", use_container_width=True):
        st.session_state["ceniki_tedni"] = tedni
        _save_ceniki(tedni)
        st.success("Shranjeno.")

    # ── Izvoz cenika za stranke ──────────────────────────────────────────
    st.divider()
    st.markdown("**Izvoz cenika za stranke**")
    st.caption("Artikle za izvoz označi z ☑ v tabeli zgoraj.")

    # Zberi izbrane artikle iz checkboxev v tabeli
    izbrani_izvoz = []
    for sklop in SKLOPI:
        sklop_data = nas_cenik.get(sklop, {})
        if isinstance(sklop_data, list):
            sklop_data = {"Cele ribe": sklop_data}
        for podsklop in PODSKOPI:
            arts = sorted(sklop_data.get(podsklop,[]),
                          key=lambda a: (a.get("naziv_slo") or a.get("naziv","")).lower())
            for a_idx, art in enumerate(arts):
                sel_key = f"izvoz_sel_{tid}_{ime_cenika}_{sklop}_{podsklop}_{a_idx}"
                if st.session_state.get(sel_key, False):
                    izbrani_izvoz.append((sklop, podsklop, art))

    n_izbranih = len(izbrani_izvoz)
    if n_izbranih == 0:
        st.caption("Ni izbranih artiklov za izvoz.")
        return
    else:
        st.caption(f"Izbrano za izvoz: {n_izbranih} artiklov")

    # HTML — samo SLO naziv, latinski naziv, PV
    html_vsebina = _glava_html(
        f"Cenik {ime_cenika}",
        f"{_fmt_datum(teden['datum_od'])} – {_fmt_datum(teden['datum_do'])} &nbsp;·&nbsp; Cene brez DDV &nbsp;·&nbsp; €/kg",
        logo_b64
    )
    for sklop in SKLOPI:
        for podsklop in PODSKOPI:
            arts_s = sorted(
                [a for s,ps,a in izbrani_izvoz if s==sklop and ps==podsklop],
                key=lambda a: (a.get("naziv_slo") or a.get("naziv","")).lower()
            )
            if arts_s:
                naziv_sek = f"{sklop} — fileji" if podsklop == "Fileji" else f"{sklop} — cele ribe"
                html_vsebina += _sklop_html_izvoz(naziv_sek, arts_s)
    html_vsebina += ('<div style="border-top:0.5px solid #ddd;padding-top:5px;'
                     'display:flex;justify-content:space-between;margin-top:8px;">'
                     '<div style="font-size:9px;color:#aaa;">Oltre Con d.o.o. · Orehovlje 2/f, 5291 Miren · SI19211210</div>'
                     '<div style="font-size:9px;color:#aaa;">1/1</div></div>')
    html_full = (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
                 f'<style>body{{font-family:Arial,sans-serif;font-size:11px;color:#222;margin:20px 40px;}}'
                 f'*{{box-sizing:border-box;}}</style></head><body>{html_vsebina}</body></html>')

    col_h, col_x = st.columns(2)
    with col_h:
        st.download_button("⬇️ Prenesi HTML cenik", data=html_full.encode("utf-8"),
            file_name=f"cenik_{ime_cenika}_{teden['datum_od']}.html", mime="text/html",
            key=f"dl_html_{tid}_{ime_cenika}")
    with col_x:
        try:
            import pandas as pd, io
            vrstice_xl = [{
                "Naziv":          a.get("naziv_slo") or a.get("naziv",""),
                "Latinski naziv": a.get("latinski_naziv",""),
                "Cena €/kg":      float(a.get("cena_prodajna") or a.get("cena") or 0),
            } for s,ps,a in izbrani_izvoz]
            df_xl = pd.DataFrame(vrstice_xl)
            buf_xl = io.BytesIO()
            with pd.ExcelWriter(buf_xl, engine="openpyxl") as writer:
                df_xl.to_excel(writer, index=False, sheet_name=f"Cenik {ime_cenika}")
                ws = writer.sheets[f"Cenik {ime_cenika}"]
                for col_l, w in zip(["A","B","C"], [40, 24, 12]):
                    ws.column_dimensions[col_l].width = w
            st.download_button("⬇️ Prenesi Excel cenik", data=buf_xl.getvalue(),
                file_name=f"cenik_{ime_cenika}_{teden['datum_od']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_xl_{tid}_{ime_cenika}")
        except ImportError:
            st.warning("Manjka pandas/openpyxl.")

# ─── RENDER ──────────────────────────────────────────────────────────────────

def render():
    st.caption("Tedni ceniki dobaviteljev → HIT / HoReCa")

    if "ceniki_tedni" not in st.session_state:
        st.session_state["ceniki_tedni"] = _load_ceniki()
    tedni: list = st.session_state["ceniki_tedni"]

    with st.sidebar:
        st.header("⚙️ Nov teden")
        col_a, col_b = st.columns(2)
        with col_a:
            d_od = st.date_input("Od", value=date.today(), key="nt_od", format="DD.MM.YYYY")
        with col_b:
            d_do = st.date_input("Do", value=date.today(), key="nt_do", format="DD.MM.YYYY")
        if st.button("➕ Ustvari nov teden", use_container_width=True, key="btn_nov_teden"):
            nov = _nov_teden(_parse_datum_input(d_od), _parse_datum_input(d_do))
            tedni.append(nov)
            tedni.sort(key=lambda t: t.get("datum_od",""))
            st.session_state["ceniki_tedni"] = tedni
            _save_ceniki(tedni)
            st.rerun()
        st.divider()
        st.caption(f"Skupaj tednov: {len(tedni)}")
        if tedni:
            st.markdown("**Tedni:**")
            for t in tedni:
                sc1, sc2 = st.columns([5, 1])
                with sc1:
                    st.caption(f"📅 {_fmt_datum(t['datum_od'])} – {_fmt_datum(t['datum_do'])}")
                with sc2:
                    if st.button("✕", key=f"sb_del_{t['id']}", help="Izbriši teden"):
                        tedni = [x for x in tedni if x["id"] != t["id"]]
                        st.session_state["ceniki_tedni"] = tedni
                        _save_ceniki(tedni)
                        st.rerun()

    if not tedni:
        st.info("Še ni tednov. Ustvari prvi teden v stranskem meniju.")
        return

    for t_idx, teden in enumerate(tedni):
        # Zagotovi da ima teden nov format + prerazporedi podskope
        for ime in NASI_CENIKI:
            if ime not in teden.get("nasi_ceniki", {}):
                teden.setdefault("nasi_ceniki", {})[ime] = _prazen_nas_cenik()
            else:
                nc = _migracija_stari_format(teden["nasi_ceniki"][ime])
                teden["nasi_ceniki"][ime] = nc

        # Popravi podsklop tudi v ceniki dobaviteljev
        for cenik in teden.get("ceniki_dob", []):
            for art in cenik.get("artikli", []):
                art["podsklop"] = _dolocii_podsklop(art)

        st_info    = _prestej_artiklov(teden)
        teden_label = (
            f"📅 {_fmt_datum(teden['datum_od'])} – {_fmt_datum(teden['datum_do'])}  ·  "
            f"{len(teden.get('ceniki_dob',[]))} dobaviteljev  ·  "
            f"{st_info['dobavitelji']} artiklov  ·  "
            f"HIT: {st_info.get('HIT',0)}  HoReCa: {st_info.get('HoReCa',0)}"
        )

        with st.expander(teden_label, expanded=(t_idx == len(tedni)-1)):
            st.caption(f"ID: {teden['id']}  ·  Ustvarjen: {_fmt_datum(teden.get('ustvarjen','?'))}")

            tab_dob, tab_hit, tab_horeca, tab_narocilo, tab_analiza = st.tabs([
                "📥 Ceniki dobaviteljev", "⭐ HIT", "🍽️ HoReCa",
                "📋 Naročilo dobavitelju", "📊 Analiza cen",
            ])

            with tab_dob:
                _tid = teden["id"]
                _up_n = st.session_state.get(f"up_reset_{_tid}", 0)
                nalozene = st.file_uploader(
                    "Naloži cenike dobaviteljev (PDF, Excel, CSV)",
                    type=["pdf","xlsx","xls","csv"],
                    accept_multiple_files=True,
                    key=f"up_{_tid}_{_up_n}",
                    label_visibility="collapsed",
                )
                if nalozene:
                    prog = st.progress(0)
                    napake, uspesni = [], []
                    for i, f in enumerate(nalozene):
                        prog.progress((i+1)/len(nalozene), text=f"Berem {f.name} …")
                        try:
                            parsed, err = _parse_cenik(f.read(), f.name, f.type)
                        except Exception as ex:
                            err, parsed = str(ex), {}
                        if err or not parsed:
                            napake.append(f"❌ **{f.name}**: {err or 'AI ni vrnil podatkov'}")
                            continue
                        dob_ime   = parsed.get("dobavitelj", f.name)
                        dob_datum = parsed.get("datum","")
                        teden["ceniki_dob"].append({
                            "id": str(uuid.uuid4())[:8], "dobavitelj": dob_ime,
                            "datum": dob_datum, "valuta": parsed.get("valuta","EUR"),
                            "fname": f.name, "artikli": parsed.get("artikli",[]),
                            "uvozeno": datetime.now().isoformat()[:16],
                        })
                        uspesni.append(f"✅ **{dob_ime}** ({_fmt_datum(dob_datum) or 'brez datuma'}): {len(parsed.get('artikli',[]))} artiklov")
                    prog.empty()
                    for msg in uspesni: st.success(msg)
                    for msg in napake:  st.error(msg)
                    if uspesni:
                        st.session_state[f"up_reset_{_tid}"] = _up_n + 1
                        st.session_state["ceniki_tedni"] = tedni
                        _save_ceniki(tedni)
                        st.rerun()
                    elif napake:
                        st.session_state[f"up_reset_{_tid}"] = _up_n + 1
                        st.stop()

                if not teden.get("ceniki_dob"):
                    st.caption("Naloži PDF/Excel/CSV cenike dobaviteljev z gumbom zgoraj.")
                else:
                    for cenik in teden["ceniki_dob"]:
                        c_label = (f"🏭 **{cenik['dobavitelj']}**  ·  "
                                   f"{_fmt_datum(cenik.get('datum','')) or '—'}  ·  "
                                   f"{len(cenik.get('artikli',[]))} artiklov  ·  `{cenik.get('fname','')}`")
                        col_exp, col_rm = st.columns([11, 1])
                        with col_rm:
                            if st.button("✕", key=f"rm_dob_{_tid}_{cenik['id']}"):
                                teden["ceniki_dob"] = [c for c in teden["ceniki_dob"] if c["id"] != cenik["id"]]
                                st.session_state["ceniki_tedni"] = tedni
                                _save_ceniki(tedni)
                                st.rerun()
                        with col_exp:
                            with st.expander(c_label, expanded=False):
                                artikli = cenik.get("artikli",[])
                                if not artikli:
                                    st.caption("Ni artiklov.")
                                else:
                                    artikli_sort = sorted(artikli, key=lambda a: (
                                        SKLOPI.index(a.get("sklop","Divjaki")) if a.get("sklop","Divjaki") in SKLOPI else 99,
                                        PODSKOPI.index(a.get("podsklop","Cele ribe")) if a.get("podsklop","Cele ribe") in PODSKOPI else 99,
                                        a.get("naziv","").lower()
                                    ))
                                    hh = st.columns([2.5, 2, 2, 1.5, 1.2, 1, 1.2])
                                    for col, h in zip(hh, ["Orig. naziv","SLO prevod","Latinski naziv","Poreklo","Cena €/kg","Sklop","Podsklop"]):
                                        col.markdown(f"**{h}**")
                                    st.markdown("---")
                                    cur_sklop, cur_ps = None, None
                                    for a_idx, art in enumerate(artikli_sort):
                                        sklop    = art.get("sklop","Divjaki")
                                        podsklop = art.get("podsklop","Cele ribe")
                                        if sklop != cur_sklop or podsklop != cur_ps:
                                            if podsklop == "Fileji":
                                                sep_label = f"🔪 {sklop} — fileji"
                                            else:
                                                sep_label = f"{SKLOP_IKONA.get(sklop,'')} {sklop} — cele ribe"
                                            st.markdown(f"**{sep_label}**")
                                            cur_sklop, cur_ps = sklop, podsklop
                                        orig_idx = next((i for i,a in enumerate(artikli) if id(a)==id(art)), a_idx)
                                        ac = st.columns([2.5,2,2,1.5,1.2,1,1.2])
                                        art["naziv"]     = ac[0].text_input("Orig", value=art.get("naziv",""), key=f"an_{_tid}_{cenik['id']}_{orig_idx}", label_visibility="collapsed")
                                        art["naziv_slo"] = ac[1].text_input("SLO",  value=art.get("naziv_slo",""), key=f"aslo_{_tid}_{cenik['id']}_{orig_idx}", label_visibility="collapsed", placeholder="slo prevod...")
                                        ac[2].caption(art.get("latinski_naziv","—"))
                                        ac[3].caption(art.get("poreklo","—"))
                                        art["cena"]   = ac[4].number_input("€", value=float(art.get("cena",0)), min_value=0.0, format="%.2f", key=f"ac_{_tid}_{cenik['id']}_{orig_idx}", label_visibility="collapsed")
                                        cur_s  = art.get("sklop","Divjaki")
                                        cur_ps2 = art.get("podsklop","Cele ribe")
                                        art["sklop"]    = ac[5].selectbox("Sklop", SKLOPI, index=SKLOPI.index(cur_s) if cur_s in SKLOPI else 1, key=f"as_{_tid}_{cenik['id']}_{orig_idx}", label_visibility="collapsed")
                                        art["podsklop"] = ac[6].selectbox("PS", PODSKOPI, index=PODSKOPI.index(cur_ps2) if cur_ps2 in PODSKOPI else 0, key=f"aps_{_tid}_{cenik['id']}_{orig_idx}", label_visibility="collapsed")
                                    if st.button("💾 Shrani popravke", key=f"save_dob_{_tid}_{cenik['id']}"):
                                        st.session_state["ceniki_tedni"] = tedni
                                        _save_ceniki(tedni)
                                        st.success("Shranjeno.")

            with tab_hit:
                _render_nas_cenik("HIT", teden, tedni)
            with tab_horeca:
                _render_nas_cenik("HoReCa", teden, tedni)
            with tab_narocilo:
                _render_narocilo(teden, tedni)
            with tab_analiza:
                _render_analiza(tedni, t_idx, teden["id"])

    st.session_state["ceniki_tedni"] = tedni
    _save_ceniki(tedni)
