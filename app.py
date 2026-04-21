"""
Agent Hub — Glavna navigacija.
Vsak tab je v svojem modulu:
  tab_loti.py        — dodelitev lotov
  tab_temeljnice.py  — dnevni izkupiček / blagajne
"""

import streamlit as st
from tab_loti import render as render_loti
from tab_temeljnice import render as render_temeljnice

st.set_page_config(
    page_title="Agent Hub",
    page_icon="🐟",
    layout="wide",
)

st.title("🐟 Agent Hub")

main_tab1, main_tab2 = st.tabs([
    "📦 Loti — dodelitev serij",
    "💰 Temeljnice — dnevni izkupiček",
])

with main_tab1:
    render_loti()

with main_tab2:
    render_temeljnice()

st.divider()
st.caption("Agent Hub v2.1 · Minimax API · Loti + Temeljnice")
