# Agent Hub — Navodila za namestitev

## Kaj potrebujete

- Brezplačen račun na **GitHub** (github.com)
- Brezplačen račun na **Streamlit Cloud** (streamlit.io)

---

## Korak 1 — GitHub repozitorij

1. Prijavite se na github.com
2. Kliknite **"New repository"** (zeleni gumb zgoraj desno)
3. Ime: `agent-hub`
4. Izberite **Private** (zasebno!)
5. Kliknite **Create repository**

### Naložite datoteke

V novem repozitoriju kliknite **"uploading an existing file"** in naložite:
- `app.py`
- `minimax_client.py`
- `lot_engine.py`
- `requirements.txt`

Kliknite **"Commit changes"**.

---

## Korak 2 — Streamlit Cloud

1. Pojdite na **share.streamlit.io**
2. Prijavite se z GitHub računom
3. Kliknite **"New app"**
4. Izberite vaš repozitorij `agent-hub`
5. Main file path: `app.py`
6. Kliknite **Deploy**

Čez ~2 minuti bo aplikacija živa na naslovu npr. `https://vase-ime-agent-hub.streamlit.app`

---

## Korak 3 — Minimax API dostop

1. Prijavite se v Minimax
2. Kliknite svoje ime (zgoraj desno) → **Moj profil**
3. Kliknite **Urejanje osnovnih podatkov**
4. Pomaknite se na dno → **Gesla za dostop zunanjih aplikacij**
5. Kliknite **Nova aplikacija**
6. Vnesite ime: `AgentHub`
7. Zapišite si **uporabniško ime** in **geslo**

Za `client_id` in `client_secret` kontaktirajte Minimax podporo
(pišite zahtevek za pomoč, napišite da potrebujete OAuth2 client credentials za API integracijo).

**ID organizacije** najdete v URL-ju ko ste prijavljeni v Minimax:
`https://moj.minimax.si/SI/VA/**WebUI/12345**/...` → številka je vaš org_id.

---

## Korak 4 — ID-ji skladišč in analitik

Ko je aplikacija zagnana:

1. Vnesite API podatke v stransko vrstico
2. Kliknite **"Poišči ID-je analitik avtomatsko"** — aplikacija sama poišče ID-je MPK1, MPK2, MPK3, MPOC
3. Za Warehouse ID-je pojdite v Minimax → **Šifranti → Skladišča** in poiščite ID vaših maloprodajnih skladišč

---

## Dnevna uporaba

1. Odprite aplikacijo (zaznamek v brskalniku)
2. Izberite zavihek lokacije (npr. MPK2)
3. Kliknite **"Poišči osnutke"**
4. Izberite dokument
5. Kliknite **"Zaženi agenta"**
6. Preglejte rezultate (zeleno = ok, rumeno = zamenjano, rdeče = brez lota)
7. Kliknite **"Shrani in pošlji v Minimax"**

---

## Barve v rezultatih

| Barva | Pomen |
|-------|-------|
| 🟢 | Točno ujemanje, lot dodeljen |
| 🟡 | Pametna zamenjava artikla (opis ima notacijo npr. `(BRASH0301)→(BRASH0302)`) |
| 🟠 | Delno pokrito — del brez lota |
| 🔴 | Brez lota — potrebna ročna obdelava |

---

## Podpora

Za nadgradnje in nove funkcije se obrnite na razvijalca.
