"""
Tab: Temeljnice — dnevni izkupiček
Ureja: chat "Ločeni procesi za knjiženje blagajn"
"""

import streamlit as st
import pandas as pd
from collections import defaultdict
import traceback

from minimax_client import BLAGAJNE
from config import get_client, check_config


def render():
    st.caption("Pregled osnutkov temeljnic, popravek knjižb in navodila za vnos v blagajno")

    col_btn, col_debug, col_space = st.columns([1, 1, 1])
    with col_btn:
        scan_btn = st.button("🔍 Poišči osnutke temeljnic", type="primary",
                             use_container_width=True, key="scan_journals")
    with col_debug:
        debug_btn = st.button("🔧 Debug API", use_container_width=True, key="debug_journals")

    if debug_btn:
        if not check_config(): st.stop()
        with st.spinner("Kličem API ..."):
            try:
                data = get_client().get_journal_drafts_debug()
                st.json(data)
            except Exception as e:
                st.error(f"Napaka: {e}")

    if scan_btn:
        if not check_config(): st.stop()
        with st.spinner("Iščem osnutke temeljnic ..."):
            try:
                cli         = get_client()
                osnutki_raw = cli.get_journal_drafts()
                osnutki     = []
                for j in osnutki_raw:
                    podatki = cli.parse_journal_placila(j)
                    if podatki:
                        osnutki.append(podatki)
                st.session_state["journal_osnutki"] = osnutki
                st.session_state.pop("journal_rezultat", None)
            except Exception as e:
                st.error(f"Napaka: {e}")
                st.error(traceback.format_exc())

    osnutki = st.session_state.get("journal_osnutki", None)

    if osnutki is None:
        st.info("👆 Kliknite 'Poišči osnutke temeljnic' za začetek.")
        return

    if len(osnutki) == 0:
        st.success("✅ Ni osnutkov temeljnic za obdelavo.")
        return

    st.divider()
    st.subheader(f"Najdenih {len(osnutki)} osnutkov")

    sel_all_j = st.checkbox("☑ Izberi vse", value=True, key="j_sel_all")
    izbrani   = []

    # ── Prikaz po datumih, znotraj po analitiki ───────────────────────────────
    po_datumih = defaultdict(list)
    for o in osnutki:
        po_datumih[o["datum"]].append(o)

    for datum in sorted(po_datumih.keys()):
        skupina_datum = sorted(po_datumih[datum], key=lambda x: x["analitika_sifra"])
        gotovina_dan  = sum(o["znesek_gotovina"] for o in skupina_datum)
        kartica_dan   = sum(o["znesek_kartica"]  for o in skupina_datum)
        skupaj_dan    = sum(o["skupaj"]           for o in skupina_datum)

        st.markdown(
            f"### 📅 {datum} &nbsp;&nbsp;"
            f"<small>gotovina: **{gotovina_dan:.2f} €** &nbsp;|&nbsp; "
            f"kartica: **{kartica_dan:.2f} €** &nbsp;|&nbsp; "
            f"skupaj: **{skupaj_dan:.2f} €**</small>",
            unsafe_allow_html=True
        )

        hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([0.5, 2, 1.5, 1, 1, 1])
        hc1.markdown("**✓**")
        hc2.markdown("**Blagajna**")
        hc3.markdown("**Vrsta plačila**")
        hc4.markdown("**Gotovina (1000)**")
        hc5.markdown("**Kartica (1652)**")
        hc6.markdown("**Skupaj**")

        for o in skupina_datum:
            if o["rezim"] == "oba":
                vrsta = "Gotovina + Kartica"
            elif o["rezim"] == "samo_kartica":
                vrsta = "Samo kartica"
            else:
                vrsta = "Samo gotovina"

            c1, c2, c3, c4, c5, c6 = st.columns([0.5, 2, 1.5, 1, 1, 1])
            checked = c1.checkbox("", value=sel_all_j,
                                  key=f"jcb_{o['journal_id']}",
                                  label_visibility="collapsed")
            c2.write(f"**{o['analitika_sifra']}** — {o['blagajna_naziv']}")
            c3.write(vrsta)
            c4.write(f"{o['znesek_gotovina']:.2f} €" if o["znesek_gotovina"] else "—")
            c5.write(f"{o['znesek_kartica']:.2f} €"  if o["znesek_kartica"]  else "—")
            c6.write(f"**{o['skupaj']:.2f} €**")
            if checked:
                izbrani.append(o)

            with st.expander("📋 Navodila za vnos v blagajno"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Blagajniški PREJEMEK:**")
                    st.markdown(f"- Stranka: `Končni kupec - maloprodaja`")
                    st.markdown(f"- Analitika: `{o['analitika_polno']}`")
                    st.markdown(f"- Tip: `Dnevni iztržek`")
                    st.markdown(f"- Znesek: **{o['skupaj']:.2f} €**")
                with col2:
                    st.markdown("**Blagajniški IZDATEK:**")
                    st.markdown(f"- Analitika: `{o['analitika_polno']}`")
                    if o["rezim"] in ("oba", "samo_gotovina"):
                        st.markdown(f"- Polog gotovine - domača DE: **{o['znesek_gotovina']:.2f} €**")
                    if o["rezim"] in ("oba", "samo_kartica"):
                        st.markdown(f"- Terjatev za plačila z kartico: **{o['znesek_kartica']:.2f} €**")

        st.divider()

    # ── Seštevek po dnevih ────────────────────────────────────────────────────
    st.subheader("📊 Seštevek po dnevih")
    st.caption("Za primerjavo s POS poročilom plačil")

    vrstice = []
    for datum in sorted(po_datumih.keys()):
        skupina = po_datumih[datum]
        for o in sorted(skupina, key=lambda x: x["analitika_sifra"]):
            vrstice.append({
                "Datum":           datum,
                "Blagajna":        f"{o['analitika_sifra']} — {o['blagajna_naziv']}",
                "Gotovina (1000)": f"{o['znesek_gotovina']:.2f} €" if o["znesek_gotovina"] else "—",
                "Kartica (1652)":  f"{o['znesek_kartica']:.2f} €"  if o["znesek_kartica"]  else "—",
                "Skupaj":          f"{o['skupaj']:.2f} €",
            })
        got_dan = sum(o["znesek_gotovina"] for o in skupina)
        kar_dan = sum(o["znesek_kartica"]  for o in skupina)
        vrstice.append({
            "Datum":           f"  ∑ {datum}",
            "Blagajna":        "",
            "Gotovina (1000)": f"{got_dan:.2f} €",
            "Kartica (1652)":  f"{kar_dan:.2f} €",
            "Skupaj":          f"{round(got_dan + kar_dan, 2):.2f} €",
        })

    vrstice.append({
        "Datum":           "SKUPAJ VSE",
        "Blagajna":        "",
        "Gotovina (1000)": f"{sum(o['znesek_gotovina'] for o in osnutki):.2f} €",
        "Kartica (1652)":  f"{sum(o['znesek_kartica']  for o in osnutki):.2f} €",
        "Skupaj":          f"{sum(o['skupaj'] for o in osnutki):.2f} €",
    })

    st.dataframe(pd.DataFrame(vrstice), use_container_width=True, hide_index=True)

    # ── Obdelava ──────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("⚙️ Popravi in potrdi temeljnice")
    st.info("Ko si ročno vnesel blagajniške dokumente, klikni spodaj da agent popravi knjižbe in potrdi temeljnice.")

    if izbrani:
        m1, m2, m3 = st.columns(3)
        m1.metric("Izbranih", len(izbrani))
        m2.metric("Blagajn", len(set(o["analitika_sifra"] for o in izbrani)))
        m3.metric("Skupaj", f"{sum(o['skupaj'] for o in izbrani):.2f} €")

    run_j_btn = st.button(
        f"▶️ Popravi in potrdi {len(izbrani)} temeljnic",
        type="primary", use_container_width=True,
        key="run_journals", disabled=len(izbrani) == 0,
    )

    if run_j_btn and izbrani:
        if not check_config(): st.stop()
        with st.spinner("Popravljam temeljnice ..."):
            cli     = get_client()
            uspesno = []
            napake  = []
            for o in izbrani:
                try:
                    cli.popravi_in_potrdi_journal(o)
                    uspesno.append(o)
                except Exception as e:
                    napake.append({"blagajna": o["blagajna_naziv"], "datum": o["datum"], "napaka": str(e)})

            if uspesno:
                st.success(f"✅ {len(uspesno)} temeljnic uspešno popravljenih in potrjenih!")
                st.dataframe(pd.DataFrame([{
                    "Datum": o["datum"], "Blagajna": o["blagajna_naziv"], "Skupaj": f"{o['skupaj']:.2f} €",
                } for o in uspesno]), use_container_width=True, hide_index=True)

            if napake:
                st.error(f"❌ {len(napake)} napak:")
                for n in napake:
                    st.error(f"{n['datum']} | {n['blagajna']}: {n['napaka']}")

            st.session_state.pop("journal_osnutki", None)
            if not napake:
                st.rerun()
