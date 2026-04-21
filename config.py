"""
Skupne nastavitve in helper funkcije za vse tabove.
"""

import streamlit as st
from minimax_client import MinimaxClient


def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return default


def get_client() -> MinimaxClient:
    return MinimaxClient(
        username      = st.session_state.get("username",      _secret("MINIMAX_USERNAME", "")),
        password      = st.session_state.get("password",      _secret("MINIMAX_PASSWORD", "")),
        client_id     = st.session_state.get("client_id",     _secret("MINIMAX_CLIENT_ID", "")),
        client_secret = st.session_state.get("client_secret", _secret("MINIMAX_CLIENT_SECRET", "")),
        org_id        = int(st.session_state.get("org_id",    _secret("MINIMAX_ORG_ID", "171038"))),
    )


def check_config() -> bool:
    required = ["username", "password", "client_id", "client_secret", "org_id"]
    missing  = [k for k in required if not st.session_state.get(k) and not _secret(f"MINIMAX_{k.upper()}", "")]
    if missing:
        st.warning("⚠️ Izpolnite vse nastavitve API v stranski vrstici.")
        return False
    return True


@st.cache_data(ttl=3600, show_spinner=False)
def resolve_ids(_username, _password, _client_id, _client_secret, _org_id):
    cli = MinimaxClient(username=_username, password=_password,
                        client_id=_client_id, client_secret=_client_secret, org_id=int(_org_id))
    wh_map, an_map = {}, {}
    try:
        for row in cli.get_warehouses():
            code = (row.get("Code") or "").strip().upper()
            wid  = row.get("WarehouseId") or row.get("ID")
            if code and wid: wh_map[code] = int(wid)
    except Exception: pass
    try:
        for row in cli.get_analytics():
            code = (row.get("Code") or "").strip().upper()
            aid  = row.get("AnalyticId")
            if code and aid: an_map[code] = int(aid)
    except Exception: pass
    return wh_map, an_map


def get_wh_id(loc_key: str) -> int:
    wh_codes = {
        "MPK1": st.session_state.get("wh_mpk1", _secret("WH_MPK1", "MP-K1")),
        "MPK2": st.session_state.get("wh_mpk2", _secret("WH_MPK2", "MP-K2")),
        "MPK3": st.session_state.get("wh_mpk3", _secret("WH_MPK3", "MP-K3")),
        "MPOC": st.session_state.get("wh_mpoc", _secret("WH_MPOC", "MP-RD")),
    }
    code = wh_codes.get(loc_key, "").strip().upper()
    if not code: return 0
    u = st.session_state.get("username", "")
    p = st.session_state.get("password", "")
    ci = st.session_state.get("client_id", "")
    cs = st.session_state.get("client_secret", "")
    oi = st.session_state.get("org_id", "")
    if all([u, p, ci, cs, oi]):
        wh_map, _ = resolve_ids(u, p, ci, cs, oi)
        return wh_map.get(code, 0)
    return 0


def get_an_id(loc_key: str) -> int:
    an_codes = {
        "MPK1": st.session_state.get("an_mpk1", _secret("AN_MPK1", "MPK1")),
        "MPK2": st.session_state.get("an_mpk2", _secret("AN_MPK2", "MPK2")),
        "MPK3": st.session_state.get("an_mpk3", _secret("AN_MPK3", "MPK3")),
        "MPOC": st.session_state.get("an_mpoc", _secret("AN_MPOC", "MPOC")),
    }
    code = an_codes.get(loc_key, "").strip().upper()
    if not code: return 0
    u = st.session_state.get("username", "")
    p = st.session_state.get("password", "")
    ci = st.session_state.get("client_id", "")
    cs = st.session_state.get("client_secret", "")
    oi = st.session_state.get("org_id", "")
    if all([u, p, ci, cs, oi]):
        _, an_map = resolve_ids(u, p, ci, cs, oi)
        return an_map.get(code, 0)
    return 0
