"""
Tab: Ceniki
Tok: Naloži cenike dobaviteljev (PDF) → AI prebere → poveži artikle → sestavi HIT / HoReCa / Ostali
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
NASI_CENIKI = ["HIT", "HoReCa", "Ostali"]

SKLOPI = ["Gojeno", "Divjaki", "Lokalna riba"]

GOJENO_DRZAVE = {
    "HR": "Hrvaška",
    "IT": "Italija",
    "TR": "Turčija",
    "NO": "Norveška",
    "GR": "Grčija",
    "ES": "Španija",
    "FR": "Francija",
}

# ─── Pomožne funkcije ─────────────────────────────────────────────────────────

def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


def _load_ceniki() -> list:
    """Naloži vse tedne iz datoteke. Vrne seznam tednov, najstarejši prvi."""
    try:
        if os.path.exists(CENIKI_FILE):
            with open(CENIKI_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Uredi: najstarejši (najmanjši datum) na vrhu
            data.sort(key=lambda t: t.get("datum_od", ""), reverse=False)
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
        "ceniki_dob":  [],   # seznam cenikov dobaviteljev
        "nasi_ceniki": {     # HIT, HoReCa, Ostali
            ime: {
                "Gojeno":       [],
                "Divjaki":      [],
                "Lokalna riba": [],
            }
            for ime in NASI_CENIKI
        },
    }


def _parse_prompt() -> str:
    return """Ti si strokovnjak za branje cenikov rib in morskih sadežev.
Dokument je cenik dobavitelja — lahko v slovenščini, italijanščini ali hrvaščini.
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
      "poreklo": "2-črkovna ISO koda države porekla",
      "sklop": "Gojeno ali Divjaki ali Lokalna riba",
      "nacin_gojenja": "gojeno v morju / gojeno v sladki vodi / prazno če ni gojeno",
      "komentar": "posebni pogoji, sezonskost, razpoložljivost"
    }
  ]
}

NAVODILA:

Sklop:
- "Gojeno" = ribe gojene v ribogojnicah (brancin, orada, losos, postrv, klapavice-gojene...)
- "Divjaki" = divje ulovljene ribe (tun, sardele, hobotnica, zobatec, skuša...)
- "Lokalna riba" = ribe slovenskega porekla (postrv iz SI, sladkovodne ribe SI)

Cena:
- cena je VEDNO za 1 kg razen če piše drugače (kos, kom)
- Zapiši neto ceno brez DDV

Latinski naziv — po lastnem znanju:
Brancin=Dicentrarchus labrax, Orada=Sparus aurata, Losos=Salmo salar,
Postrv=Oncorhynchus mykiss, Tun=Thunnus albacares, Sardele=Sardina pilchardus,
Klapavice=Mytilus galloprovincialis, Hobotnica=Octopus vulgaris, Skuša=Scomber scombrus,
Zobatec=Dentex dentex, Komarča=Sparus aurata, Oslič=Merluccius merluccius

Poreklo: 2-črkovna ISO koda (HR, IT, NO, TR, GR, SI, ES, MA...)
Če ni navedeno, sklepaj po dobavitelju in vrsti ribe."""


def _parse_pdf_claude(pdf_bytes: bytes) -> tuple:
    """Prebere PDF cenik z Claude Vision. Vrne (dict, napaka)."""
    try:
        import anthropic
        api_key = _secret("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {}, "ANTHROPIC_API_KEY ni nastavljen"
        client = anthropic.Anthropic(api_key=api_key)
        b64    = base64.b64encode(pdf_bytes).decode()
        resp   = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
                    },
                    {"type": "text", "text": _parse_prompt()},
                ],
            }],
        )
        raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return {}, f"JSON napaka: {e}"
    except Exception as e:
        return {}, str(e)


def _poisci_najboljso_ceno(tedni: list, teden_id: str, naziv_query: str) -> list:
    """Za dani artikel poišče vse cene pri vseh dobaviteljih v tednu."""
    teden = next((t for t in tedni if t["id"] == teden_id), None)
    if not teden:
        return []
    rezultati = []
    q = naziv_query.lower()
    for cenik in teden.get("ceniki_dob", []):
        for art in cenik.get("artikli", []):
            naziv = art.get("naziv", "").lower()
            lat   = art.get("latinski_naziv", "").lower()
            if q in naziv or q in lat or naziv in q:
                rezultati.append({
                    "dobavitelj": cenik.get("dobavitelj", ""),
                    "naziv":      art.get("naziv", ""),
                    "cena":       art.get("cena", 0),
                    "enota":      art.get("enota", "kg"),
                    "poreklo":    art.get("poreklo", ""),
                    "sklop":      art.get("sklop", ""),
                })
    rezultati.sort(key=lambda x: x.get("cena", 0))
    return rezultati


def _sklop_label(sklop: str, poreklo: str) -> str:
    """Vrne prikazan label sklopa — za Gojeno doda državo."""
    if sklop == "Gojeno":
        drzava = GOJENO_DRZAVE.get(poreklo.upper(), poreklo)
        return f"Gojeno — {drzava}" if drzava else "Gojeno"
    return sklop


def _zberi_zgodovino_cen(tedni: list, trenutni_idx: int, n_tednov: int = 4) -> dict:
    """
    Za vsak artikel v trenutnem tednu zbere cene iz zadnjih n_tednov tednov.
    Vrne {lat_key: {"naziv": str, "dobavitelj": str, "sklop": str, "poreklo": str,
                     "cene": [c_4t_nazaj, c_3t_nazaj, c_2t_nazaj, c_1t_nazaj, c_trenutna]}}
    Vrednost None = artikel ni bil v tistem tednu.
    """
    rezultat: dict = {}

    # Indeksi preteklih tednov (do n_tednov nazaj, brez trenutnega)
    pretekli_idx = list(range(max(0, trenutni_idx - n_tednov), trenutni_idx))

    # Najprej zgradi slovar cen po tednih za vsak lat_key
    # pretekli_idx je seznam indeksov — zapolni z None za manjkajoče
    # Struktura: {lat_key: [cena_t0, cena_t1, ..., cena_tn-1]}  (brez trenutnega)
    pretekle_cene: dict = {}  # lat_key → {teden_idx: float}

    for t_idx in pretekli_idx:
        t = tedni[t_idx]
        for cenik in t.get("ceniki_dob", []):
            for art in cenik.get("artikli", []):
                lat = (art.get("latinski_naziv") or art.get("naziv", "")).lower().strip()
                if not lat:
                    continue
                cena = float(art.get("cena", 0) or 0)
                if cena <= 0:
                    continue
                if lat not in pretekle_cene:
                    pretekle_cene[lat] = {}
                # Če je v istem tednu več dobaviteljev — vzami najnižjo
                if t_idx not in pretekle_cene[lat] or cena < pretekle_cene[lat][t_idx]:
                    pretekle_cene[lat][t_idx] = cena

    # Zdaj zberi trenutni teden
    trenutni = tedni[trenutni_idx]
    # Zberi vse artikle iz cenikov dobaviteljev trenutnega tedna
    trenutne: dict = {}  # lat_key → {cena, naziv, dobavitelj, sklop, poreklo}
    for cenik in trenutni.get("ceniki_dob", []):
        for art in cenik.get("artikli", []):
            lat   = (art.get("latinski_naziv") or art.get("naziv", "")).lower().strip()
            cena  = float(art.get("cena", 0) or 0)
            if not lat or cena <= 0:
                continue
            if lat not in trenutne or cena < trenutne[lat]["cena"]:
                trenutne[lat] = {
                    "cena":       cena,
                    "naziv":      art.get("naziv", lat.title()),
                    "dobavitelj": cenik.get("dobavitelj", ""),
                    "sklop":      art.get("sklop", "Divjaki"),
                    "poreklo":    art.get("poreklo", ""),
                }

    # Sestavi končni rezultat
    for lat, curr in trenutne.items():
        # Zgodovinske cene — seznam dolžine n_tednov (None če ni podatka)
        hist = []
        for t_idx in pretekli_idx:
            hist.append(pretekle_cene.get(lat, {}).get(t_idx, None))

        rezultat[lat] = {
            "naziv":      curr["naziv"],
            "dobavitelj": curr["dobavitelj"],
            "sklop":      curr["sklop"],
            "poreklo":    curr["poreklo"],
            "cena":       curr["cena"],
            "hist":       hist,   # [c_-4t, c_-3t, c_-2t, c_-1t]  (dolžina = n_tednov)
        }

    return rezultat


def _izracunaj_trend(cena_trenutna: float, hist: list) -> dict:
    """
    Izračuna oba trenda.
    Vrne {
        "trend_1t": float|None,   # % vs prejšnji teden
        "trend_avg": float|None,  # % vs povprečje zadnjih 4t
        "avg_4t": float|None,
        "cena_1t": float|None,
    }
    """
    # Zadnja znana cena v zgodovini (= prejšnji teden)
    cena_1t = None
    for c in reversed(hist):
        if c is not None:
            cena_1t = c
            break

    # Povprečje vseh znanih zgodovinskih cen
    znane = [c for c in hist if c is not None]
    avg_4t = round(sum(znane) / len(znane), 4) if znane else None

    trend_1t  = None
    trend_avg = None

    if cena_1t and cena_1t > 0:
        trend_1t = round((cena_trenutna / cena_1t - 1) * 100, 1)
    if avg_4t and avg_4t > 0:
        trend_avg = round((cena_trenutna / avg_4t - 1) * 100, 1)

    return {
        "trend_1t":  trend_1t,
        "trend_avg": trend_avg,
        "avg_4t":    avg_4t,
        "cena_1t":   cena_1t,
    }


def _trend_ikona(pct: float | None) -> str:
    if pct is None:
        return "—"
    if pct <= -10:
        return f"🟢🟢 {pct:+.1f}%"
    if pct < 0:
        return f"🟢 {pct:+.1f}%"
    if pct == 0:
        return f"⬜ {pct:+.1f}%"
    if pct <= 5:
        return f"🔴 {pct:+.1f}%"
    return f"🔴🔴 {pct:+.1f}%"


def _render_analiza(tedni: list, trenutni_idx: int, teden_id: str):
    """Prikaže tab Analiza cen za dani teden."""

    N = 4  # število preteklih tednov

    if trenutni_idx == 0 and len(tedni) == 1:
        st.info("Za analizo cen potrebuješ vsaj 2 tedna podatkov.")
        return

    # Zberi zgodovino
    zgodovina = _zberi_zgodovino_cen(tedni, trenutni_idx, n_tednov=N)

    if not zgodovina:
        st.info("V trenutnem tednu ni cenikov dobaviteljev za analizo.")
        return

    # Labeli za pretekle tedne
    pretekli_idx = list(range(max(0, trenutni_idx - N), trenutni_idx))
    hist_labeli = []
    for t_idx in pretekli_idx:
        t = tedni[t_idx]
        hist_labeli.append(t.get("datum_od", f"-{trenutni_idx - t_idx}t")[:10])
    # Dopolni z "—" če je manj kot N tednov
    while len(hist_labeli) < N:
        hist_labeli.insert(0, "—")

    # ── Filter: prag za push listo ─────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns([2, 2, 3])
    with col_f1:
        prag_push = st.number_input(
            "Push lista: prag avg trend (%)",
            value=-5.0, max_value=0.0, step=0.5, format="%.1f",
            key=f"prag_{teden_id}",
            help="Artikli z avg trendom pod tem pragom se pokažejo na push listi"
        )
    with col_f2:
        filter_sklop = st.selectbox(
            "Filtriraj po sklopu",
            ["Vsi"] + SKLOPI,
            key=f"fsk_{teden_id}"
        )
    with col_f3:
        pokazi_samo_spremembe = st.checkbox(
            "Prikaži samo artikle s spremembo cene",
            value=False,
            key=f"samo_spr_{teden_id}"
        )

    st.divider()

    # ── Tabs znotraj analize ───────────────────────────────────────────────
    tab_hist, tab_push = st.tabs(["📈 Gibanje cen", "📣 Push lista"])

    # ══════════════════════════════════
    # TAB: GIBANJE CEN
    # ══════════════════════════════════
    with tab_hist:

        # Glava tabele
        col_w = [2.5, 1.5, 1.2] + [1.0] * N + [1.2, 1.2]
        cols_h = st.columns(col_w)
        headers = ["Artikel", "Dobavitelj", "Sklop"] + hist_labeli + ["Trenutna €", "Trend (1t)", "Trend (avg 4t)"]
        # Popravi — glava ima N+5 stolpcev
        col_w2  = [2.5, 1.5, 1.2] + [1.0] * N + [1.2, 1.2, 1.2]
        cols_h2 = st.columns(col_w2)
        for i, h in enumerate(headers):
            cols_h2[i].markdown(f"**{h}**")
        st.markdown("---")

        # Uredi: najprej po sklopu, nato po avg trendu (najbolj pocenjeni na vrhu)
        def _sort_key(item):
            lat, d = item
            t = _izracunaj_trend(d["cena"], d["hist"])
            avg = t["trend_avg"] if t["trend_avg"] is not None else 999
            sklop_ord = SKLOPI.index(d["sklop"]) if d["sklop"] in SKLOPI else 99
            return (sklop_ord, avg)

        sorted_items = sorted(zgodovina.items(), key=_sort_key)

        for lat, d in sorted_items:
            # Filter po sklopu
            if filter_sklop != "Vsi" and d["sklop"] != filter_sklop:
                continue

            t = _izracunaj_trend(d["cena"], d["hist"])

            # Filter samo spremembe
            if pokazi_samo_spremembe and t["trend_1t"] is None and t["trend_avg"] is None:
                continue

            cols_r = st.columns(col_w2)

            # Artikel + latinski
            cols_r[0].markdown(f"**{d['naziv']}**")

            # Dobavitelj
            cols_r[1].caption(d["dobavitelj"])

            # Sklop
            sklop_label = _sklop_label(d["sklop"], d["poreklo"])
            cols_r[2].caption(sklop_label)

            # Zgodovinske cene — levo→desno = starejše→novejše
            hist_full = d["hist"]
            # Dopolni z None za manjkajoče pretekle tedne (ko imamo manj kot N tednov)
            while len(hist_full) < N:
                hist_full = [None] + hist_full

            for i, hc in enumerate(hist_full):
                if hc is None:
                    cols_r[3 + i].caption("—")
                else:
                    cols_r[3 + i].caption(f"{hc:.2f}")

            # Trenutna cena
            cols_r[3 + N].markdown(f"**{d['cena']:.2f} €**")

            # Trend 1t
            cols_r[3 + N + 1].caption(_trend_ikona(t["trend_1t"]))

            # Trend avg 4t
            cols_r[3 + N + 2].caption(_trend_ikona(t["trend_avg"]))

        st.divider()
        st.caption("🟢🟢 = padec >10%  ·  🟢 = padec  ·  🔴 = rast  ·  🔴🔴 = rast >5%")

    # ══════════════════════════════════
    # TAB: PUSH LISTA
    # ══════════════════════════════════
    with tab_push:
        st.caption(
            f"Artikli kjer je trenutna cena vsaj **{abs(prag_push):.0f}% nižja** od povprečja zadnjih 4 tednov — "
            "primerni za obveščanje strank."
        )

        push_artikli = []
        for lat, d in sorted_items:
            if filter_sklop != "Vsi" and d["sklop"] != filter_sklop:
                continue
            t = _izracunaj_trend(d["cena"], d["hist"])
            if t["trend_avg"] is not None and t["trend_avg"] <= prag_push:
                push_artikli.append((d, t))

        if not push_artikli:
            st.info(f"Ni artiklov z avg trendom ≤ {prag_push:.0f}%. Zmanjšaj prag ali dodaj več tednov podatkov.")
        else:
            # ── Tabela push artiklov ───────────────────────────────────────
            ph = st.columns([3, 1.5, 1.2, 1.2, 1.5, 1.5])
            for h, t in zip(
                ["Artikel", "Dobavitelj", "Trenutna €", "Povp. 4t €", "Trend (avg)", "Trend (1t)"],
                ph
            ):
                t.markdown(f"**{h}**")
            st.markdown("---")

            for d, t in push_artikli:
                pc1, pc2, pc3, pc4, pc5, pc6 = st.columns([3, 1.5, 1.2, 1.2, 1.5, 1.5])
                pc1.markdown(f"**{d['naziv']}**  \n*{d.get('sklop','')}*")
                pc2.caption(d["dobavitelj"])
                pc3.markdown(f"**{d['cena']:.2f} €**")
                avg_str = f"{t['avg_4t']:.2f} €" if t["avg_4t"] else "—"
                pc4.caption(avg_str)
                pc5.markdown(_trend_ikona(t["trend_avg"]))
                pc6.caption(_trend_ikona(t["trend_1t"]))

            st.divider()

            # ── Gumb: Kopiraj za WhatsApp/email ───────────────────────────
            lines = [
                f"🐟 TEDNA AKCIJA — POCENI RIBE ({tedni[trenutni_idx].get('datum_od','?')} – {tedni[trenutni_idx].get('datum_do','?')})",
                "",
            ]
            for d, t in push_artikli:
                avg_str = f"povp. {t['avg_4t']:.2f} €" if t["avg_4t"] else ""
                lines.append(
                    f"✅ {d['naziv']}  {d['cena']:.2f} €/kg  "
                    f"({_trend_ikona(t['trend_avg'])} vs {avg_str})"
                    f"  — {d['dobavitelj']}"
                )
            lines += ["", "Zaloge omejene. Za naročila nas kontaktirajte."]
            push_text = "\n".join(lines)

            st.text_area(
                "Besedilo za WhatsApp / email",
                value=push_text,
                height=200,
                key=f"push_txt_{teden_id}"
            )
            st.caption("Označi vse (Ctrl+A) in kopiraj.")


def _dodaj_artikel_v_nas_cenik(tedni: list, teden_id: str, ime_cenika: str,
                                artikel: dict) -> list:
    """Doda artikel v naš cenik (HIT/HoReCa/Ostali) v ustrezen sklop."""
    for t in tedni:
        if t["id"] != teden_id:
            continue
        sklop = artikel.get("sklop", "Divjaki")
        if sklop not in SKLOPI:
            sklop = "Divjaki"
        t["nasi_ceniki"][ime_cenika][sklop].append(artikel)
    return tedni


def _prestej_artiklov(teden: dict) -> dict:
    """Vrne {cenik_dob: N, HIT: N, HoReCa: N, Ostali: N}."""
    n_dob = sum(len(c.get("artikli", [])) for c in teden.get("ceniki_dob", []))
    nasi  = {}
    for ime in NASI_CENIKI:
        nc = teden.get("nasi_ceniki", {}).get(ime, {})
        nasi[ime] = sum(len(v) for v in nc.values())
    return {"dobavitelji": n_dob, **nasi}


# ─── RENDER ──────────────────────────────────────────────────────────────────

def render():
    st.caption("Tedni ceniki dobaviteljev → HIT / HoReCa / Ostali")

    # Naloži podatke
    if "ceniki_tedni" not in st.session_state:
        st.session_state["ceniki_tedni"] = _load_ceniki()
    tedni: list = st.session_state["ceniki_tedni"]

    # ═══════════════════════════════════════
    # SIDEBAR
    # ═══════════════════════════════════════
    with st.sidebar:
        st.header("⚙️ Nov teden")
        col_a, col_b = st.columns(2)
        with col_a:
            d_od = st.date_input("Od", value=date.today(), key="nt_od")
        with col_b:
            d_do = st.date_input("Do", value=date.today(), key="nt_do")

        if st.button("➕ Ustvari nov teden", use_container_width=True, key="btn_nov_teden"):
            nov = _nov_teden(str(d_od), str(d_do))
            tedni.append(nov)
            tedni.sort(key=lambda t: t.get("datum_od", ""))
            st.session_state["ceniki_tedni"] = tedni
            _save_ceniki(tedni)
            st.rerun()

        st.divider()
        st.caption(f"Skupaj tednov: {len(tedni)}")

    # ═══════════════════════════════════════
    # GLAVNI PRIKAZ
    # ═══════════════════════════════════════
    if not tedni:
        st.info("Še ni tednov. Ustvari prvi teden v stranskem meniju.")
        return

    # Prikaz tednov — najstarejši na vrhu
    for t_idx, teden in enumerate(tedni):
        st_info = _prestej_artiklov(teden)
        teden_label = (
            f"📅 {teden['datum_od']} – {teden['datum_do']}  ·  "
            f"{len(teden.get('ceniki_dob', []))} dobaviteljev  ·  "
            f"{st_info['dobavitelji']} artiklov  ·  "
            f"HIT: {st_info.get('HIT',0)}  HoReCa: {st_info.get('HoReCa',0)}  Ostali: {st_info.get('Ostali',0)}"
        )

        with st.expander(teden_label, expanded=(t_idx == len(tedni) - 1)):

            # Gumb za brisanje tedna
            col_del, col_info = st.columns([1, 6])
            with col_del:
                if st.button("🗑️ Izbriši teden", key=f"del_teden_{teden['id']}"):
                    tedni = [t for t in tedni if t["id"] != teden["id"]]
                    st.session_state["ceniki_tedni"] = tedni
                    _save_ceniki(tedni)
                    st.rerun()
            with col_info:
                st.caption(f"ID: {teden['id']}  ·  Ustvarjen: {teden.get('ustvarjen','?')}")

            # ── Tabs ────────────────────────────────────────────────────────
            tab_dob, tab_hit, tab_horeca, tab_ostali, tab_analiza = st.tabs([
                "📥 Ceniki dobaviteljev",
                "⭐ HIT",
                "🍽️ HoReCa",
                "📦 Ostali",
                "📊 Analiza cen",
            ])

            # ════════════════════════════════════════
            # TAB: CENIKI DOBAVITELJEV
            # ════════════════════════════════════════
            with tab_dob:

                # Upload PDF
                _tid = teden['id']
                _up_reset_n = st.session_state.get(f"up_reset_{_tid}", 0)
                upload_key = f"up_{_tid}_{_up_reset_n}"
                pdfs = st.file_uploader(
                    "Naloži cenike dobaviteljev (PDF)",
                    type=["pdf"],
                    accept_multiple_files=True,
                    key=upload_key,
                    label_visibility="collapsed",
                )

                if pdfs:
                    prog = st.progress(0)
                    for i, f in enumerate(pdfs):
                        prog.progress((i + 1) / len(pdfs), text=f"Berem {f.name} …")
                        pdf_bytes = f.read()
                        parsed, err = _parse_pdf_claude(pdf_bytes)
                        if err or not parsed:
                            st.error(f"❌ {f.name}: {err or 'AI ni vrnil podatkov'}")
                            continue
                        # Preveri če ta dobavitelj že obstaja za ta teden
                        dob_ime = parsed.get("dobavitelj", f.name)
                        obstaja = any(
                            c.get("dobavitelj", "").lower() == dob_ime.lower()
                            for c in teden.get("ceniki_dob", [])
                        )
                        if obstaja:
                            st.warning(f"⚠️ Cenik za '{dob_ime}' že obstaja v tem tednu — preskočen.")
                            continue
                        teden["ceniki_dob"].append({
                            "id":          str(uuid.uuid4())[:8],
                            "dobavitelj":  dob_ime,
                            "datum":       parsed.get("datum", ""),
                            "valuta":      parsed.get("valuta", "EUR"),
                            "fname":       f.name,
                            "artikli":     parsed.get("artikli", []),
                            "uvozeno":     datetime.now().isoformat()[:16],
                        })
                        st.success(f"✅ {dob_ime}: {len(parsed.get('artikli', []))} artiklov")
                    prog.empty()
                    # Reset uploaderja
                    reset_n = st.session_state.get(f"up_reset_{teden['id']}", 0)
                    st.session_state[f"up_reset_{teden['id']}"] = reset_n + 1
                    st.session_state["ceniki_tedni"] = tedni
                    _save_ceniki(tedni)
                    st.rerun()

                # Prikaz naloženih cenikov dobaviteljev
                if not teden.get("ceniki_dob"):
                    st.caption("Naloži PDF cenike dobaviteljev z gumbom zgoraj.")
                else:
                    for c_idx, cenik in enumerate(teden["ceniki_dob"]):
                        c_label = (
                            f"🏭 **{cenik['dobavitelj']}**  ·  "
                            f"{cenik.get('datum','?')}  ·  "
                            f"{len(cenik.get('artikli',[]))} artiklov  ·  "
                            f"{cenik.get('fname','')}"
                        )
                        col_exp, col_rm = st.columns([11, 1])
                        with col_rm:
                            if st.button("✕", key=f"rm_dob_{teden['id']}_{cenik['id']}",
                                         help="Odstrani cenik dobavitelja"):
                                teden["ceniki_dob"] = [
                                    c for c in teden["ceniki_dob"] if c["id"] != cenik["id"]
                                ]
                                st.session_state["ceniki_tedni"] = tedni
                                _save_ceniki(tedni)
                                st.rerun()
                        with col_exp:
                            with st.expander(c_label, expanded=False):
                                artikli = cenik.get("artikli", [])
                                if not artikli:
                                    st.caption("Ni artiklov.")
                                else:
                                    # Tabela artiklov
                                    for a_idx, art in enumerate(artikli):
                                        ac1, ac2, ac3, ac4, ac5, ac6 = st.columns([3, 2, 1, 1, 1, 2])
                                        with ac1:
                                            new_naziv = st.text_input(
                                                "Naziv", value=art.get("naziv", ""),
                                                key=f"an_{teden['id']}_{cenik['id']}_{a_idx}",
                                                label_visibility="collapsed"
                                            )
                                            art["naziv"] = new_naziv
                                        with ac2:
                                            st.caption(art.get("latinski_naziv", ""))
                                        with ac3:
                                            new_cena = st.number_input(
                                                "€", value=float(art.get("cena", 0)),
                                                min_value=0.0, step=0.01, format="%.2f",
                                                key=f"ac_{teden['id']}_{cenik['id']}_{a_idx}",
                                                label_visibility="collapsed"
                                            )
                                            art["cena"] = new_cena
                                        with ac4:
                                            st.caption(art.get("enota", "kg"))
                                        with ac5:
                                            st.caption(art.get("poreklo", ""))
                                        with ac6:
                                            sklop_opts = SKLOPI
                                            cur_sklop  = art.get("sklop", "Divjaki")
                                            sklop_idx  = sklop_opts.index(cur_sklop) if cur_sklop in sklop_opts else 1
                                            new_sklop  = st.selectbox(
                                                "Sklop",
                                                sklop_opts, index=sklop_idx,
                                                key=f"as_{teden['id']}_{cenik['id']}_{a_idx}",
                                                label_visibility="collapsed"
                                            )
                                            art["sklop"] = new_sklop

                                    if st.button("💾 Shrani popravke", key=f"save_dob_{teden['id']}_{cenik['id']}"):
                                        st.session_state["ceniki_tedni"] = tedni
                                        _save_ceniki(tedni)
                                        st.success("Shranjeno.")

            # ════════════════════════════════════════
            # SKUPNA LOGIKA ZA NAŠE CENIKE
            # ════════════════════════════════════════
            def _render_nas_cenik(ime_cenika: str, tab_key: str):
                """Prikaže in uredi naš cenik (HIT / HoReCa / Ostali)."""
                nas_cenik = teden["nasi_ceniki"][ime_cenika]

                # ── Gumb: Samodejno sestavi iz najcenejših ──────────────
                st.caption(
                    "Samodejno sestavi: vzame najcenejšo ceno za vsak artikel med vsemi dobavitelji tega tedna."
                )
                if st.button(
                    f"🤖 Samodejno sestavi {ime_cenika}",
                    key=f"auto_{teden['id']}_{ime_cenika}",
                    disabled=not teden.get("ceniki_dob"),
                ):
                    # Zberi vse artikle iz vseh cenikov dobaviteljev
                    vse: dict = {}  # latinski_naziv → {best_art, dobavitelj}
                    for cenik in teden["ceniki_dob"]:
                        for art in cenik.get("artikli", []):
                            lat   = (art.get("latinski_naziv") or art.get("naziv", "")).lower().strip()
                            cena  = float(art.get("cena", 0))
                            if not lat or cena <= 0:
                                continue
                            if lat not in vse or cena < vse[lat]["cena"]:
                                vse[lat] = {
                                    "naziv":         art.get("naziv", ""),
                                    "latinski_naziv":art.get("latinski_naziv", ""),
                                    "cena":          cena,
                                    "enota":         art.get("enota", "kg"),
                                    "poreklo":       art.get("poreklo", ""),
                                    "sklop":         art.get("sklop", "Divjaki"),
                                    "cena_prodajna": 0.0,
                                    "marza_pct":     0.0,
                                    "dobavitelj":    cenik.get("dobavitelj", ""),
                                    "komentar":      art.get("komentar", ""),
                                }
                    # Razvrsti v sklope
                    for sklop in SKLOPI:
                        nas_cenik[sklop] = []
                    for art_data in vse.values():
                        sklop = art_data.get("sklop", "Divjaki")
                        if sklop not in SKLOPI:
                            sklop = "Divjaki"
                        nas_cenik[sklop].append(art_data)
                    # Uredi po ceni znotraj sklopa
                    for sklop in SKLOPI:
                        nas_cenik[sklop].sort(key=lambda x: x.get("cena", 0))
                    teden["nasi_ceniki"][ime_cenika] = nas_cenik
                    st.session_state["ceniki_tedni"] = tedni
                    _save_ceniki(tedni)
                    st.rerun()

                # ── Ročno dodajanje artikla ─────────────────────────────
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

                    if st.button("Dodaj", key=f"radd_{teden['id']}_{ime_cenika}"):
                        if r_naziv:
                            nas_cenik[r_sklop].append({
                                "naziv":          r_naziv,
                                "latinski_naziv": r_lat,
                                "cena":           r_cena,
                                "cena_prodajna":  r_prod,
                                "marza_pct":      round((r_prod / r_cena - 1) * 100, 1) if r_cena > 0 else 0,
                                "enota":          "kg",
                                "poreklo":        r_por,
                                "sklop":          r_sklop,
                                "dobavitelj":     r_dob,
                                "komentar":       "",
                            })
                            st.session_state["ceniki_tedni"] = tedni
                            _save_ceniki(tedni)
                            st.rerun()

                # ── Prikaz po sklopih ───────────────────────────────────
                total_art = sum(len(nas_cenik.get(s, [])) for s in SKLOPI)
                if total_art == 0:
                    st.info("Cenik je prazen. Uporabi 'Samodejno sestavi' ali dodaj ročno.")
                    return

                for sklop in SKLOPI:
                    artikli_sklop = nas_cenik.get(sklop, [])
                    if not artikli_sklop:
                        continue

                    # Glava sklopa
                    if sklop == "Gojeno":
                        # Razčleni po državah
                        po_drzavah: dict = {}
                        for art in artikli_sklop:
                            por = art.get("poreklo", "??").upper()
                            po_drzavah.setdefault(por, []).append(art)
                        for por_code, arts in sorted(po_drzavah.items()):
                            drzava = GOJENO_DRZAVE.get(por_code, por_code)
                            st.markdown(f"#### 🐟 Gojeno — {drzava}")
                            _render_sklop_tabela(arts, sklop, por_code, teden, ime_cenika, nas_cenik, tedni)
                    else:
                        ikona = "🌊" if sklop == "Divjaki" else "🏔️"
                        st.markdown(f"#### {ikona} {sklop}")
                        _render_sklop_tabela(artikli_sklop, sklop, "", teden, ime_cenika, nas_cenik, tedni)

                # Shrani gumb
                if st.button(f"💾 Shrani {ime_cenika}", key=f"save_{teden['id']}_{ime_cenika}",
                              type="primary", use_container_width=True):
                    st.session_state["ceniki_tedni"] = tedni
                    _save_ceniki(tedni)
                    st.success("Shranjeno.")

            def _render_sklop_tabela(artikli: list, sklop: str, por_filter: str,
                                     teden: dict, ime_cenika: str, nas_cenik: dict, tedni: list):
                """Prikaže tabelo artiklov za en sklop/državo."""
                # Glava tabele
                h0, h1, h2, h3, h4, h5, h6, h7 = st.columns([3, 2, 1.2, 1.2, 1.2, 1, 1.5, 0.6])
                h0.markdown("**Naziv**")
                h1.markdown("**Latinski naziv**")
                h2.markdown("**Nakupna €**")
                h3.markdown("**Prod. €**")
                h4.markdown("**Marža %**")
                h5.markdown("**Por.**")
                h6.markdown("**Dobavitelj ↙**")
                h7.markdown("")
                st.markdown("---")

                # Poišči vse dobaviteljeve cene za primerjavo
                vse_cene_cache: dict = {}

                for a_idx, art in enumerate(artikli):
                    lat_key = (art.get("latinski_naziv") or art.get("naziv", "")).lower().strip()

                    # Primerljive cene (za tooltip / primerjavo)
                    if lat_key not in vse_cene_cache:
                        primerjave = []
                        for cenik in teden.get("ceniki_dob", []):
                            for a2 in cenik.get("artikli", []):
                                lat2 = (a2.get("latinski_naziv") or a2.get("naziv","")).lower().strip()
                                if lat2 == lat_key:
                                    primerjave.append(
                                        f"{cenik['dobavitelj']}: {a2.get('cena',0):.2f} €"
                                    )
                        vse_cene_cache[lat_key] = primerjave
                    primerjave = vse_cene_cache[lat_key]

                    # Unikatni ključi
                    uid = f"{teden['id']}_{ime_cenika}_{sklop}_{por_filter}_{a_idx}"

                    c0, c1, c2, c3, c4, c5, c6, c7 = st.columns([3, 2, 1.2, 1.2, 1.2, 1, 1.5, 0.6])
                    with c0:
                        art["naziv"] = st.text_input(
                            "naziv", value=art.get("naziv", ""),
                            key=f"naziv_{uid}", label_visibility="collapsed"
                        )
                    with c1:
                        st.caption(art.get("latinski_naziv", ""))
                    with c2:
                        art["cena"] = st.number_input(
                            "nc", value=float(art.get("cena", 0)),
                            min_value=0.0, step=0.01, format="%.2f",
                            key=f"cena_{uid}", label_visibility="collapsed"
                        )
                    with c3:
                        old_prod = float(art.get("cena_prodajna", 0))
                        art["cena_prodajna"] = st.number_input(
                            "pc", value=old_prod,
                            min_value=0.0, step=0.01, format="%.2f",
                            key=f"prod_{uid}", label_visibility="collapsed"
                        )
                    with c4:
                        nc = float(art.get("cena", 0))
                        pc = float(art.get("cena_prodajna", 0))
                        if nc > 0 and pc > 0:
                            marza = round((pc / nc - 1) * 100, 1)
                            art["marza_pct"] = marza
                            st.metric("", f"{marza:.1f}%", label_visibility="collapsed")
                        else:
                            st.caption("—")
                    with c5:
                        st.caption(art.get("poreklo", ""))
                    with c6:
                        dob = art.get("dobavitelj", "")
                        if primerjave and len(primerjave) > 1:
                            st.caption(f"✅ {dob}", help="\n".join(primerjave))
                        else:
                            st.caption(dob)
                    with c7:
                        if st.button("✕", key=f"rm_{uid}", help="Odstrani artikel"):
                            artikli.pop(a_idx)
                            st.session_state["ceniki_tedni"] = tedni
                            _save_ceniki(tedni)
                            st.rerun()

            # ════════════════════════════════════════
            # POVEŽI TABS Z NAŠIMI CENIKI
            # ════════════════════════════════════════
            with tab_hit:
                _render_nas_cenik("HIT", f"hit_{teden['id']}")

            with tab_horeca:
                _render_nas_cenik("HoReCa", f"horeca_{teden['id']}")

            with tab_ostali:
                _render_nas_cenik("Ostali", f"ostali_{teden['id']}")

            with tab_analiza:
                _render_analiza(tedni, t_idx, teden["id"])

    # Shrani vse spremembe ob koncu rendera
    st.session_state["ceniki_tedni"] = tedni
    _save_ceniki(tedni)
