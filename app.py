"""
Agent Hub — Glavna navigacija.
Moduli:
  tab_loti.py        — dodelitev lotov (ureja chat "Zapiranje LOT")
  tab_temeljnice.py  — dnevni izkupiček (ureja chat "Ločeni procesi")
  minimax_client.py  — API klient (ureja chat "Ločeni procesi")
"""

import streamlit as st

st.set_page_config(
    page_title="Agent Hub",
    page_icon="🐟",
    layout="wide",
)

# ── Navigacija ────────────────────────────────────────────────────────────────

MODULI = {
    "loti":        {"icon": "📦", "naziv": "Loti — dodelitev serij",        "opis": "FIFO dodelitev lotov maloprodajnim dokumentom iz Shopsy",    "status": "aktiven"},
    "temeljnice":  {"icon": "💰", "naziv": "Temeljnice — dnevni izkupiček", "opis": "Popravek knjižb in potrjevanje temeljnic MP",                 "status": "aktiven"},
    "prenos_mp":   {"icon": "🚛", "naziv": "Prenos med skladišči",          "opis": "Kreacija prenosov glede na zahteve prodajalcev MP",           "status": "kmalu"},
    "veleprodaja": {"icon": "📋", "naziv": "Veleprodaja",                   "opis": "Kreacija dobavnic in IR na podlagi naročil strank",           "status": "kmalu"},
    "prejem":      {"icon": "📥", "naziv": "Prejem blaga",                  "opis": "Vnos dobavnic dobaviteljev v prejem in knjiženje PR",         "status": "kmalu"},
}

if "aktiven_modul" not in st.session_state:
    st.session_state["aktiven_modul"] = None

# ── Hub prikaz ────────────────────────────────────────────────────────────────

if st.session_state["aktiven_modul"] is None:
    st.title("🐟 Agent Hub")
    st.caption("Izberite modul za začetek")
    st.divider()

    col1, col2, col3 = st.columns(3)
    cols = [col1, col2, col3]

    for i, (key, m) in enumerate(MODULI.items()):
        with cols[i % 3]:
            aktiven = m["status"] == "aktiven"
            with st.container(border=True):
                st.markdown(f"### {m['icon']} {m['naziv']}")
                st.caption(m["opis"])
                if aktiven:
                    if st.button("Odpri", key=f"btn_{key}", use_container_width=True, type="primary"):
                        st.session_state["aktiven_modul"] = key
                        st.rerun()
                else:
                    st.button("Kmalu", key=f"btn_{key}", use_container_width=True, disabled=True)

# ── Modul prikaz ──────────────────────────────────────────────────────────────

else:
    modul = st.session_state["aktiven_modul"]
    m     = MODULI[modul]

    col_back, col_title = st.columns([1, 8])
    with col_back:
        if st.button("← Nazaj"):
            st.session_state["aktiven_modul"] = None
            st.rerun()
    with col_title:
        st.title(f"{m['icon']} {m['naziv']}")

    st.divider()

    if modul == "loti":
        from tab_loti import render
        render()
    elif modul == "temeljnice":
        from tab_temeljnice import render
        render()

st.divider()
st.caption("Agent Hub v2.2 · Minimax API")
