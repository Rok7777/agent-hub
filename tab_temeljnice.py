"""
Tab: Temeljnice — dnevni izkupiček
Ureja: Gazda AI
Samostojen modul — brez config.py
"""

import io
import os
import streamlit as st
import pandas as pd
from collections import defaultdict
import traceback

from minimax_client import MinimaxClient, BLAGAJNE


def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


def _make_client() -> MinimaxClient:
    return MinimaxClient(
        username      = st.session_state.get("username",      _secret("MINIMAX_USERNAME", "")),
        password      = st.session_state.get("password",      _secret("MINIMAX_PASSWORD", "")),
        client_id     = st.session_state.get("client_id",     _secret("MINIMAX_CLIENT_ID", "")),
        client_secret = st.session_state.get("client_secret", _secret("MINIMAX_CLIENT_SECRET", "")),
        org_id        = int(st.session_state.get("org_id",    _secret("MINIMAX_ORG_ID", "171038"))),
    )


def _check_config() -> bool:
    u  = st.session_state.get("username",      _secret("MINIMAX_USERNAME", ""))
    p  = st.session_state.get("password",      _secret("MINIMAX_PASSWORD", ""))
    ci = st.session_state.get("client_id",     _secret("MINIMAX_CLIENT_ID", ""))
    cs = st.session_state.get("client_secret", _secret("MINIMAX_CLIENT_SECRET", ""))
    if not all([u, p, ci, cs]):
        st.warning("⚠️ Izpolnite vse nastavitve API v stranski vrstici (odprite Loti tab).")
        return False
    return True


def _excel_download(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Temeljnice")
        ws = writer.sheets["Temeljnice"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col) + 4
            ws.column_dimensions[col[0].column_letter].width = min(max_len, 50)
    return buf.getvalue()


def render():
    st.caption("Pregled osnutkov temeljnic, popravek knjižb in navodila za vnos v blagajno")

    col_btn, col_debug, col_space = st.columns([1, 1, 1])
    with col_btn:
        scan_btn = st.button("🔍 Poišči osnutke temeljnic", type="primary",
                             use_container_width=True, key="scan_journals")
    with col_debug:
        debug_btn = st.button("🔧 Debug API", use_container_width=True, key="debug_journals")

    if debug_btn:
        if not _check_config(): st.stop()
        with st.spinner("Kličem API ..."):
            try:
                data = _make_client().get_journal_drafts_debug()
                st.json(data)
            except Exception as e:
                st.error(f"Napaka: {e}")

    if scan_btn:
        if not _check_config(): st.stop()
        with st.spinner("Iščem osnutke temeljnic ..."):
            try:
                cli         = _make_client()
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

    # ── Prikaz po blagajnah, znotraj po datumih ──────────────────────────────
    po_blagajnah = defaultdict(list)
    for o in osnutki:
        sifra = o.get("analitika_sifra") or "—"
        po_blagajnah[sifra].append(o)

    for blagajna_sifra in sorted(po_blagajnah.keys()):
        skupina = sorted(po_blagajnah[blagajna_sifra], key=lambda x: x["datum"])
        naziv    = skupina[0].get("blagajna_naziv") or blagajna_sifra
        got_blag = sum(o["znesek_gotovina"] for o in skupina)
        kar_blag = sum(o["znesek_kartica"]  for o in skupina)
        skup_blag = sum(o["skupaj"]          for o in skupina)

        st.markdown(
            f"### 🏪 {blagajna_sifra} — {naziv} &nbsp;&nbsp;"
            f"<small>gotovina: **{got_blag:.2f} €** &nbsp;|&nbsp; "
            f"kartica: **{kar_blag:.2f} €** &nbsp;|&nbsp; "
            f"skupaj: **{skup_blag:.2f} €**</small>",
            unsafe_allow_html=True
        )

        hc1, hc2, hc3, hc4, hc5, hc6 = st.columns([0.5, 1.5, 1.5, 1, 1, 1])
        hc1.markdown("**✓**")
        hc2.markdown("**Datum**")
        hc3.markdown("**Vrsta plačila**")
        hc4.markdown("**Gotovina (1000)**")
        hc5.markdown("**Kartica (1652)**")
        hc6.markdown("**Skupaj**")

        for o in skupina:
            if o["rezim"] == "oba":            vrsta = "Gotovina + Kartica"
            elif o["rezim"] == "samo_kartica": vrsta = "Samo kartica"
            else:                              vrsta = "Samo gotovina"

            c1, c2, c3, c4, c5, c6 = st.columns([0.5, 1.5, 1.5, 1, 1, 1])
            checked = c1.checkbox("", value=sel_all_j,
                                  key=f"jcb_{o['journal_id']}",
                                  label_visibility="collapsed")
            c2.write(f"**{o['datum']}**")
            c3.write(vrsta)
            c4.write(f"{o['znesek_gotovina']:.2f} €" if o["znesek_gotovina"] else "—")
            c5.write(f"{o['znesek_kartica']:.2f} €"  if o["znesek_kartica"]  else "—")
            c6.write(f"**{o['skupaj']:.2f} €**")
            if checked:
                izbrani.append(o)

            an_prikaz = o.get("analitika_polno") or o.get("analitika_sifra") or "—"
            with st.expander(f"📋 Navodila — {o['datum']}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Blagajniški PREJEMEK:**")
                    st.markdown(f"- Stranka: `Končni kupec - maloprodaja`")
                    st.markdown(f"- Analitika: `{an_prikaz}`")
                    st.markdown(f"- Tip: `Dnevni iztržek`")
                    st.markdown(f"- Znesek: **{o['skupaj']:.2f} €**")
                with col2:
                    st.markdown("**Blagajniški IZDATEK:**")
                    st.markdown(f"- Analitika: `{an_prikaz}`")
                    if o["rezim"] in ("oba", "samo_gotovina"):
                        st.markdown(f"- Polog gotovine - domača DE: **{o['znesek_gotovina']:.2f} €**")
                    if o["rezim"] in ("oba", "samo_kartica"):
                        st.markdown(f"- Terjatev za plačila z kartico: **{o['znesek_kartica']:.2f} €**")

        st.divider()

    # ── Seštevek po dnevih ────────────────────────────────────────────────────
    st.subheader("📊 Seštevek po dnevih")
    st.caption("Za primerjavo s POS poročilom plačil")

    vrstice = []
    for o in sorted(osnutki, key=lambda x: (x.get("analitika_sifra",""), x["datum"])):
        sifra = o.get("analitika_sifra") or "—"
        naziv = o.get("blagajna_naziv") or ""
        vrstice.append({
            "Blagajna":        f"{sifra} — {naziv}" if naziv else sifra,
            "Datum":           o["datum"],
            "Gotovina (1000)": f"{o['znesek_gotovina']:.2f} €" if o["znesek_gotovina"] else "—",
            "Kartica (1652)":  f"{o['znesek_kartica']:.2f} €"  if o["znesek_kartica"]  else "—",
            "Skupaj":          f"{o['skupaj']:.2f} €",
        })

    vrstice.append({
        "Datum":           "SKUPAJ VSE",
        "Blagajna":        "",
        "Gotovina (1000)": f"{sum(o['znesek_gotovina'] for o in osnutki):.2f} €",
        "Kartica (1652)":  f"{sum(o['znesek_kartica']  for o in osnutki):.2f} €",
        "Skupaj":          f"{sum(o['skupaj'] for o in osnutki):.2f} €",
    })

    df_sestevek = pd.DataFrame(vrstice)
    st.dataframe(df_sestevek, use_container_width=True, hide_index=True)

    xlsx = _excel_download(df_sestevek)
    st.download_button(
        label="⬇️ Prenesi seštevek (Excel)",
        data=xlsx,
        file_name=f"sestevek_temeljnice_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

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
        if not _check_config(): st.stop()
        with st.spinner("Popravljam temeljnice ..."):
            cli     = _make_client()
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
