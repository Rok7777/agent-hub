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
GOJENO_DRZAVE = {
    "HR": "Hrvaška", "IT": "Italija", "TR": "Turčija",
    "NO": "Norveška", "GR": "Grčija", "ES": "Španija", "FR": "Francija",
}

# ─── Pomožne funkcije ─────────────────────────────────────────────────────────

def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


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
        "nasi_ceniki": {
            ime: {"Gojeno": [], "Divjaki": [], "Lokalna riba": []}
            for ime in NASI_CENIKI
        },
    }


def _fmt_datum(d) -> str:
    if not d:
        return str(d) if d else ""
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
    nasi  = {ime: sum(len(v) for v in teden.get("nasi_ceniki", {}).get(ime, {}).values())
             for ime in NASI_CENIKI}
    return {"dobavitelji": n_dob, **nasi}

# ─── Dokumenti: HTML / Excel ─────────────────────────────────────────────────

def _logo_b64() -> str:
    logo_path = _DATA_DIR / "logo.png"
    if logo_path.exists():
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""


def _glava_html(naslov: str, podnaslov: str, logo_b64: str = "") -> str:
    logo_tag = (f'<img src="data:image/png;base64,{logo_b64}" style="height:48px;width:auto;margin-right:12px;" alt="logo">'
                if logo_b64 else "")
    return f"""
    <div style="display:flex;align-items:flex-start;gap:0;margin-bottom:10px;
                padding-bottom:8px;border-bottom:2px solid #e8742a;">
      {logo_tag}
      <div style="line-height:1.5;font-size:11px;color:#444;">
        <strong style="font-size:13px;color:#222;display:block;">Oltre Con d.o.o.</strong>
        Orehovlje 2/f, 5291 Miren<br>
        Davčna št.: SI19211210
      </div>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
      <div style="font-size:14px;font-weight:500;color:#222;">{naslov}</div>
      <div style="font-size:10px;color:#777;">{podnaslov}</div>
    </div>"""


def _sklop_html(naziv: str, artikli: list, pokazi_dobavitelja: bool = False) -> str:
    if not artikli:
        return ""
    sortirani = sorted(artikli, key=lambda a: a.get("naziv", "").lower())
    vrstice = ""
    for art in sortirani:
        por = f' <span style="color:#999;font-size:9px;">{art.get("poreklo","")}</span>' if art.get("poreklo") else ""
        dob_txt = f' <span style="color:#bbb;font-size:9px;">· {art.get("dobavitelj","")}</span>' if pokazi_dobavitelja and art.get("dobavitelj") else ""
        cena = float(art.get("cena_prodajna") or art.get("cena") or 0)
        cena_str = f"{cena:.2f} €".replace(".", ",") if cena > 0 else "—"
        vrstice += (f'<tr style="border-bottom:0.5px solid #eee;">'
                    f'<td style="padding:2px 4px;color:#222;">{art.get("naziv","")}{por}{dob_txt}</td>'
                    f'<td style="padding:2px 4px;text-align:right;color:#222;white-space:nowrap;">{cena_str}</td>'
                    f'</tr>')
    return (f'<div style="font-size:10px;font-weight:500;color:#e8742a;text-transform:uppercase;'
            f'letter-spacing:0.07em;padding:3px 0 2px;border-bottom:1px solid #f5c9a0;margin-bottom:2px;">{naziv}</div>'
            f'<table style="width:100%;border-collapse:collapse;margin-bottom:6px;"><tbody>{vrstice}</tbody></table>')


def _izvozi_excel_cenik_unused():
    pass  # funkcionalnost je inline v _render_nas_cenik

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
      "latinski_naziv": "latinsko ime vrste",
      "cena": 0.00,
      "enota": "kg",
      "min_kolicina": 0.0,
      "poreklo": "2-črkovna ISO koda",
      "sklop": "Gojeno ali Divjaki ali Lokalna riba",
      "nacin_gojenja": "gojeno v morju / gojeno v sladki vodi / prazno",
      "komentar": ""
    }
  ]
}

Sklop: Gojeno=ribogojnice, Divjaki=divje ulovljene, Lokalna riba=slovensko poreklo.
Cena=vedno za 1kg brez DDV. Poreklo=2-črkovna ISO koda (HR,IT,NO,TR,GR,SI,ES,MA...)."""


def _parse_pdf_claude(pdf_bytes: bytes) -> tuple:
    try:
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {}, "ANTHROPIC_API_KEY ni nastavljen"
        client = anthropic.Anthropic(api_key=api_key)
        b64    = base64.b64encode(pdf_bytes).decode()
        resp   = client.messages.create(
            model="claude-opus-4-6", max_tokens=4096,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": _parse_prompt()},
            ]}],
        )
        raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return {}, f"JSON napaka: {e}"
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
            except Exception as e:
                continue
            df = df.dropna(how="all").dropna(axis=1, how="all")
            if len(df) < 2 or len(df.columns) < 2:
                continue

            # Poišči vrstico z glavo — iščemo vrstico ki vsebuje besedilo (ne samo številke)
            glava_idx = 0
            for hi in range(min(8, len(df))):
                row = df.iloc[hi]
                non_empty = row.dropna().astype(str).str.strip()
                has_text  = non_empty.str.contains(r'[a-zA-ZčšžČŠŽ]', regex=True).any()
                if has_text and len(non_empty) >= 2:
                    glava_idx = hi
                    break

            df.columns = df.iloc[glava_idx].astype(str).str.strip()
            df = df.iloc[glava_idx + 1:].reset_index(drop=True)
            df = df.dropna(how="all").fillna("")

            if len(df) >= 1:
                izbran_list, izbran_df = list_ime, df
                break

        if izbran_df is None:
            return {}, f"Excel '{fname}': ni bilo mogoče prebrati nobeden list (listi: {xf.sheet_names})"

        tabela_txt = _tabela_v_tekst(izbran_df)
        prompt = _parse_prompt() + f"\n\nDatoteka: {fname} (list: {izbran_list})\n\nVsebina:\n{tabela_txt}"

        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {}, "ANTHROPIC_API_KEY ni nastavljen"
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-opus-4-6", max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return {}, f"JSON napaka pri Excel parsanju: {e}"
    except ImportError:
        return {}, "Manjka knjižnica openpyxl — dodaj v requirements.txt"
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
        resp = client.messages.create(model="claude-opus-4-6", max_tokens=4096,
            messages=[{"role": "user", "content": prompt}])
        raw = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return {}, f"JSON napaka: {e}"
    except Exception as e:
        return {}, str(e)


def _parse_cenik(file_bytes: bytes, fname: str, ftype: str) -> tuple:
    ft = ftype.lower()
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
    if "pdf" in ft or ext == "pdf":
        return _parse_pdf_claude(file_bytes)
    elif "excel" in ft or "spreadsheet" in ft or ext in ("xlsx", "xls"):
        return _parse_excel_claude(file_bytes, fname)
    elif "csv" in ft or ext == "csv":
        return _parse_csv_claude(file_bytes, fname)
    return {}, f"Neznan format: {fname}"

# ─── Analiza cen ─────────────────────────────────────────────────────────────

def _zberi_zgodovino_cen(tedni: list, trenutni_idx: int, n_tednov: int = 4) -> dict:
    rezultat: dict = {}
    pretekli_idx = list(range(max(0, trenutni_idx - n_tednov), trenutni_idx))
    pretekle_cene: dict = {}
    for t_idx in pretekli_idx:
        t = tedni[t_idx]
        for cenik in t.get("ceniki_dob", []):
            for art in cenik.get("artikli", []):
                lat  = (art.get("latinski_naziv") or art.get("naziv", "")).lower().strip()
                cena = float(art.get("cena", 0) or 0)
                if not lat or cena <= 0:
                    continue
                if lat not in pretekle_cene:
                    pretekle_cene[lat] = {}
                if t_idx not in pretekle_cene[lat] or cena < pretekle_cene[lat][t_idx]:
                    pretekle_cene[lat][t_idx] = cena
    trenutni = tedni[trenutni_idx]
    trenutne: dict = {}
    for cenik in trenutni.get("ceniki_dob", []):
        for art in cenik.get("artikli", []):
            lat  = (art.get("latinski_naziv") or art.get("naziv", "")).lower().strip()
            cena = float(art.get("cena", 0) or 0)
            if not lat or cena <= 0:
                continue
            if lat not in trenutne or cena < trenutne[lat]["cena"]:
                trenutne[lat] = {
                    "cena": cena, "naziv": art.get("naziv", lat.title()),
                    "dobavitelj": cenik.get("dobavitelj", ""),
                    "sklop": art.get("sklop", "Divjaki"),
                    "poreklo": art.get("poreklo", ""),
                }
    for lat, curr in trenutne.items():
        hist = [pretekle_cene.get(lat, {}).get(t_idx, None) for t_idx in pretekli_idx]
        rezultat[lat] = {**curr, "hist": hist}
    return rezultat


def _izracunaj_trend(cena_trenutna: float, hist: list) -> dict:
    cena_1t = next((c for c in reversed(hist) if c is not None), None)
    znane   = [c for c in hist if c is not None]
    avg_4t  = round(sum(znane) / len(znane), 4) if znane else None
    trend_1t  = round((cena_trenutna / cena_1t  - 1) * 100, 1) if cena_1t  and cena_1t  > 0 else None
    trend_avg = round((cena_trenutna / avg_4t   - 1) * 100, 1) if avg_4t   and avg_4t   > 0 else None
    return {"trend_1t": trend_1t, "trend_avg": trend_avg, "avg_4t": avg_4t, "cena_1t": cena_1t}


def _trend_ikona(pct) -> str:
    if pct is None:
        return "—"
    if pct <= -10: return f"🟢🟢 {pct:+.1f}%"
    if pct <    0: return f"🟢 {pct:+.1f}%"
    if pct ==   0: return f"⬜ {pct:+.1f}%"
    if pct <=   5: return f"🔴 {pct:+.1f}%"
    return f"🔴🔴 {pct:+.1f}%"


def _render_analiza(tedni: list, trenutni_idx: int, teden_id: str):
    N = 4
    if len(tedni) < 2:
        st.info("Za analizo cen potrebuješ vsaj 2 tedna podatkov.")
        return
    zgodovina = _zberi_zgodovino_cen(tedni, trenutni_idx, n_tednov=N)
    if not zgodovina:
        st.info("V trenutnem tednu ni cenikov dobaviteljev za analizo.")
        return
    pretekli_idx = list(range(max(0, trenutni_idx - N), trenutni_idx))
    hist_labeli  = ["—"] * (N - len(pretekli_idx)) + [
        _fmt_datum(tedni[i].get("datum_od", "")) for i in pretekli_idx
    ]
    col_f1, col_f2, col_f3 = st.columns([2, 2, 3])
    with col_f1:
        prag_push = st.number_input("Push lista: prag avg trend (%)", value=-5.0,
                                     max_value=0.0, step=0.5, format="%.1f", key=f"prag_{teden_id}")
    with col_f2:
        filter_sklop = st.selectbox("Filtriraj po sklopu", ["Vsi"] + SKLOPI, key=f"fsk_{teden_id}")
    with col_f3:
        pokazi_samo_spr = st.checkbox("Samo artikli s spremembo", value=False, key=f"samo_spr_{teden_id}")
    st.divider()
    tab_hist, tab_push = st.tabs(["📈 Gibanje cen", "📣 Push lista"])

    def _sort_key(item):
        lat, d = item
        tr = _izracunaj_trend(d["cena"], d["hist"])
        return (SKLOPI.index(d["sklop"]) if d["sklop"] in SKLOPI else 99,
                tr["trend_avg"] if tr["trend_avg"] is not None else 999)

    sorted_items = sorted(zgodovina.items(), key=_sort_key)

    with tab_hist:
        col_w = [2.5, 1.5, 1.2] + [1.0] * N + [1.2, 1.2, 1.2]
        cols_h = st.columns(col_w)
        for i, h in enumerate(["Artikel", "Dobavitelj", "Sklop"] + hist_labeli + ["Trenutna €", "Trend (1t)", "Trend (avg 4t)"]):
            cols_h[i].markdown(f"**{h}**")
        st.markdown("---")
        for lat, d in sorted_items:
            if filter_sklop != "Vsi" and d["sklop"] != filter_sklop:
                continue
            trend_r = _izracunaj_trend(d["cena"], d["hist"])
            if pokazi_samo_spr and trend_r["trend_1t"] is None and trend_r["trend_avg"] is None:
                continue
            cols_r = st.columns(col_w)
            cols_r[0].markdown(f"**{d['naziv']}**")
            cols_r[1].caption(d["dobavitelj"])
            cols_r[2].caption(_sklop_label(d["sklop"], d["poreklo"]))
            hist_full = ([None] * (N - len(d["hist"]))) + d["hist"]
            for i, hc in enumerate(hist_full):
                cols_r[3 + i].caption(f"{hc:.2f}" if hc is not None else "—")
            cols_r[3 + N].markdown(f"**{d['cena']:.2f} €**")
            cols_r[3 + N + 1].caption(_trend_ikona(trend_r["trend_1t"]))
            cols_r[3 + N + 2].caption(_trend_ikona(trend_r["trend_avg"]))
        st.divider()
        st.caption("🟢🟢 padec >10%  ·  🟢 padec  ·  🔴 rast  ·  🔴🔴 rast >5%")

    with tab_push:
        st.caption(f"Artikli kjer je trenutna cena vsaj **{abs(prag_push):.0f}% nižja** od povprečja zadnjih 4 tednov.")
        teden_cur = next((t for t in tedni if t["id"] == teden_id), {})
        push_artikli = []
        for lat, d in sorted_items:
            if filter_sklop != "Vsi" and d["sklop"] != filter_sklop:
                continue
            trend_r = _izracunaj_trend(d["cena"], d["hist"])
            if trend_r["trend_avg"] is not None and trend_r["trend_avg"] <= prag_push:
                push_artikli.append((d, trend_r))
        if not push_artikli:
            st.info(f"Ni artiklov z avg trendom ≤ {prag_push:.0f}%.")
        else:
            ph = st.columns([3, 1.5, 1.2, 1.2, 1.5, 1.5])
            for col, h in zip(ph, ["Artikel", "Dobavitelj", "Trenutna €", "Povp. 4t €", "Trend (avg)", "Trend (1t)"]):
                col.markdown(f"**{h}**")
            st.markdown("---")
            for d, t in push_artikli:
                pc1, pc2, pc3, pc4, pc5, pc6 = st.columns([3, 1.5, 1.2, 1.2, 1.5, 1.5])
                pc1.markdown(f"**{d['naziv']}**  \n*{d.get('sklop','')}*")
                pc2.caption(d["dobavitelj"])
                pc3.markdown(f"**{d['cena']:.2f} €**")
                pc4.caption(f"{t['avg_4t']:.2f} €" if t["avg_4t"] else "—")
                pc5.markdown(_trend_ikona(t["trend_avg"]))
                pc6.caption(_trend_ikona(t["trend_1t"]))
            st.divider()
            lines = [
                f"🐟 TEDNA AKCIJA — POCENI RIBE ({_fmt_datum(teden_cur.get('datum_od','?'))} – {_fmt_datum(teden_cur.get('datum_do','?'))})",
                "",
            ]
            for d, t in push_artikli:
                lines.append(f"✅ {d['naziv']}  {d['cena']:.2f} €/kg  "
                              f"({_trend_ikona(t['trend_avg'])} vs povp. {t['avg_4t']:.2f} €)"
                              f"  — {d['dobavitelj']}")
            lines += ["", "Zaloge omejene. Za naročila nas kontaktirajte."]
            st.text_area("Besedilo za WhatsApp / email", value="\n".join(lines),
                         height=200, key=f"push_txt_{teden_id}")
            st.caption("Označi vse (Ctrl+A) in kopiraj.")

# ─── Naročilo dobavitelju ─────────────────────────────────────────────────────

def _render_narocilo(teden: dict, tedni: list):
    st.caption("Izberi artikle za naročilo — sistem grupira po dobaviteljih in pripravi dokumente.")
    ceniki_dob = teden.get("ceniki_dob", [])
    if not ceniki_dob:
        st.info("Najprej naloži cenike dobaviteljev.")
        return

    nc1, nc2, nc3 = st.columns([3, 2, 2])
    with nc1:
        iskanje_n = st.text_input("🔍 Išči artikel", key=f"nar_isk_{teden['id']}", placeholder="npr. brancin...")
    with nc2:
        filter_dob_n = st.selectbox("Dobavitelj", ["Vsi"] + [c["dobavitelj"] for c in ceniki_dob], key=f"nar_dob_{teden['id']}")
    with nc3:
        filter_sklop_n = st.selectbox("Sklop", ["Vsi"] + SKLOPI, key=f"nar_sklop_{teden['id']}")

    # Zberi najugodnejše cene
    vse_art: dict = {}
    for cenik in ceniki_dob:
        for art in cenik.get("artikli", []):
            lat  = (art.get("latinski_naziv") or art.get("naziv", "")).lower().strip()
            cena = float(art.get("cena", 0) or 0)
            if not lat or cena <= 0:
                continue
            if lat not in vse_art or cena < vse_art[lat]["cena"]:
                vse_art[lat] = {
                    "naziv": art.get("naziv", ""), "cena": cena,
                    "enota": art.get("enota", "kg"), "poreklo": art.get("poreklo", ""),
                    "sklop": art.get("sklop", "Divjaki"), "dobavitelj": cenik.get("dobavitelj", ""),
                }

    filtrirani = [
        (lat, art) for lat, art in vse_art.items()
        if (filter_dob_n == "Vsi" or art["dobavitelj"] == filter_dob_n)
        and (filter_sklop_n == "Vsi" or art["sklop"] == filter_sklop_n)
        and (not iskanje_n or iskanje_n.lower() in art["naziv"].lower())
    ]
    filtrirani.sort(key=lambda x: (x[1].get("sklop",""), x[1].get("naziv","").lower()))

    if not filtrirani:
        st.info("Ni artiklov za prikaz.")
        return

    master_nar = st.checkbox("☑ Izberi vse", key=f"nar_master_{teden['id']}")
    prev_mk = f"nar_prev_m_{teden['id']}"
    prev_m  = st.session_state.get(prev_mk, None)
    if prev_m is not None and master_nar != prev_m:
        for lat, _ in filtrirani:
            st.session_state[f"nar_sel_{teden['id']}_{lat}"] = master_nar
    st.session_state[prev_mk] = master_nar
    st.markdown("---")

    gh = st.columns([0.5, 3.5, 1.5, 1, 1.5, 1.5])
    for col, h in zip(gh, ["", "Artikel", "Dobavitelj", "Cena €", "Sklop", "Količina"]):
        col.markdown(f"**{h}**")
    st.markdown("---")

    izbrani = []
    for lat, art in filtrirani:
        rc = st.columns([0.5, 3.5, 1.5, 1, 1.5, 1.5])
        sel = rc[0].checkbox("", key=f"nar_sel_{teden['id']}_{lat}")
        rc[1].write(f"{art['naziv']}" + (f" *{art.get('poreklo','')}*" if art.get("poreklo") else ""))
        rc[2].caption(art["dobavitelj"])
        rc[3].caption(f"{art['cena']:.2f}")
        rc[4].caption(art["sklop"])
        kolicina = rc[5].number_input("kol", min_value=0.0, value=0.0, step=1.0, format="%.1f",
                                       key=f"nar_kol_{teden['id']}_{lat}", label_visibility="collapsed")
        if sel:
            izbrani.append({**art, "kolicina": kolicina})

    st.markdown("---")
    if not izbrani:
        st.caption("Izberi artikle zgoraj za pripravo naročila.")
        return

    po_dob: dict = {}
    for art in izbrani:
        po_dob.setdefault(art["dobavitelj"], []).append(art)

    st.success(f"Izbrano: {len(izbrani)} artiklov pri {len(po_dob)} dobaviteljih")

    for dob, arts in po_dob.items():
        with st.expander(f"📄 Naročilo — {dob} ({len(arts)} artiklov)", expanded=True):
            nh = st.columns([4, 1, 1, 1, 1])
            for col, h in zip(nh, ["Artikel", "Količina", "Enota", "Cena €", "Skupaj €"]):
                col.markdown(f"**{h}**")
            st.markdown("---")
            skupaj = 0.0
            for art in arts:
                kol    = float(art.get("kolicina") or 0)
                cena   = float(art.get("cena") or 0)
                znesek = round(kol * cena, 2)
                skupaj += znesek
                nc = st.columns([4, 1, 1, 1, 1])
                nc[0].write(f"{art['naziv']} {art.get('poreklo','')}")
                nc[1].write(f"{kol:.1f}")
                nc[2].caption(art.get("enota", "kg"))
                nc[3].caption(f"{cena:.2f}")
                nc[4].write(f"**{znesek:.2f}**")
            st.markdown("---")
            st.markdown(f"**Skupaj: {skupaj:.2f} €**")
            try:
                import pandas as pd, io
                df_nar = pd.DataFrame([{
                    "Artikel": a["naziv"], "Poreklo": a.get("poreklo",""),
                    "Količina": float(a.get("kolicina") or 0), "Enota": a.get("enota","kg"),
                    "Cena €/enoto": float(a.get("cena") or 0),
                    "Skupaj €": round(float(a.get("kolicina") or 0) * float(a.get("cena") or 0), 2),
                } for a in arts])
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    df_nar.to_excel(writer, index=False, sheet_name="Narocilo")
                    ws = writer.sheets["Narocilo"]
                    ws.column_dimensions["A"].width = 35
                    for col_l in ["B","C","D","E","F"]:
                        ws.column_dimensions[col_l].width = 14
                st.download_button(
                    f"⬇️ Excel naročilo — {dob}",
                    data=buf.getvalue(),
                    file_name=f"narocilo_{dob.replace(' ','_')}_{teden['datum_od']}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_nar_{teden['id']}_{dob}",
                )
            except ImportError:
                st.warning("Manjka pandas/openpyxl.")

# ─── Naši ceniki ─────────────────────────────────────────────────────────────

def _render_nas_cenik(ime_cenika: str, teden: dict, tedni: list):
    nas_cenik = teden["nasi_ceniki"][ime_cenika]
    logo_b64  = _logo_b64()

    # ── Iskalnik + filter ────────────────────────────────────────────────
    sc1, sc2 = st.columns([3, 2])
    with sc1:
        iskanje = st.text_input("🔍 Išči artikel", key=f"isk_{teden['id']}_{ime_cenika}",
                                placeholder="npr. brancin, losos, tun...")
    with sc2:
        filter_s = st.selectbox("Sklop", ["Vsi"] + SKLOPI,
                                key=f"fs_{teden['id']}_{ime_cenika}")
    st.markdown("---")

    # ── Gumb: Samodejno sestavi ──────────────────────────────────────────
    st.caption("Samodejno sestavi: vzame najcenejšo ceno za vsak artikel med vsemi dobavitelji tega tedna.")
    if st.button(f"🤖 Samodejno sestavi {ime_cenika}",
                 key=f"auto_{teden['id']}_{ime_cenika}",
                 disabled=not teden.get("ceniki_dob")):
        vse: dict = {}
        for cenik in teden["ceniki_dob"]:
            for art in cenik.get("artikli", []):
                lat  = (art.get("latinski_naziv") or art.get("naziv","")).lower().strip()
                cena = float(art.get("cena", 0))
                if not lat or cena <= 0:
                    continue
                if lat not in vse or cena < vse[lat]["cena"]:
                    vse[lat] = {
                        "naziv": art.get("naziv",""), "latinski_naziv": art.get("latinski_naziv",""),
                        "cena": cena, "enota": art.get("enota","kg"),
                        "poreklo": art.get("poreklo",""), "sklop": art.get("sklop","Divjaki"),
                        "cena_prodajna": 0.0, "marza_pct": 0.0,
                        "dobavitelj": cenik.get("dobavitelj",""), "komentar": art.get("komentar",""),
                    }
        for sklop in SKLOPI:
            nas_cenik[sklop] = []
        for art_data in vse.values():
            sklop = art_data.get("sklop","Divjaki")
            if sklop not in SKLOPI:
                sklop = "Divjaki"
            nas_cenik[sklop].append(art_data)
        teden["nasi_ceniki"][ime_cenika] = nas_cenik
        st.session_state["ceniki_tedni"] = tedni
        _save_ceniki(tedni)
        st.rerun()

    # ── Ročno dodajanje ──────────────────────────────────────────────────
    with st.expander("➕ Ročno dodaj artikel", expanded=False):
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            r_naziv = st.text_input("Naziv", key=f"rn_{teden['id']}_{ime_cenika}")
            r_lat   = st.text_input("Latinski naziv", key=f"rl_{teden['id']}_{ime_cenika}")
        with rc2:
            r_cena  = st.number_input("Nakupna cena €/kg", min_value=0.0, step=0.01,
                                       key=f"rc_{teden['id']}_{ime_cenika}")
            r_prod  = st.number_input("Prodajna cena €/kg", min_value=0.0, step=0.01,
                                       key=f"rp_{teden['id']}_{ime_cenika}")
        with rc3:
            r_sklop = st.selectbox("Sklop", SKLOPI, key=f"rs_{teden['id']}_{ime_cenika}")
            r_por   = st.text_input("Poreklo (ISO)", key=f"ro_{teden['id']}_{ime_cenika}")
            r_dob   = st.text_input("Dobavitelj", key=f"rd_{teden['id']}_{ime_cenika}")
        if st.button("Dodaj", key=f"radd_{teden['id']}_{ime_cenika}") and r_naziv:
            nas_cenik[r_sklop].append({
                "naziv": r_naziv, "latinski_naziv": r_lat, "cena": r_cena,
                "cena_prodajna": r_prod,
                "marza_pct": round((r_prod/r_cena - 1)*100, 1) if r_cena > 0 else 0,
                "enota": "kg", "poreklo": r_por, "sklop": r_sklop,
                "dobavitelj": r_dob, "komentar": "",
            })
            st.session_state["ceniki_tedni"] = tedni
            _save_ceniki(tedni)
            st.rerun()

    # ── Prikaz po sklopih z iskalnikom ──────────────────────────────────
    total_art = sum(len(nas_cenik.get(s, [])) for s in SKLOPI)
    if total_art == 0:
        st.info("Cenik je prazen. Uporabi 'Samodejno sestavi' ali dodaj ročno.")
    else:
        vse_cene_cache: dict = {}
        for sklop in SKLOPI:
            if filter_s != "Vsi" and sklop != filter_s:
                continue
            artikli_sklop = nas_cenik.get(sklop, [])
            # Abecedno sortiranje
            artikli_sklop_sort = sorted(artikli_sklop, key=lambda a: a.get("naziv","").lower())
            # Filter iskanje
            if iskanje:
                artikli_sklop_sort = [a for a in artikli_sklop_sort if iskanje.lower() in a.get("naziv","").lower()]
            if not artikli_sklop_sort:
                continue
            ikona = {"Gojeno": "🐟", "Divjaki": "🌊", "Lokalna riba": "🏔️"}.get(sklop, "")
            st.markdown(f"#### {ikona} {sklop}")
            h0,h1,h2,h3,h4,h5,h6,h7 = st.columns([3,2,1.2,1.2,1.2,1,1.5,0.6])
            h0.markdown("**Naziv**"); h1.markdown("**Latinski naziv**")
            h2.markdown("**Nakupna €**"); h3.markdown("**Prod. €**")
            h4.markdown("**Marža %**"); h5.markdown("**Por.**")
            h6.markdown("**Dobavitelj ↙**"); h7.markdown("")
            st.markdown("---")
            for a_idx, art in enumerate(artikli_sklop_sort):
                lat_key  = (art.get("latinski_naziv") or art.get("naziv","")).lower().strip()
                if lat_key not in vse_cene_cache:
                    primerjave = []
                    for cenik in teden.get("ceniki_dob",[]):
                        for a2 in cenik.get("artikli",[]):
                            lat2 = (a2.get("latinski_naziv") or a2.get("naziv","")).lower().strip()
                            if lat2 == lat_key:
                                primerjave.append(f"{cenik['dobavitelj']}: {a2.get('cena',0):.2f} €")
                    vse_cene_cache[lat_key] = primerjave
                primerjave = vse_cene_cache[lat_key]
                uid = f"{teden['id']}_{ime_cenika}_{sklop}_{a_idx}"
                c0,c1,c2,c3,c4,c5,c6,c7 = st.columns([3,2,1.2,1.2,1.2,1,1.5,0.6])
                with c0:
                    art["naziv"] = st.text_input("naziv", value=art.get("naziv",""),
                                                  key=f"naziv_{uid}", label_visibility="collapsed")
                with c1:
                    st.caption(art.get("latinski_naziv",""))
                with c2:
                    art["cena"] = st.number_input("nc", value=float(art.get("cena",0)),
                                                   min_value=0.0, step=0.01, format="%.2f",
                                                   key=f"cena_{uid}", label_visibility="collapsed")
                with c3:
                    new_pc = st.number_input("pc", value=float(art.get("cena_prodajna",0)),
                                              min_value=0.0, step=0.01, format="%.2f",
                                              key=f"prod_{uid}", label_visibility="collapsed")
                    if new_pc != float(art.get("cena_prodajna",0)):
                        art["cena_prodajna"] = new_pc
                        nc_v = float(art.get("cena",0))
                        if nc_v > 0 and new_pc > 0:
                            art["marza_pct"] = round((new_pc/nc_v - 1)*100, 1)
                with c4:
                    nc_v = float(art.get("cena",0))
                    pc_v = float(art.get("cena_prodajna",0))
                    if nc_v > 0 and pc_v > 0:
                        marza = round((pc_v/nc_v - 1)*100, 1)
                        art["marza_pct"] = marza
                        st.metric("", f"{marza:.1f}%", label_visibility="collapsed")
                    else:
                        st.caption("—")
                with c5:
                    st.caption(art.get("poreklo",""))
                with c6:
                    dob = art.get("dobavitelj","")
                    if primerjave and len(primerjave) > 1:
                        st.caption(f"✅ {dob}", help="\n".join(primerjave))
                    else:
                        st.caption(dob)
                with c7:
                    if st.button("✕", key=f"rm_{uid}", help="Odstrani artikel"):
                        # Poišči po identiteti objekta (id) — zanesljivo tudi pri sortiranih listah
                        art_id = id(art)
                        orig_idx = next((i for i, a in enumerate(artikli_sklop) if id(a) == art_id), None)
                        if orig_idx is not None:
                            artikli_sklop.pop(orig_idx)
                        st.session_state["ceniki_tedni"] = tedni
                        _save_ceniki(tedni)
                        st.rerun()

        if st.button(f"💾 Shrani {ime_cenika}", key=f"save_{teden['id']}_{ime_cenika}",
                     type="primary", use_container_width=True):
            st.session_state["ceniki_tedni"] = tedni
            _save_ceniki(tedni)
            st.success("Shranjeno.")

    # ── Izvoz ────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("**Izvoz cenika za stranke**")

    # Izbor artiklov za izvoz
    vse_artikli_flat = []
    for sklop in SKLOPI:
        for art in sorted(nas_cenik.get(sklop,[]), key=lambda a: a.get("naziv","").lower()):
            vse_artikli_flat.append((sklop, art))

    if vse_artikli_flat:
        master_izvoz = st.checkbox("☑ Izberi vse za izvoz", key=f"izvoz_master_{teden['id']}_{ime_cenika}")
        prev_mik = f"izvoz_prev_m_{teden['id']}_{ime_cenika}"
        prev_mi  = st.session_state.get(prev_mik, None)
        if prev_mi is not None and master_izvoz != prev_mi:
            for i, (_, art) in enumerate(vse_artikli_flat):
                st.session_state[f"izvoz_sel_{teden['id']}_{ime_cenika}_{i}"] = master_izvoz
        st.session_state[prev_mik] = master_izvoz

        izbrani_izvoz = []
        for i, (sklop, art) in enumerate(vse_artikli_flat):
            sel_i = st.checkbox(
                f"{art.get('naziv','')} ({sklop}) — "
                f"{float(art.get('cena_prodajna') or art.get('cena') or 0):.2f} €",
                key=f"izvoz_sel_{teden['id']}_{ime_cenika}_{i}"
            )
            if sel_i:
                izbrani_izvoz.append((sklop, art))

        if izbrani_izvoz:
            # HTML izvoz
            html_vsebina = _glava_html(
                f"Cenik {ime_cenika}",
                f"{_fmt_datum(teden['datum_od'])} – {_fmt_datum(teden['datum_do'])} &nbsp;·&nbsp; Cene brez DDV &nbsp;·&nbsp; €/kg",
                logo_b64
            )
            for sklop in SKLOPI:
                arts_s = sorted(
                    [a for s,a in izbrani_izvoz if s == sklop],
                    key=lambda a: a.get("naziv","").lower()
                )
                html_vsebina += _sklop_html(sklop, arts_s)
            html_vsebina += ('<div style="border-top:0.5px solid #ddd;padding-top:5px;'
                             'display:flex;justify-content:space-between;margin-top:8px;">'
                             '<div style="font-size:9px;color:#aaa;">Oltre Con d.o.o. · Orehovlje 2/f, 5291 Miren · SI19211210</div>'
                             '<div style="font-size:9px;color:#aaa;">1/1</div></div>')
            html_full = (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
                         f'<style>body{{font-family:Arial,sans-serif;font-size:11px;color:#222;margin:20px 40px;}}'
                         f'*{{box-sizing:border-box;}}</style></head><body>{html_vsebina}</body></html>')

            col_h, col_x = st.columns(2)
            with col_h:
                st.download_button(
                    "⬇️ Prenesi HTML cenik",
                    data=html_full.encode("utf-8"),
                    file_name=f"cenik_{ime_cenika}_{teden['datum_od']}.html",
                    mime="text/html",
                    key=f"dl_html_{teden['id']}_{ime_cenika}",
                )
            with col_x:
                # Excel izvoz izbranih artiklov
                try:
                    import pandas as pd, io
                    vrstice_xl = [{
                        "Sklop": s, "Artikel": a.get("naziv",""),
                        "Poreklo": a.get("poreklo",""),
                        "Cena €/kg": float(a.get("cena_prodajna") or a.get("cena") or 0),
                    } for s, a in izbrani_izvoz]
                    df_xl = pd.DataFrame(vrstice_xl)
                    buf_xl = io.BytesIO()
                    with pd.ExcelWriter(buf_xl, engine="openpyxl") as writer:
                        df_xl.to_excel(writer, index=False, sheet_name=f"Cenik {ime_cenika}")
                        ws = writer.sheets[f"Cenik {ime_cenika}"]
                        for col_l, w in zip(["A","B","C","D"], [14, 40, 10, 12]):
                            ws.column_dimensions[col_l].width = w
                    st.download_button(
                        "⬇️ Prenesi Excel cenik",
                        data=buf_xl.getvalue(),
                        file_name=f"cenik_{ime_cenika}_{teden['datum_od']}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_xl_{teden['id']}_{ime_cenika}",
                    )
                except ImportError:
                    st.warning("Manjka pandas/openpyxl.")

# ─── RENDER ──────────────────────────────────────────────────────────────────

def render():
    st.caption("Tedni ceniki dobaviteljev → HIT / HoReCa")

    if "ceniki_tedni" not in st.session_state:
        st.session_state["ceniki_tedni"] = _load_ceniki()
    tedni: list = st.session_state["ceniki_tedni"]

    # ── Sidebar ──────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Nov teden")
        col_a, col_b = st.columns(2)
        with col_a:
            d_od = st.date_input("Od", value=date.today(), key="nt_od")
        with col_b:
            d_do = st.date_input("Do", value=date.today(), key="nt_do")
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

    # ── Prikaz tednov ────────────────────────────────────────────────────
    for t_idx, teden in enumerate(tedni):
        st_info    = _prestej_artiklov(teden)
        teden_label = (
            f"📅 {_fmt_datum(teden['datum_od'])} – {_fmt_datum(teden['datum_do'])}  ·  "
            f"{len(teden.get('ceniki_dob',[]))} dobaviteljev  ·  "
            f"{st_info['dobavitelji']} artiklov  ·  "
            f"HIT: {st_info.get('HIT',0)}  HoReCa: {st_info.get('HoReCa',0)}"
        )

        with st.expander(teden_label, expanded=(t_idx == len(tedni) - 1)):
            st.caption(f"ID: {teden['id']}  ·  Ustvarjen: {_fmt_datum(teden.get('ustvarjen','?'))}")

            tab_dob, tab_hit, tab_horeca, tab_narocilo, tab_analiza = st.tabs([
                "📥 Ceniki dobaviteljev",
                "⭐ HIT",
                "🍽️ HoReCa",
                "📋 Naročilo dobavitelju",
                "📊 Analiza cen",
            ])

            # ── TAB: CENIKI DOBAVITELJEV ──────────────────────────────────
            with tab_dob:
                _tid = teden["id"]
                _up_reset_n = st.session_state.get(f"up_reset_{_tid}", 0)
                upload_key  = f"up_{_tid}_{_up_reset_n}"
                nalozene = st.file_uploader(
                    "Naloži cenike dobaviteljev (PDF, Excel, CSV)",
                    type=["pdf","xlsx","xls","csv"],
                    accept_multiple_files=True,
                    key=upload_key,
                    label_visibility="collapsed",
                )
                if nalozene:
                    prog = st.progress(0)
                    for i, f in enumerate(nalozene):
                        prog.progress((i+1)/len(nalozene), text=f"Berem {f.name} …")
                        file_bytes = f.read()
                        parsed, err = _parse_cenik(file_bytes, f.name, f.type)
                        if err or not parsed:
                            st.error(f"❌ {f.name}: {err or 'AI ni vrnil podatkov'}")
                            continue
                        dob_ime   = parsed.get("dobavitelj", f.name)
                        dob_datum = parsed.get("datum", "")
                        teden["ceniki_dob"].append({
                            "id":         str(uuid.uuid4())[:8],
                            "dobavitelj": dob_ime,
                            "datum":      dob_datum,
                            "valuta":     parsed.get("valuta","EUR"),
                            "fname":      f.name,
                            "artikli":    parsed.get("artikli",[]),
                            "uvozeno":    datetime.now().isoformat()[:16],
                        })
                        st.success(f"✅ {dob_ime} ({_fmt_datum(dob_datum) or 'brez datuma'}): "
                                   f"{len(parsed.get('artikli',[]))} artiklov")
                    prog.empty()
                    st.session_state[f"up_reset_{_tid}"] = _up_reset_n + 1
                    st.session_state["ceniki_tedni"] = tedni
                    _save_ceniki(tedni)
                    st.rerun()

                if not teden.get("ceniki_dob"):
                    st.caption("Naloži PDF/Excel/CSV cenike dobaviteljev z gumbom zgoraj.")
                else:
                    for c_idx, cenik in enumerate(teden["ceniki_dob"]):
                        c_label = (f"🏭 **{cenik['dobavitelj']}**  ·  "
                                   f"{_fmt_datum(cenik.get('datum','')) or '—'}  ·  "
                                   f"{len(cenik.get('artikli',[]))} artiklov  ·  "
                                   f"`{cenik.get('fname','')}`")
                        col_exp, col_rm = st.columns([11, 1])
                        with col_rm:
                            if st.button("✕", key=f"rm_dob_{_tid}_{cenik['id']}",
                                         help="Odstrani cenik dobavitelja"):
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
                                    for a_idx, art in enumerate(artikli):
                                        ac1,ac2,ac3,ac4,ac5,ac6 = st.columns([3,2,1.2,1.2,1,2])
                                        art["naziv"] = ac1.text_input("Naziv", value=art.get("naziv",""),
                                            key=f"an_{_tid}_{cenik['id']}_{a_idx}", label_visibility="collapsed")
                                        ac2.caption(art.get("latinski_naziv",""))
                                        art["cena"] = ac3.number_input("€", value=float(art.get("cena",0)),
                                            min_value=0.0, step=0.01, format="%.2f",
                                            key=f"ac_{_tid}_{cenik['id']}_{a_idx}", label_visibility="collapsed")
                                        ac4.caption(art.get("enota","kg"))
                                        ac5.caption(art.get("poreklo",""))
                                        sklop_opts = SKLOPI
                                        cur_s = art.get("sklop","Divjaki")
                                        art["sklop"] = ac6.selectbox("Sklop", sklop_opts,
                                            index=sklop_opts.index(cur_s) if cur_s in sklop_opts else 1,
                                            key=f"as_{_tid}_{cenik['id']}_{a_idx}", label_visibility="collapsed")
                                    if st.button("💾 Shrani popravke", key=f"save_dob_{_tid}_{cenik['id']}"):
                                        st.session_state["ceniki_tedni"] = tedni
                                        _save_ceniki(tedni)
                                        st.success("Shranjeno.")

            # ── NAŠI CENIKI ───────────────────────────────────────────────
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
