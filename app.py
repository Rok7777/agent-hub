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

if "aktiven_modul" not in st.session_state:
    st.session_state["aktiven_modul"] = None

# ══════════════════════════════════════════════════════════════════════════════
# HUB
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state["aktiven_modul"] is None:

    st.markdown("""
    <style>
    .master-box {
        background: linear-gradient(135deg, #534AB7, #7F77DD);
        border-radius: 14px; padding: 18px 24px;
        text-align: center; color: white; margin-bottom: 8px;
    }
    .master-box h2 { margin:0; font-size:20px; }
    .master-box p  { margin:4px 0 0; font-size:13px; opacity:0.85; }
    .trigger-auto  { background:#e8f5e9; border:1px solid #a5d6a7; border-radius:6px;
                     padding:4px 10px; font-size:11px; color:#2e7d32; text-align:center; margin-top:4px; }
    .trigger-man   { background:#fff8e1; border:1px solid #ffe082; border-radius:6px;
                     padding:4px 10px; font-size:11px; color:#f57f17; text-align:center; margin-top:4px; }
    .modul-kmalu   { background:#f5f5f5; border:1.5px dashed #ccc; border-radius:12px;
                     padding:16px 12px; text-align:center; opacity:0.65; }
    .modul-kmalu h4 { margin:4px 0; font-size:14px; color:#555; }
    .modul-kmalu p  { margin:0; font-size:11px; color:#888; }
    .data-layer    { background:#f5f5f5; border:1.5px dashed #bbb; border-radius:10px;
                     padding:10px 20px; text-align:center; font-size:12px; color:#555; margin-top:8px; }
    div[data-testid="column"] { padding: 0 6px !important; }
    </style>
    """, unsafe_allow_html=True)

    # Master robot
    st.markdown("""
    <div class="master-box">
        <h2>🤖 Master AI Robot</h2>
        <p>Koordinacija vseh procesov</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='text-align:center;color:#ccc;font-size:20px;margin:4px 0'>│</div>", unsafe_allow_html=True)

    # 4 stolpci modulov
    c1, c2, c3, c4 = st.columns(4)

    # ── Modul 1: Prejem ──────────────────────────────────────────────────────
    with c1:
        st.markdown("""
        <div class="modul-kmalu">
            <div style="font-size:28px">📥</div>
            <h4>Prejem blaga</h4>
            <p>Dobavnice → zaloga + knjiženje PR</p>
            <br><span style="background:#ddd;color:#888;border-radius:20px;padding:2px 10px;font-size:10px">kmalu</span>
        </div>
        <div class="trigger-man">📷 Trigger: skeniranje dobavnice</div>
        """, unsafe_allow_html=True)

    # ── Modul 2: Veleprodaja ─────────────────────────────────────────────────
    with c2:
        st.markdown("""
        <div class="modul-kmalu">
            <div style="font-size:28px">📋</div>
            <h4>Veleprodaja</h4>
            <p>Naročila strank → IR + dobavnice</p>
            <br><span style="background:#ddd;color:#888;border-radius:20px;padding:2px 10px;font-size:10px">kmalu</span>
        </div>
        <div class="trigger-man">📷 Trigger: skeniranje naročila</div>
        """, unsafe_allow_html=True)

    # ── Modul 3: Prenos MP ───────────────────────────────────────────────────
    with c3:
        st.markdown("""
        <div class="modul-kmalu">
            <div style="font-size:28px">🚛</div>
            <h4>Prenos MP</h4>
            <p>Prenos med skladišči glede na zahteve</p>
            <br><span style="background:#ddd;color:#888;border-radius:20px;padding:2px 10px;font-size:10px">kmalu</span>
        </div>
        <div class="trigger-man">📝 Trigger: zahteve prodajalcev</div>
        """, unsafe_allow_html=True)

    # ── Modul 4: Loti + Temeljnice ───────────────────────────────────────────
    with c4:
        st.markdown("<p style='text-align:center;font-size:11px;font-weight:600;color:#185FA5;margin-bottom:6px'>Shopsy → Minimax</p>", unsafe_allow_html=True)
        sub1, sub2 = st.columns(2)
        with sub1:
            if st.button("📦\n\n**Loti**\n\nDodelitev serij IS", use_container_width=True, key="btn_loti"):
                st.session_state["aktiven_modul"] = "loti"
                st.rerun()
        with sub2:
            if st.button("💰\n\n**Temeljnice**\n\nPopravek + potrditev", use_container_width=True, key="btn_temeljnice"):
                st.session_state["aktiven_modul"] = "temeljnice"
                st.rerun()
        st.markdown('<div class="trigger-auto">🔄 Trigger: klik prenos iz Shopsy</div>', unsafe_allow_html=True)

    # Skupni podatkovni sloj
    st.markdown("""
    <div class="data-layer">
        <strong>Minimax</strong> &nbsp;·&nbsp; <strong>Google Drive</strong> &nbsp;·&nbsp; <strong>Shopsy</strong>
        &nbsp;&nbsp;—&nbsp;&nbsp; skupni podatkovni sloj
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# MODUL PRIKAZ
# ══════════════════════════════════════════════════════════════════════════════

else:
    modul = st.session_state["aktiven_modul"]

    NAZIVI = {
        "loti":       "📦 Loti — dodelitev serij",
        "temeljnice": "💰 Temeljnice — dnevni izkupiček",
    }

    col_back, col_title = st.columns([1, 8])
    with col_back:
        if st.button("← Hub"):
            st.session_state["aktiven_modul"] = None
            st.rerun()
    with col_title:
        st.title(NAZIVI.get(modul, modul))

    st.divider()

    if modul == "loti":
        from tab_loti import render
        render()
    elif modul == "temeljnice":
        from tab_temeljnice import render
        render()

st.divider()
st.caption("Agent Hub v2.2 · Minimax API")
