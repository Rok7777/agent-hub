"""
AGENT: Blagajna + Temeljnice (Minimax)
=======================================
Za vsak osnutek v temeljnicah:
  1. Prebere knjižbe (konto 1652 = kartica, konto 1000 = gotovina)
  2. Kreira blagajniški dnevnik za ustrezen datum in blagajno
  3. Doda blagajniški PREJEMEK (dnevni iztržek = skupaj)
  4. Doda blagajniški IZDATEK (2 vrstici: gotovina + kartica)
  5. Popravi temeljnico: 1652 → 120000 z vsoto, izbriše 1000
"""

import asyncio
import re
import logging
from datetime import datetime
from playwright.async_api import async_playwright

# ─────────────────────────────────────────
# KONFIGURACIJA
# ─────────────────────────────────────────
BASE_URL = "https://moj.minimax.si"

# Šifra analitike → bg_id blagajne
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
# POMOŽNE FUNKCIJE
# ─────────────────────────────────────────

async def connect(playwright):
    """Poveže se na obstoječi Chrome (CDP)"""
    browser = await playwright.chromium.connect_over_cdp("http://localhost:9222")
    context = browser.contexts[0]
    page = context.pages[0]
    return page


def parse_znesek(text: str) -> float:
    """Pretvori '1.234,56' v float 1234.56"""
    clean = text.strip().replace("\xa0", "").replace(" ", "")
    clean = clean.replace(".", "").replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return 0.0


def format_znesek(value: float) -> str:
    """Pretvori float v '1234,56' za vnos v Minimax"""
    return f"{value:.2f}".replace(".", ",")


async def pocakaj_in_klikni(page, selector, timeout=8000):
    el = await page.wait_for_selector(selector, timeout=timeout)
    await el.click()
    return el


async def izberi_dropdown(page, container_selector: str, vrednost: str, timeout=8000):
    """
    Minimax dropdown: klikne vnosno polje, vtipka vrednost,
    počaka na seznam in klikne prvo ujemanje.
    """
    field = await page.wait_for_selector(container_selector, timeout=timeout)
    await field.click()
    await page.wait_for_timeout(200)
    await field.fill(vrednost)
    await page.wait_for_timeout(600)

    # Čakaj na li element v dropdownu
    option = await page.wait_for_selector(
        f'ul.ui-autocomplete li:has-text("{vrednost}"), '
        f'.dropdown-menu li:has-text("{vrednost}"), '
        f'[class*="autocomplete"] li:has-text("{vrednost}")',
        timeout=5000,
    )
    await option.click()
    await page.wait_for_timeout(300)


# ─────────────────────────────────────────
# KORAK 1: POBERI OSNUTKE IZ TEMELJNIC
# ─────────────────────────────────────────

async def dobij_osnutke(page) -> list[str]:
    """Vrne seznam tm_id za vse osnutke v temeljnicah"""
    log.info("Iščem osnutke v temeljnicah …")
    await page.goto(f"{BASE_URL}/SI/VA/WebUI/Temeljnica/Temeljnica.aspx")
    await page.wait_for_load_state("networkidle")

    # Klikni Najdi
    await pocakaj_in_klikni(page, 'button:has-text("Najdi"), input[value="Najdi"]')
    await page.wait_for_load_state("networkidle")

    osnutki = []
    # Poišči vse vrstice kjer je v celici besedilo "Osnutek"
    vrstice = await page.query_selector_all("tr")
    for vrstica in vrstice:
        tekst = await vrstica.inner_text()
        if "Osnutek" not in tekst:
            continue
        # Poišči link do TemeljnicaEdit
        link = await vrstica.query_selector('a[href*="TemeljnicaEdit"]')
        if not link:
            continue
        href = await link.get_attribute("href")
        m = re.search(r"tm_id=(\d+)", href)
        if m:
            tm_id = m.group(1)
            osnutki.append(tm_id)
            log.info(f"  ✓ Osnutek najden: tm_id={tm_id}")

    log.info(f"Skupaj osnutkov: {len(osnutki)}")
    return osnutki


# ─────────────────────────────────────────
# KORAK 2: PREBERI KNJIŽBE OSNUTKA
# ─────────────────────────────────────────

async def preberi_knjizbe(page, tm_id: str) -> dict | None:
    """
    Odpre temeljnico in prebere konto 1652 + 1000.
    Vrne slovar s podatki ali None če ni obeh kontov.
    """
    url = f"{BASE_URL}/SI/VA/WebUI/Temeljnica/TemeljnicaEdit.aspx?tm_id={tm_id}&pgat=pgate"
    await page.goto(url)
    await page.wait_for_load_state("networkidle")

    # Preberi datum iz header vrstice
    datum_field = await page.query_selector(
        'input[id*="Datum"], input[name*="Datum"], input[id*="datum"]'
    )
    datum = await datum_field.input_value() if datum_field else ""

    # Klikni Knjižbe (tab ali gumb) — prikaže tabelo z zneski
    knjizbe_link = await page.query_selector('a:has-text("Knjižbe"), button:has-text("Knjižbe")')
    if knjizbe_link:
        await knjizbe_link.click()
        await page.wait_for_timeout(500)

    # Poišči vrstice s kontoma 1652 in 1000 v tabeli knjižb
    data_1652 = None
    data_1000 = None

    vrstice = await page.query_selector_all("table tr, .grid tr, [class*='knjizbe'] tr")

    for vrstica in vrstice:
        celice = await vrstica.query_selector_all("td")
        if len(celice) < 4:
            continue

        # Preverimo vsako celico za vrednost konta
        for idx, celica in enumerate(celice):
            tekst = (await celica.inner_text()).strip()

            if tekst == "1652":
                # Analitika je 2 celici desno od konta
                analitika = (await celice[idx + 2].inner_text()).strip() if len(celice) > idx + 2 else ""
                # Breme = predzadnja celica
                breme_tekst = (await celice[-2].inner_text()).strip()
                znesek = parse_znesek(breme_tekst)
                data_1652 = {"analitika": analitika, "znesek": znesek, "vrstica": vrstica}
                break

            elif tekst == "1000":
                analitika = (await celice[idx + 2].inner_text()).strip() if len(celice) > idx + 2 else ""
                breme_tekst = (await celice[-2].inner_text()).strip()
                znesek = parse_znesek(breme_tekst)
                data_1000 = {"analitika": analitika, "znesek": znesek, "vrstica": vrstica}
                break

    if not data_1652 or not data_1000:
        log.warning(f"  Osnutek {tm_id}: ni najdenih obeh kontov (1652/1000) — preskačem")
        return None

    skupaj = round(data_1652["znesek"] + data_1000["znesek"], 2)
    analitika_polno = data_1652["analitika"]  # npr. "MPK3 - Potujoča 3 (GO CT-002)"

    # Izvleči šifro blagajne (MPK1/MPK2/MPK3/MPOC)
    sifra_m = re.match(r"^(MPK\d+|MPOC)", analitika_polno)
    sifra = sifra_m.group(1) if sifra_m else analitika_polno.split(" ")[0]

    log.info(
        f"  Datum={datum} | Analitika={sifra} | "
        f"Kartica(1652)={data_1652['znesek']} | "
        f"Gotovina(1000)={data_1000['znesek']} | Skupaj={skupaj}"
    )

    return {
        "tm_id": tm_id,
        "datum": datum,
        "analitika_sifra": sifra,
        "analitika_polno": analitika_polno,
        "znesek_kartica": data_1652["znesek"],
        "znesek_gotovina": data_1000["znesek"],
        "skupaj": skupaj,
    }


# ─────────────────────────────────────────
# KORAK 3A: BLAGAJNA — KREIRAJ DATUM
# ─────────────────────────────────────────

async def kreiraj_datum_blagajne(page, bg_id: int, datum: str) -> str | None:
    """
    Odpre BlagajniDnevnikEdit, nastavi datum, shrani.
    Vrne bdn_id iz URL-ja po shranjevanju.
    """
    log.info(f"  Kreiranje datuma blagajne bg_id={bg_id} za {datum} …")

    url = f"{BASE_URL}/SI/VA/WebUI/BlagajniDnevnik/BlagajniDnevnikEdit.aspx?bg_id={bg_id}"
    await page.goto(url)
    await page.wait_for_load_state("networkidle")

    # Vnesi datum
    datum_field = await page.wait_for_selector(
        'input[id*="Datum"], input[name*="Datum"]', timeout=5000
    )
    await datum_field.triple_click()
    await datum_field.type(datum)
    await page.wait_for_timeout(300)

    # Shrani
    await pocakaj_in_klikni(page, 'button:has-text("Shrani"), input[value="Shrani"]')
    await page.wait_for_load_state("networkidle")

    # Preberi bdn_id iz novega URL-ja
    m = re.search(r"bdn_id=(\d+)", page.url)
    if m:
        bdn_id = m.group(1)
        log.info(f"  Kreiran dnevnik: bdn_id={bdn_id}")
        return bdn_id

    log.error("  NAPAKA: bdn_id ni najden v URL-ju po shranjevanju!")
    return None


# ─────────────────────────────────────────
# KORAK 3B: BLAGAJNA — KREIRAJ PREJEMEK
# ─────────────────────────────────────────

async def kreiraj_prejemek(page, bdn_id: str, analitika_polno: str, skupaj: float):
    """Kreira blagajniški prejemek (Dnevni iztržek)"""
    log.info(f"  Kreiranje prejemka: {skupaj} EUR …")

    # Odpri View stran in klikni Nov prejemek
    view_url = f"{BASE_URL}/SI/VA/WebUI/BlagajniDnevnik/BlagajniDnevnikView.aspx?bdn_id={bdn_id}&pgat=pgatv"
    await page.goto(view_url)
    await page.wait_for_load_state("networkidle")

    await pocakaj_in_klikni(page, 'a:has-text("Nov prejemek"), button:has-text("Nov prejemek")')
    await page.wait_for_load_state("networkidle")

    # Stranka → Končni kupec - maloprodaja
    await izberi_dropdown(
        page,
        'input[id*="Stranka"], [id*="Stranka"] input',
        "Končni kupec - maloprodaja",
    )

    # Analitika — preveri ali je že predizpolnjena
    analitika_input = await page.query_selector('[id*="Analitika"] input, input[id*="analitika"]')
    if analitika_input:
        current = await analitika_input.input_value()
        if not current.strip():
            sifra = analitika_polno.split(" ")[0]
            await izberi_dropdown(page, '[id*="Analitika"] input', sifra)

    # Tip prejemka → Dnevni iztržek
    await izberi_dropdown(
        page,
        'input[id*="Prejemek"], [id*="TipPrejemka"] input, [id*="Prejemek"] input',
        "Dnevni iztržek",
    )

    # Znesek
    znesek_field = await page.wait_for_selector(
        'input[id*="Znesek"], input[name*="Znesek"]', timeout=5000
    )
    await znesek_field.triple_click()
    await znesek_field.type(format_znesek(skupaj))

    # Shrani vrstico (gumb Shrani znotraj obrazca)
    await pocakaj_in_klikni(page, 'button:has-text("Shrani")')
    await page.wait_for_load_state("networkidle")

    # Shrani celoten prejemek
    shrani_btn = await page.query_selector('button:has-text("Shrani"), input[value="Shrani"]')
    if shrani_btn:
        await shrani_btn.click()
        await page.wait_for_load_state("networkidle")

    log.info("  Prejemek shranjen ✓")


# ─────────────────────────────────────────
# KORAK 3C: BLAGAJNA — KREIRAJ IZDATEK
# ─────────────────────────────────────────

async def kreiraj_izdatek(
    page, bdn_id: str, analitika_polno: str, znesek_gotovina: float, znesek_kartica: float
):
    """
    Kreira blagajniški izdatek z dvema vrsticama:
    1. Polog gotovine - domača DE  → znesek_gotovina
    2. Terjatev za plačila z kartico → znesek_kartica
    """
    log.info(f"  Kreiranje izdatka: gotovina={znesek_gotovina}, kartica={znesek_kartica} …")

    # Odpri View stran in klikni Nov izdatek
    view_url = f"{BASE_URL}/SI/VA/WebUI/BlagajniDnevnik/BlagajniDnevnikView.aspx?bdn_id={bdn_id}&pgat=pgatv"
    await page.goto(view_url)
    await page.wait_for_load_state("networkidle")

    await pocakaj_in_klikni(page, 'a:has-text("Nov izdatek"), button:has-text("Nov izdatek")')
    await page.wait_for_load_state("networkidle")

    # Analitika
    analitika_input = await page.query_selector('[id*="Analitika"] input')
    if analitika_input:
        current = await analitika_input.input_value()
        if not current.strip():
            sifra = analitika_polno.split(" ")[0]
            await izberi_dropdown(page, '[id*="Analitika"] input', sifra)

    async def dodaj_vrstico_izdatka(tip: str, znesek: float):
        """Doda eno vrstico izdatka (tip + znesek + shrani)"""
        await izberi_dropdown(
            page,
            'input[id*="Izdatek"], [id*="TipIzdatka"] input, [id*="Izdatek"] input',
            tip,
        )
        znesek_field = await page.wait_for_selector(
            'input[id*="Znesek"], input[name*="Znesek"]', timeout=5000
        )
        await znesek_field.triple_click()
        await znesek_field.type(format_znesek(znesek))

        # Shrani vrstico (manjši gumb v obrazcu)
        await pocakaj_in_klikni(page, 'button:has-text("Shrani")')
        await page.wait_for_timeout(600)

    # Vrstica 1: Gotovina
    await dodaj_vrstico_izdatka("Polog gotovine - domača DE", znesek_gotovina)

    # Vrstica 2: Kartica
    await dodaj_vrstico_izdatka("Terjatev za plačila z kartico", znesek_kartica)

    # Shrani celoten izdatek
    shrani_btn = await page.query_selector('button:has-text("Shrani"), input[value="Shrani"]')
    if shrani_btn:
        await shrani_btn.click()
        await page.wait_for_load_state("networkidle")

    log.info("  Izdatek shranjen ✓")


# ─────────────────────────────────────────
# KORAK 4: POPRAVI TEMELJNICO
# ─────────────────────────────────────────

async def popravi_temeljnico(page, podatki: dict):
    """
    Odpre temeljnico, popravi konto 1652 → 120000 z vsoto,
    izbriše vrstico 1000 in shrani.
    """
    log.info(f"  Popravljam temeljnico tm_id={podatki['tm_id']} …")

    url = f"{BASE_URL}/SI/VA/WebUI/Temeljnica/TemeljnicaEdit.aspx?tm_id={podatki['tm_id']}&pgat=pgate"
    await page.goto(url)
    await page.wait_for_load_state("networkidle")

    # Klikni tab Knjižbe
    knjizbe_link = await page.query_selector('a:has-text("Knjižbe"), button:has-text("Knjižbe")')
    if knjizbe_link:
        await knjizbe_link.click()
        await page.wait_for_timeout(600)

    # ── UREDI VRSTICO 1652 ──
    vrstice = await page.query_selector_all("table tr")
    gumb_edit_1652 = None
    gumb_delete_1000 = None

    for vrstica in vrstice:
        tekst = await vrstica.inner_text()
        celice = await vrstica.query_selector_all("td")

        if "1652" in tekst and gumb_edit_1652 is None:
            # Ikona svinčnika / uredi gumb v vrstici
            gumb_edit_1652 = await vrstica.query_selector(
                'a[href*="Edit"], button[title*="Uredi"], .edit-btn, a.pencil, '
                'input[title*="Uredi"], a[id*="edit"], a[id*="Edit"]'
            )

        # Konto 1000 — pazi da ne ujameš 10001, 10002 …
        for celica in celice:
            ct = (await celica.inner_text()).strip()
            if ct == "1000":
                gumb_delete_1000 = await vrstica.query_selector(
                    'a[href*="Delete"], button[title*="Briši"], .delete-btn, '
                    'a[id*="delete"], a[id*="Delete"], span[title*="Briši"]'
                )
                break

    if gumb_edit_1652:
        await gumb_edit_1652.click()
        await page.wait_for_timeout(500)

        # Zamenjaj konto
        konto_input = await page.wait_for_selector(
            '[id*="Konto"] input, input[id*="konto"]', timeout=5000
        )
        await konto_input.triple_click()
        await konto_input.type("120000")
        await page.wait_for_timeout(600)
        opcija = await page.wait_for_selector(
            'li:has-text("120000"), [class*="autocomplete"] li:has-text("120000")',
            timeout=5000,
        )
        await opcija.click()
        await page.wait_for_timeout(300)

        # Dodaj stranko
        await izberi_dropdown(
            page, '[id*="Stranka"] input', "Končni kupec - maloprodaja"
        )

        # Popravi znesek (Breme) na skupaj
        breme_input = await page.query_selector(
            'input[id*="Breme"], input[id*="breme"], input[name*="Breme"]'
        )
        if breme_input:
            await breme_input.triple_click()
            await breme_input.type(format_znesek(podatki["skupaj"]))

        # Shrani knjižbo
        await pocakaj_in_klikni(page, 'button:has-text("Shrani knjižbo")')
        await page.wait_for_timeout(500)
    else:
        log.warning("  Gumb za urejanje vrstice 1652 ni najden!")

    # ── IZBRIŠI VRSTICO 1000 ──
    if gumb_delete_1000:
        await gumb_delete_1000.click()
        await page.wait_for_timeout(400)
        # Potrdi dialog (če se pojavi)
        try:
            await page.click(
                'button:has-text("Da"), button:has-text("OK"), button:has-text("Potrdi")',
                timeout=2000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(400)
    else:
        log.warning("  Gumb za brisanje vrstice 1000 ni najden!")

    # ── SHRANI TEMELJNICO ──
    await pocakaj_in_klikni(page, 'button:has-text("Shrani"), input[value="Shrani"]')
    await page.wait_for_load_state("networkidle")

    log.info("  Temeljnica shranjena ✓")


# ─────────────────────────────────────────
# GLAVNI AGENT
# ─────────────────────────────────────────

async def main():
    async with async_playwright() as p:
        page = await connect(p)

        log.info("=" * 50)
        log.info("AGENT: BLAGAJNA + TEMELJNICE — ZAČETEK")
        log.info("=" * 50)

        # 1. Poberi osnutke
        osnutki_ids = await dobij_osnutke(page)

        if not osnutki_ids:
            log.info("Ni osnutkov za obdelavo. Konec.")
            return

        obdelani = []
        napake = []

        for tm_id in osnutki_ids:
            log.info(f"\n{'─'*40}")
            log.info(f"Obdelujem osnutek tm_id={tm_id}")

            try:
                # 2. Preberi knjižbe
                podatki = await preberi_knjizbe(page, tm_id)
                if not podatki:
                    napake.append(tm_id)
                    continue

                sifra = podatki["analitika_sifra"]

                if sifra not in BLAGAJNE:
                    log.warning(f"  Analitika '{sifra}' ni v BLAGAJNE — preskačem")
                    continue

                bg_id = BLAGAJNE[sifra]

                # 3a. Kreiraj datum v blagajni
                bdn_id = await kreiraj_datum_blagajne(page, bg_id, podatki["datum"])
                if not bdn_id:
                    napake.append(tm_id)
                    continue

                # 3b. Blagajniški prejemek
                await kreiraj_prejemek(
                    page, bdn_id, podatki["analitika_polno"], podatki["skupaj"]
                )

                # 3c. Blagajniški izdatek
                await kreiraj_izdatek(
                    page,
                    bdn_id,
                    podatki["analitika_polno"],
                    podatki["znesek_gotovina"],
                    podatki["znesek_kartica"],
                )

                # 4. Popravi temeljnico
                await popravi_temeljnico(page, podatki)

                obdelani.append(podatki)

            except Exception as exc:
                log.exception(f"  NAPAKA pri tm_id={tm_id}: {exc}")
                napake.append(tm_id)

        # ── POROČILO ──
        log.info(f"\n{'='*50}")
        log.info("POROČILO")
        log.info(f"{'='*50}")
        log.info(f"Uspešno obdelanih: {len(obdelani)}")
        for o in obdelani:
            log.info(
                f"  ✓ {o['datum']} | {o['analitika_sifra']:5s} | "
                f"Gotovina: {o['znesek_gotovina']:8.2f} | "
                f"Kartica: {o['znesek_kartica']:8.2f} | "
                f"Skupaj: {o['skupaj']:8.2f} EUR"
            )

        if napake:
            log.warning(f"Napake ({len(napake)} osnutkov): {napake}")
        else:
            log.info("Vse obdelano brez napak ✓")


if __name__ == "__main__":
    asyncio.run(main())
