"""
AGENT: Blagajna + Temeljnice (Minimax)
=======================================
Nacini:
  python agent_blagajna.py --scan
  python agent_blagajna.py --process 123,456
  python agent_blagajna.py --process all

Logika placil:
  - Mozna sta konta 1652 (kartica) in 1000 (gotovina)
  - Ce sta oba: uredi 1652 -> 120000 z vsoto, izbrise 1000
  - Ce je samo eden: uredi tega -> 120000, nic ne brise
"""

import asyncio
import re
import json
import sys
import logging
from playwright.async_api import async_playwright

BASE_URL = "https://moj.minimax.si"

BLAGAJNE = {
    "MPK1": 17589,
    "MPK2": 17590,
    "MPK3": 17591,
    "MPOC": 18186,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("blagajna-agent")


# ─────────────────────────────────────────
# POMOZNE FUNKCIJE
# ─────────────────────────────────────────

async def connect(playwright):
    browser = await playwright.chromium.connect_over_cdp("http://localhost:9222")
    context = browser.contexts[0]
    return context.pages[0]


def parse_znesek(text: str) -> float:
    clean = (text.strip()
             .replace("\xa0", "")
             .replace(" ", "")
             .replace(".", "")
             .replace(",", "."))
    try:
        return float(clean)
    except ValueError:
        return 0.0


def format_znesek(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


async def klikni(page, selector, timeout=8000):
    el = await page.wait_for_selector(selector, timeout=timeout)
    await el.click()
    return el


async def dropdown(page, sel: str, vrednost: str, timeout=8000):
    field = await page.wait_for_selector(sel, timeout=timeout)
    await field.click()
    await page.wait_for_timeout(200)
    await field.fill(vrednost)
    await page.wait_for_timeout(600)
    opt = await page.wait_for_selector(
        f'ul.ui-autocomplete li:has-text("{vrednost}"), '
        f'.dropdown-menu li:has-text("{vrednost}"), '
        f'[class*="autocomplete"] li:has-text("{vrednost}")',
        timeout=5000,
    )
    await opt.click()
    await page.wait_for_timeout(300)


# ─────────────────────────────────────────
# PREBERI KNJIZBE
# ─────────────────────────────────────────

async def preberi_knjizbe(page, tm_id: str) -> dict | None:
    """
    Prebere knjizbe osnutka. Vrne slovar z podatki.
    Podpira:
      - oba konta (1652 + 1000)
      - samo 1652
      - samo 1000
    Ce ni nobenega -> vrne None.
    """
    await page.goto(
        f"{BASE_URL}/SI/VA/WebUI/Temeljnica/TemeljnicaEdit.aspx"
        f"?tm_id={tm_id}&pgat=pgate"
    )
    await page.wait_for_load_state("networkidle")

    # Preberi datum
    df = await page.query_selector('input[id*="Datum"], input[name*="Datum"]')
    datum = await df.input_value() if df else ""

    # Odpri Knjizbe tab ce obstaja
    kb = await page.query_selector('a:has-text("Knjizbe"), button:has-text("Knjizbe")')
    if kb:
        await kb.click()
        await page.wait_for_timeout(500)

    d1652 = None
    d1000 = None

    for vrstica in await page.query_selector_all("table tr, .grid tr"):
        celice = await vrstica.query_selector_all("td")
        if len(celice) < 4:
            continue
        for idx, celica in enumerate(celice):
            ct = (await celica.inner_text()).strip()
            if ct == "1652" and not d1652:
                an = (await celice[idx + 2].inner_text()).strip() if len(celice) > idx + 2 else ""
                zn = parse_znesek((await celice[-2].inner_text()).strip())
                d1652 = {"analitika": an, "znesek": zn}
            elif ct == "1000" and not d1000:
                an = (await celice[idx + 2].inner_text()).strip() if len(celice) > idx + 2 else ""
                zn = parse_znesek((await celice[-2].inner_text()).strip())
                d1000 = {"analitika": an, "znesek": zn}

    if not d1652 and not d1000:
        log.warning(f"tm_id={tm_id}: ni najden noben placilni konto (1652/1000) — preskacem")
        return None

    # Analitika — vzamemo od tistega ki obstaja
    an_polno = (d1652 or d1000)["analitika"]
    m = re.match(r"^(MPK\d+|MPOC)", an_polno)
    sifra = m.group(1) if m else an_polno.split(" ")[0]

    znesek_kartica = d1652["znesek"] if d1652 else 0.0
    znesek_gotovina = d1000["znesek"] if d1000 else 0.0
    skupaj = round(znesek_kartica + znesek_gotovina, 2)

    # Rezim: koliko kontov imamo
    if d1652 and d1000:
        rezim = "oba"
    elif d1652:
        rezim = "samo_kartica"
    else:
        rezim = "samo_gotovina"

    log.info(
        f"  tm_id={tm_id} | {datum} | {sifra} | "
        f"kartica={znesek_kartica} | gotovina={znesek_gotovina} | "
        f"skupaj={skupaj} | rezim={rezim}"
    )

    return {
        "tm_id": tm_id,
        "datum": datum,
        "analitika_sifra": sifra,
        "analitika_polno": an_polno,
        "znesek_kartica": znesek_kartica,
        "znesek_gotovina": znesek_gotovina,
        "skupaj": skupaj,
        "rezim": rezim,  # "oba" | "samo_kartica" | "samo_gotovina"
    }


# ─────────────────────────────────────────
# SCAN
# ─────────────────────────────────────────

async def scan_osnutke(page) -> list[dict]:
    log.info("SCAN: Iscem osnutke ...")
    await page.goto(f"{BASE_URL}/SI/VA/WebUI/Temeljnica/Temeljnica.aspx")
    await page.wait_for_load_state("networkidle")
    await klikni(page, 'button:has-text("Najdi"), input[value="Najdi"]')
    await page.wait_for_load_state("networkidle")

    ids = []
    for v in await page.query_selector_all("tr"):
        if "Osnutek" not in await v.inner_text():
            continue
        link = await v.query_selector('a[href*="TemeljnicaEdit"]')
        if not link:
            continue
        href = await link.get_attribute("href")
        m = re.search(r"tm_id=(\d+)", href)
        if m:
            ids.append(m.group(1))

    log.info(f"Najdenih {len(ids)} osnutkov, berem knjizbe ...")
    rezultati = []
    for tm_id in ids:
        p = await preberi_knjizbe(page, tm_id)
        if p:
            rezultati.append(p)
    return rezultati


# ─────────────────────────────────────────
# BLAGAJNA: KREIRAJ DATUM
# ─────────────────────────────────────────

async def kreiraj_datum_blagajne(page, bg_id: int, datum: str) -> str | None:
    log.info(f"  Datum bg_id={bg_id} za {datum} ...")
    await page.goto(
        f"{BASE_URL}/SI/VA/WebUI/BlagajniDnevnik/BlagajniDnevnikEdit.aspx?bg_id={bg_id}"
    )
    await page.wait_for_load_state("networkidle")

    df = await page.wait_for_selector('input[id*="Datum"], input[name*="Datum"]', timeout=5000)
    await df.triple_click()
    await df.type(datum)
    await page.wait_for_timeout(300)

    await klikni(page, 'button:has-text("Shrani"), input[value="Shrani"]')
    await page.wait_for_load_state("networkidle")

    m = re.search(r"bdn_id=(\d+)", page.url)
    if m:
        log.info(f"  bdn_id={m.group(1)} OK")
        return m.group(1)
    log.error("  bdn_id ni v URL-ju!")
    return None


# ─────────────────────────────────────────
# BLAGAJNA: KREIRAJ PREJEMEK
# ─────────────────────────────────────────

async def kreiraj_prejemek(page, bdn_id: str, an_polno: str, skupaj: float):
    log.info(f"  Prejemek {skupaj} EUR ...")
    await page.goto(
        f"{BASE_URL}/SI/VA/WebUI/BlagajniDnevnik/BlagajniDnevnikView.aspx"
        f"?bdn_id={bdn_id}&pgat=pgatv"
    )
    await page.wait_for_load_state("networkidle")
    await klikni(page, 'a:has-text("Nov prejemek"), button:has-text("Nov prejemek")')
    await page.wait_for_load_state("networkidle")

    await dropdown(page, 'input[id*="Stranka"], [id*="Stranka"] input', "Koncni kupec - maloprodaja")

    an_in = await page.query_selector('[id*="Analitika"] input')
    if an_in and not (await an_in.input_value()).strip():
        await dropdown(page, '[id*="Analitika"] input', an_polno.split(" ")[0])

    await dropdown(page, '[id*="Prejemek"] input, [id*="TipPrejemka"] input', "Dnevni iztrZek")

    zf = await page.wait_for_selector('input[id*="Znesek"], input[name*="Znesek"]', timeout=5000)
    await zf.triple_click()
    await zf.type(format_znesek(skupaj))

    await klikni(page, 'button:has-text("Shrani")')
    await page.wait_for_load_state("networkidle")
    log.info("  Prejemek OK")


# ─────────────────────────────────────────
# BLAGAJNA: KREIRAJ IZDATEK
# ─────────────────────────────────────────

async def kreiraj_izdatek(
    page, bdn_id: str, an_polno: str,
    znesek_gotovina: float, znesek_kartica: float,
    rezim: str
):
    """
    Kreira izdatek.
    - rezim="oba":           2 vrstici (gotovina + kartica)
    - rezim="samo_kartica":  1 vrstica (samo kartica)
    - rezim="samo_gotovina": 1 vrstica (samo gotovina)
    """
    log.info(f"  Izdatek rezim={rezim} ...")
    await page.goto(
        f"{BASE_URL}/SI/VA/WebUI/BlagajniDnevnik/BlagajniDnevnikView.aspx"
        f"?bdn_id={bdn_id}&pgat=pgatv"
    )
    await page.wait_for_load_state("networkidle")
    await klikni(page, 'a:has-text("Nov izdatek"), button:has-text("Nov izdatek")')
    await page.wait_for_load_state("networkidle")

    an_in = await page.query_selector('[id*="Analitika"] input')
    if an_in and not (await an_in.input_value()).strip():
        await dropdown(page, '[id*="Analitika"] input', an_polno.split(" ")[0])

    async def dodaj_vrstico(tip: str, znesek: float):
        await dropdown(page, '[id*="Izdatek"] input, [id*="TipIzdatka"] input', tip)
        zf = await page.wait_for_selector('input[id*="Znesek"], input[name*="Znesek"]', timeout=5000)
        await zf.triple_click()
        await zf.type(format_znesek(znesek))
        await klikni(page, 'button:has-text("Shrani")')
        await page.wait_for_timeout(600)

    if rezim in ("oba", "samo_gotovina"):
        await dodaj_vrstico("Polog gotovine - domaca DE", znesek_gotovina)

    if rezim in ("oba", "samo_kartica"):
        await dodaj_vrstico("Terjatev za placila z kartico", znesek_kartica)

    sb = await page.query_selector('button:has-text("Shrani"), input[value="Shrani"]')
    if sb:
        await sb.click()
        await page.wait_for_load_state("networkidle")
    log.info("  Izdatek OK")


# ─────────────────────────────────────────
# TEMELJNICA: POPRAVI KNJIZBE
# ─────────────────────────────────────────

async def popravi_temeljnico(page, podatki: dict):
    """
    Popravi temeljnico glede na rezim:
    - "oba":           uredi 1652 -> 120000 z vsoto, izbrisi 1000
    - "samo_kartica":  uredi 1652 -> 120000 (znesek ostane)
    - "samo_gotovina": uredi 1000 -> 120000 (znesek ostane)
    """
    rezim = podatki["rezim"]
    log.info(f"  Temeljnica tm_id={podatki['tm_id']} rezim={rezim} ...")

    await page.goto(
        f"{BASE_URL}/SI/VA/WebUI/Temeljnica/TemeljnicaEdit.aspx"
        f"?tm_id={podatki['tm_id']}&pgat=pgate"
    )
    await page.wait_for_load_state("networkidle")

    kb = await page.query_selector('a:has-text("Knjizbe"), button:has-text("Knjizbe")')
    if kb:
        await kb.click()
        await page.wait_for_timeout(600)

    edit_1652 = None
    edit_1000 = None
    del_1000  = None

    for v in await page.query_selector_all("table tr"):
        for c in await v.query_selector_all("td"):
            ct = (await c.inner_text()).strip()
            if ct == "1652" and not edit_1652:
                edit_1652 = await v.query_selector(
                    'a[href*="Edit"], button[title*="Uredi"], .edit-btn'
                )
            elif ct == "1000" and not edit_1000:
                edit_1000 = await v.query_selector(
                    'a[href*="Edit"], button[title*="Uredi"], .edit-btn'
                )
                del_1000 = await v.query_selector(
                    'a[href*="Delete"], button[title*="Brisi"], .delete-btn'
                )

    async def uredi_na_120000(gumb_edit, nov_znesek: float):
        """Uredi vrstico: zamenja konto na 120000, doda stranko, popravi znesek."""
        await gumb_edit.click()
        await page.wait_for_timeout(500)

        ki = await page.wait_for_selector('[id*="Konto"] input, input[id*="konto"]', timeout=5000)
        await ki.triple_click()
        await ki.type("120000")
        await page.wait_for_timeout(600)
        opt = await page.wait_for_selector('li:has-text("120000")', timeout=5000)
        await opt.click()
        await page.wait_for_timeout(300)

        await dropdown(page, '[id*="Stranka"] input', "Koncni kupec - maloprodaja")

        bi = await page.query_selector('input[id*="Breme"], input[name*="Breme"]')
        if bi:
            await bi.triple_click()
            await bi.type(format_znesek(nov_znesek))

        await klikni(page, 'button:has-text("Shrani knjizbo")')
        await page.wait_for_timeout(500)

    if rezim == "oba":
        # Uredi 1652 z vsoto, izbrisi 1000
        if edit_1652:
            await uredi_na_120000(edit_1652, podatki["skupaj"])
        else:
            log.warning("  Edit gumb 1652 ni najden!")

        if del_1000:
            await del_1000.click()
            await page.wait_for_timeout(400)
            try:
                await page.click('button:has-text("Da"), button:has-text("OK")', timeout=2000)
            except Exception:
                pass
        else:
            log.warning("  Delete gumb 1000 ni najden!")

    elif rezim == "samo_kartica":
        # Samo uredi 1652, nic ne brisemo
        if edit_1652:
            await uredi_na_120000(edit_1652, podatki["znesek_kartica"])
        else:
            log.warning("  Edit gumb 1652 ni najden!")

    elif rezim == "samo_gotovina":
        # Samo uredi 1000, nic ne brisemo
        if edit_1000:
            await uredi_na_120000(edit_1000, podatki["znesek_gotovina"])
        else:
            log.warning("  Edit gumb 1000 ni najden!")

    # Shrani temeljnico
    await klikni(page, 'button:has-text("Shrani"), input[value="Shrani"]')
    await page.wait_for_load_state("networkidle")
    log.info("  Temeljnica OK")


# ─────────────────────────────────────────
# OBDELAJ IZBRANE
# ─────────────────────────────────────────

async def obdelaj_izbrane(page, tm_ids: list[str]):
    obdelani = 0
    napake = 0

    for tm_id in tm_ids:
        log.info(f"\n{'─'*40}")
        log.info(f"Obdelujem tm_id={tm_id}")
        try:
            podatki = await preberi_knjizbe(page, tm_id)
            if not podatki:
                napake += 1
                continue

            sifra = podatki["analitika_sifra"]
            if sifra not in BLAGAJNE:
                log.warning(f"  Analitika '{sifra}' ni v BLAGAJNE — preskacem")
                continue

            bdn_id = await kreiraj_datum_blagajne(page, BLAGAJNE[sifra], podatki["datum"])
            if not bdn_id:
                napake += 1
                continue

            await kreiraj_prejemek(
                page, bdn_id, podatki["analitika_polno"], podatki["skupaj"]
            )
            await kreiraj_izdatek(
                page, bdn_id, podatki["analitika_polno"],
                podatki["znesek_gotovina"], podatki["znesek_kartica"],
                podatki["rezim"]
            )
            await popravi_temeljnico(page, podatki)

            obdelani += 1
            log.info(
                f"  OK {podatki['datum']} | {sifra} | "
                f"{podatki['skupaj']} EUR | rezim={podatki['rezim']}"
            )

        except Exception as exc:
            log.exception(f"  NAPAKA tm_id={tm_id}: {exc}")
            napake += 1

    log.info(f"\n{'='*50}")
    log.info(f"KONCANO: {obdelani} uspesno, {napake} napak")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

async def main():
    args = sys.argv[1:]
    async with async_playwright() as p:
        page = await connect(p)

        if "--scan" in args:
            rezultati = await scan_osnutke(page)
            print("SCAN_JSON_START")
            print(json.dumps(rezultati, ensure_ascii=False))
            print("SCAN_JSON_END")

        elif "--process" in args:
            idx = args.index("--process")
            tm_ids_arg = args[idx + 1] if idx + 1 < len(args) else ""

            if tm_ids_arg == "all":
                rez = await scan_osnutke(page)
                tm_ids = [r["tm_id"] for r in rez]
            else:
                tm_ids = [t.strip() for t in tm_ids_arg.split(",") if t.strip()]

            if tm_ids:
                await obdelaj_izbrane(page, tm_ids)
            else:
                log.info("Ni tm_id-jev za obdelavo.")

        else:
            print("Uporaba:")
            print("  python agent_blagajna.py --scan")
            print("  python agent_blagajna.py --process 123,456")
            print("  python agent_blagajna.py --process all")


if __name__ == "__main__":
    asyncio.run(main())
