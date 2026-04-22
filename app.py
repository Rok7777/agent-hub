"""
Agent Hub — Glavna navigacija.
Moduli:
  tab_loti.py        — dodelitev lotov (ureja chat "Zapiranje LOT")
  tab_temeljnice.py  — dnevni izkupiček (ureja chat "Ločeni procesi")
  minimax_client.py  — API klient (ureja chat "Ločeni procesi")
"""

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Agent Hub",
    page_icon="🐟",
    layout="wide",
)

# ── Navigacija ────────────────────────────────────────────────────────────────

if "aktiven_modul" not in st.session_state:
    st.session_state["aktiven_modul"] = None

# ── Hub prikaz ────────────────────────────────────────────────────────────────

if st.session_state["aktiven_modul"] is None:

    st.title("🐟 Agent Hub")
    st.caption("Kliknite na modul za začetek")

    # Vizualni hub kot interaktivna shema
    hub_html = """
    <style>
      .hub { font-family: sans-serif; padding: 10px 0; }
      .master {
        background: #534AB7; color: #fff;
        border-radius: 12px; padding: 14px 24px;
        text-align: center; width: 260px; margin: 0 auto 0 auto;
        font-weight: 600; font-size: 15px;
      }
      .master small { display:block; font-weight:400; font-size:12px; opacity:0.85; margin-top:4px; }
      .connector-v {
        width: 2px; height: 30px; background: #ccc;
        margin: 0 auto;
      }
      .connector-h {
        display: flex; justify-content: space-between;
        position: relative; margin: 0 20px;
      }
      .connector-h::before {
        content: ''; position: absolute;
        top: 0; left: 60px; right: 60px;
        height: 2px; background: #ccc;
      }
      .col-line {
        width: 2px; height: 24px; background: #ccc; margin: 0 auto;
      }
      .moduli {
        display: flex; gap: 16px; justify-content: center;
        flex-wrap: nowrap; margin-top: 0;
      }
      .modul-wrap { display: flex; flex-direction: column; align-items: center; width: 130px; }
      .modul {
        border-radius: 10px; padding: 12px 8px;
        text-align: center; width: 130px; cursor: pointer;
        border: 2px solid transparent;
        transition: transform 0.15s, box-shadow 0.15s;
      }
      .modul:hover { transform: translateY(-3px); box-shadow: 0 4px 16px rgba(0,0,0,0.15); }
      .modul.aktiven { background: #E6F1FB; border-color: #378ADD; }
      .modul.kmalu   { background: #f5f5f5; border-color: #ddd; opacity: 0.6; cursor: default; }
      .modul .icon   { font-size: 24px; margin-bottom: 6px; }
      .modul .naziv  { font-size: 12px; font-weight: 600; color: #222; }
      .modul .opis   { font-size: 11px; color: #666; margin-top: 4px; }
      .modul .badge  {
        display: inline-block; margin-top: 8px;
        padding: 2px 8px; border-radius: 20px; font-size: 10px; font-weight: 600;
      }
      .badge-aktiven { background: #1D9E75; color: #fff; }
      .badge-kmalu   { background: #ddd; color: #888; }
      .trigger {
        font-size: 10px; color: #888; text-align: center;
        margin-top: 6px; padding: 3px 6px;
        border-radius: 4px; background: #fff8e1; border: 1px solid #ffe082;
        width: 130px;
      }
      .trigger.auto { background: #e8f5e9; border-color: #a5d6a7; color: #2e7d32; }
      .submoduli {
        display: flex; gap: 8px; margin-top: 8px; justify-content: center;
      }
      .submodul {
        border-radius: 8px; padding: 8px 6px;
        text-align: center; width: 100px; cursor: pointer;
        border: 1.5px solid #378ADD; background: #E6F1FB;
        transition: transform 0.15s;
      }
      .submodul:hover { transform: translateY(-2px); box-shadow: 0 3px 10px rgba(0,0,0,0.12); }
      .submodul .icon { font-size: 18px; margin-bottom: 4px; }
      .submodul .naziv { font-size: 11px; font-weight: 600; color: #185FA5; }
      .submodul .opis  { font-size: 10px; color: #378ADD; margin-top: 2px; }
      .data-layer {
        margin: 24px 20px 0;
        background: #f5f5f5; border: 1.5px dashed #bbb;
        border-radius: 10px; padding: 10px 20px;
        text-align: center; font-size: 12px; color: #555;
      }
      .data-layer strong { color: #333; }
    </style>

    <div class="hub">

      <!-- MASTER -->
      <div class="master">
        🤖 Master AI Robot
        <small>Koordinacija vseh procesov</small>
      </div>

      <!-- VERTIKALNA LINIJA -->
      <div class="connector-v"></div>

      <!-- HORIZONTALNA LINIJA -->
      <div class="connector-h">
        <div class="col-line"></div>
        <div class="col-line"></div>
        <div class="col-line"></div>
        <div class="col-line"></div>
      </div>

      <!-- MODULI -->
      <div class="moduli">

        <!-- 1: Prejem -->
        <div class="modul-wrap">
          <div class="modul kmalu">
            <div class="icon">📥</div>
            <div class="naziv">Prejem blaga</div>
            <div class="opis">Dobavnice → zaloga + PR</div>
            <span class="badge badge-kmalu">kmalu</span>
          </div>
          <div class="trigger">📷 Trigger: skeniranje dobavnice</div>
        </div>

        <!-- 2: Veleprodaja -->
        <div class="modul-wrap">
          <div class="modul kmalu">
            <div class="icon">📋</div>
            <div class="naziv">Veleprodaja</div>
            <div class="opis">Naročila → IR + dobavnice</div>
            <span class="badge badge-kmalu">kmalu</span>
          </div>
          <div class="trigger">📷 Trigger: skeniranje naročila</div>
        </div>

        <!-- 3: Prenos MP -->
        <div class="modul-wrap">
          <div class="modul kmalu">
            <div class="icon">🚛</div>
            <div class="naziv">Prenos MP</div>
            <div class="opis">Prenos med skladišči MP</div>
            <span class="badge badge-kmalu">kmalu</span>
          </div>
          <div class="trigger">📝 Trigger: zahteve prodajalcev</div>
        </div>

        <!-- 4: Loti + Temeljnice — RAZDELJENO NA 2 -->
        <div class="modul-wrap" style="width:216px;">
          <div style="font-size:11px; font-weight:600; color:#185FA5; margin-bottom:6px; text-align:center;">
            Shopsy prenos → Minimax
          </div>
          <div class="submoduli">
            <div class="submodul" onclick="window.parent.postMessage({type:'streamlit:setComponentValue', value:'loti'}, '*')">
              <div class="icon">📦</div>
              <div class="naziv">Loti</div>
              <div class="opis">Dodelitev serij IS</div>
            </div>
            <div class="submodul" onclick="window.parent.postMessage({type:'streamlit:setComponentValue', value:'temeljnice'}, '*')">
              <div class="icon">💰</div>
              <div class="naziv">Temeljnice</div>
              <div class="opis">Popravek + potrditev</div>
            </div>
          </div>
          <div class="trigger auto" style="width:216px;">🔄 Trigger: klik prenos iz Shopsy</div>
        </div>

      </div>

      <!-- SKUPNI PODATKOVNI SLOJ -->
      <div class="data-layer">
        <strong>Minimax</strong> &nbsp;·&nbsp; <strong>Google Drive</strong> &nbsp;·&nbsp; <strong>Shopsy</strong>
        &nbsp;&nbsp;—&nbsp;&nbsp; skupni podatkovni sloj
      </div>

    </div>
    """

    # Prikaz HTML sheme
    clicked = components.html(hub_html, height=420, scrolling=False)

    # Gumbi pod shemo za navigacijo
    st.divider()
    st.caption("Aktivni moduli:")
    col1, col2, col3 = st.columns([1, 1, 3])
    with col1:
        if st.button("📦 Odpri Loti", use_container_width=True, type="primary"):
            st.session_state["aktiven_modul"] = "loti"
            st.rerun()
    with col2:
        if st.button("💰 Odpri Temeljnice", use_container_width=True, type="primary"):
            st.session_state["aktiven_modul"] = "temeljnice"
            st.rerun()

# ── Modul prikaz ──────────────────────────────────────────════════════════════

else:
    modul = st.session_state["aktiven_modul"]

    NAZIVI = {
        "loti":       "📦 Loti — dodelitev serij",
        "temeljnice": "💰 Temeljnice — dnevni izkupiček",
    }

    col_back, col_title = st.columns([1, 8])
    with col_back:
        if st.button("← Nazaj na hub"):
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
