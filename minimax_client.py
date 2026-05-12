"""
Minimax API odjemalec.
Dokumentacija: https://moj.minimax.si/SI/API
"""

import requests
from datetime import datetime
from typing import Optional


BASE     = "https://moj.minimax.si/SI/API"
AUTH_URL = "https://moj.minimax.si/SI/AUT/OAuth20/Token"

LOCATIONS = {
    "MPK1": {"name": "Potujoča 1",        "analytic_name": "MPK1"},
    "MPK2": {"name": "Potujoča 2",        "analytic_name": "MPK2"},
    "MPK3": {"name": "Potujoča 3",        "analytic_name": "MPK3"},
    "MPOC": {"name": "Ribarnica Domžale", "analytic_name": "MPOC"},
}

BLAGAJNE = {
    "MPK1": "Maloprodaja kombi 1",
    "MPK2": "Maloprodaja kombi 2",
    "MPK3": "Maloprodaja kombi 3",
    "MPOC": "Maloprodaja Orehovlje",
}


class MinimaxClient:
    def __init__(self, username: str, password: str, client_id: str,
                 client_secret: str, org_id: int):
        self.username      = username
        self.password      = password
        self.client_id     = client_id
        self.client_secret = client_secret
        self.org_id        = org_id
        self._token          = None
        self._token_expiry   = datetime.min
        self._analytics_map  = None  # cache: {analytic_id: code}

    # ── Auth ─────────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._token and datetime.now() < self._token_expiry:
            return self._token
        r = requests.post(AUTH_URL, data={
            "grant_type":    "password",
            "username":      self.username,
            "password":      self.password,
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
        }, timeout=15)
        if not r.ok:
            raise Exception(f"Prijava neuspešna ({r.status_code}): {r.text[:300]}")
        data = r.json()
        self._token = data["access_token"]
        expires_in  = int(data.get("expires_in", 3600))
        from datetime import timedelta
        self._token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type":  "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{BASE}/api/orgs/{self.org_id}{path}"
        r = requests.get(url, headers=self._headers(), params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, body: dict) -> dict:
        url = f"{BASE}/api/orgs/{self.org_id}{path}"
        r = requests.put(url, headers=self._headers(), json=body, timeout=20)
        if not r.ok:
            raise Exception(f"PUT {path} → {r.status_code}: {r.text[:500]}")
        return r.json()

    # ── Journal (Temeljnice) ──────────────────────────────────────────────────

    def get_journal_drafts(self) -> list[dict]:
        """
        Vrne osnutke temeljnic tipa DI (dnevni iztržek iz Shopsy).
        1. Pobere vse DI journale (JournalType=DI) — ~136 zapisov
        2. Za vsak pokliče GetJournal ki vrne pravi Status
        3. Obdrži samo Status=O (osnutek)
        """
        di_ids = []
        page   = 1
        while True:
            data = self._get("/journals", params={
                "JournalType": "DI",
                "CurrentPage": page,
                "PageSize":    50,
            })
            rows = data.get("Rows", [])
            for row in rows:
                di_ids.append(row.get("JournalId"))
            total   = data.get("TotalRows", 0)
            fetched = (page - 1) * 50 + len(rows)
            if fetched >= total or not rows:
                break
            page += 1

        result = []
        for jid in di_ids:
            try:
                j = self.get_journal(jid)
                if str(j.get("Status", "")) == "O":
                    result.append(j)
            except Exception:
                continue
        return result

    def get_journal_drafts_debug(self) -> dict:
        """Debug: cel tok iskanja osnutkov — 3 koraki."""
        try:
            osnutki = self.get_journal_drafts()
            k1 = {"najdeno": len(osnutki), "ids": [j.get("JournalId") for j in osnutki]}
        except Exception as e:
            k1 = {"napaka": str(e)}
            osnutki = []

        k2 = []
        for j in osnutki:
            try:
                p = self.parse_journal_placila(j)
                k2.append({
                    "id":            j.get("JournalId"),
                    "entries_count": len(j.get("JournalEntries", [])),
                    "parse_ok":      p is not None,
                    "sifra":         p.get("analitika_sifra") if p else None,
                    "skupaj":        p.get("skupaj") if p else None,
                })
            except Exception as e:
                k2.append({"id": j.get("JournalId"), "napaka": str(e)})

        # Pokaži cel entry (Account + Analytic) za prvi osnutek
        k3 = {}
        if osnutki:
            jid = osnutki[0].get("JournalId")
            try:
                j       = self.get_journal(jid)
                entries = j.get("JournalEntries", [])
                k3["prvi_osnutek"] = {
                    "JournalId":   jid,
                    "Description": j.get("Description"),
                    "entries": [{
                        "Account":  e.get("Account"),
                        "Analytic": e.get("Analytic"),
                        "Debit":    e.get("Debit"),
                        "Credit":   e.get("Credit"),
                    } for e in entries]
                }
            except Exception as e:
                k3["prvi_osnutek"] = {"napaka": str(e)}

        return {"k1_get_drafts": k1, "k2_parse": k2, "k3_direktno": k3}

    def get_journal(self, journal_id: int) -> dict:
        return self._get(f"/journals/{journal_id}")

    def update_journal(self, journal_id: int, journal_data: dict) -> dict:
        return self._put(f"/journals/{journal_id}", journal_data)

    def parse_journal_placila(self, journal: dict) -> dict | None:
        """
        Iz temeljnice izvleče podatke za blagajno.
        Vrne None če ni kontov 1000/1652.
        Interni ID-ji za Oltre Con d.o.o.:
          72537347 = konto 1000 (gotovina)
          72537491 = konto 1652 (kartica)
        """
        entries     = journal.get("JournalEntries", [])
        datum       = journal.get("JournalDate", "")[:10]
        journal_id  = journal.get("JournalId")
        row_version = journal.get("RowVersion", "")

        ID_GOTOVINA = 72537347
        ID_KARTICA  = 72537491

        data_1652 = None
        data_1000 = None

        import re

        def _analytic_sifra_from_code(code):
            m = re.search(r"(MPK\d+|MPOC)", code or "")
            return m.group(1) if m else ""

        def _analytic_sifra(entry):
            an   = entry.get("Analytic") or {}
            code = an.get("Code", "") or ""
            desc = entry.get("Description", "") or ""
            jdesc = journal.get("Description", "") or ""
            combined = f"{code} {desc} {jdesc}"
            m = re.search(r"(MPK\d+|MPOC)", combined)
            return m.group(1) if m else ""

        for entry in entries:
            acc_id  = (entry.get("Account") or {}).get("ID")
            an_obj  = entry.get("Analytic") or {}
            an_id   = an_obj.get("ID")
            an_code = an_obj.get("Code", "") or ""
            # Če Code ni na voljo, poišči po ID-ju
            if not an_code and an_id:
                an_code = self._get_analytic_code(an_id)
            sifra = _analytic_sifra_from_code(an_code) or _analytic_sifra(entry)

            debit  = float(entry.get("Debit", 0) or 0)
            credit = float(entry.get("Credit", 0) or 0)
            znesek = debit if debit > 0 else credit

            if acc_id == ID_KARTICA and not data_1652:
                data_1652 = {"analitika": an_code, "sifra": sifra, "znesek": znesek}
            elif acc_id == ID_GOTOVINA and not data_1000:
                data_1000 = {"analitika": an_code, "sifra": sifra, "znesek": znesek}

        if not data_1652 and not data_1000:
            return None

        an_polno        = (data_1652 or data_1000)["analitika"]
        sifra           = (data_1652 or data_1000)["sifra"]
        znesek_kartica  = data_1652["znesek"] if data_1652 else 0.0
        znesek_gotovina = data_1000["znesek"] if data_1000 else 0.0
        skupaj          = round(znesek_kartica + znesek_gotovina, 2)
        rezim = "oba" if (data_1652 and data_1000) else ("samo_kartica" if data_1652 else "samo_gotovina")

        return {
            "journal_id":      journal_id,
            "datum":           datum,
            "analitika_sifra": sifra,
            "analitika_polno": an_polno,
            "blagajna_naziv":  BLAGAJNE.get(sifra, sifra),
            "znesek_kartica":  znesek_kartica,
            "znesek_gotovina": znesek_gotovina,
            "skupaj":          skupaj,
            "rezim":           rezim,
            "row_version":     row_version,
            "entries":         entries,
            "journal_raw":     journal,
        }

    def popravi_in_potrdi_journal(self, podatki: dict) -> bool:
        """Popravi knjižbe 1652/1000 → 120000 in potrdi temeljnico."""
        ID_GOTOVINA = 72537347
        ID_KARTICA  = 72537491

        # Svež GetJournal za pravilen RowVersion
        journal = self.get_journal(podatki["journal_id"])
        entries = journal.get("JournalEntries", [])

        stranka_obj = None
        for e in entries:
            s = e.get("Customer") or e.get("Supplier")
            if s and s.get("ID"):
                stranka_obj = s
                break

        if not stranka_obj:
            try:
                stranke = self._get("/customers", params={"Search": "Končni kupec", "PageSize": 10})
                for s in stranke.get("Rows", []):
                    if "končni kupec" in s.get("Name", "").lower():
                        stranka_obj = {"ID": s["CustomerID"]}
                        break
            except Exception:
                pass

        # Odstrani 1652/1000 in morebitne obstoječe 120000 vrstice (cleanup duplikatov)
        nove_entries, entry_1652, entry_1000 = [], None, None
        for entry in entries:
            acc      = entry.get("Account") or {}
            acc_id   = acc.get("ID")
            acc_name = (acc.get("Name", "") or "").lower()
            # Ujemanje po ID-ju IN imenu konta
            is_kartica  = (acc_id == ID_KARTICA)  or "1652" in acc_name
            is_gotovina = (acc_id == ID_GOTOVINA) or ("1000 -" in acc_name)
            is_120000   = (acc_id == 130744074)   or "120000" in acc_name
            if is_kartica and not entry_1652:    entry_1652 = entry
            elif is_gotovina and not entry_1000: entry_1000 = entry
            elif is_120000:                      pass  # preskoči obstoječe 120000
            else:                                nove_entries.append(entry)

        ref_entry    = entry_1652 or entry_1000
        analitika_id = (ref_entry.get("Analytic") or {}).get("ID") if ref_entry else None

        # Interni ID za konto 120000 — Oltre Con d.o.o.
        konto_120000_id = 130744074

        # Datum iz journala, valuta EUR
        journal_date = journal.get("JournalDate", "")
        entry_date   = journal_date if journal_date else datetime.now().strftime("%Y-%m-%dT00:00:00")
        if ref_entry and ref_entry.get("EntryDate"):
            entry_date = ref_entry.get("EntryDate")

        # Kopiraj strukturo iz prve obstoječe knjižbe
        template = dict(nove_entries[0]) if nove_entries else {}
        journal_date = journal.get("JournalDate", "")

        # Končni kupec - maloprodaja (Oltre Con d.o.o.) — hardkodirano
        if not stranka_obj:
            stranka_obj = {"ID": 17414634}

        nova = {
            **template,
            "Account":                    {"ID": konto_120000_id},
            "Analytic":                   {"ID": analitika_id} if analitika_id else None,
            "Customer":                   stranka_obj,
            "Debit":                      podatki["skupaj"],
            "Credit":                     0,
            "DebitInDomesticCurrency":    podatki["skupaj"],
            "CreditInDomesticCurrency":   0,
            "TransactionDate":            journal_date,
            "DueDate":                    journal_date,
        }
        # Odstrani readonly polja
        for f in ["JournalEntryId", "RowVersion", "RecordDtModified", "ResourceUrl", "Journal"]:
            nova.pop(f, None)
        nove_entries.append(nova)

        # En sam PUT — posodobi knjižbe IN potrdi
        self.update_journal(podatki["journal_id"], {
            **journal,
            "Status":         "P",
            "JournalEntries": nove_entries,
        })
        return True

    # ── Analitike ─────────────────────────────────────────────────────────────

    def _get_analytic_code(self, analytic_id) -> str:
        """Vrne kodo analitike (npr. 'MPK2') po internem ID-ju. Cachira rezultat."""
        if self._analytics_map is None:
            self._analytics_map = {}
            try:
                for row in self.get_analytics():
                    aid  = row.get("AnalyticId")
                    code = row.get("Code", "") or ""
                    if aid and code:
                        self._analytics_map[aid] = code
            except Exception:
                pass
        return self._analytics_map.get(analytic_id, "")

    def get_analytics(self) -> list[dict]:
        """Vrne seznam analitik (za iskanje ID-jev MPK1, MPK2 ...)."""
        result = []
        page   = 1
        while True:
            data = self._get("/analytics", params={"CurrentPage": page, "PageSize": 100})
            rows = data.get("Rows", [])
            result.extend(rows)
            if len(result) >= data.get("TotalRows", 0):
                break
            page += 1
        return result

    def get_analytic_id(self, analytic_code: str) -> Optional[int]:
        """Vrne ID analitike po kodi (npr. 'MPK2')."""
        for row in self.get_analytics():
            if row.get("Code", "").upper() == analytic_code.upper():
                return row.get("AnalyticId")
        return None

    # ── Osnutki dokumentov ────────────────────────────────────────────────────

    RETAIL_CUSTOMER = "končni kupec - maloprodaja"

    def get_draft_entries(self, analytic_id: int) -> list[dict]:
        """
        Vrne osnutke (Status=O) izdaj strank za dano analitiko.
        Filtrira SAMO dokumente s stranko 'Končni kupec - maloprodaja'.
        """
        result = []
        page   = 1
        while True:
            data = self._get("/stockentry", params={
                "StockEntryType":    "I",
                "StockEntrySubtype": "S",
                "Status":            "O",
                "AnalyticId":        analytic_id,
                "CurrentPage":       page,
                "PageSize":          50,
            })
            rows = data.get("Rows", [])
            for row in rows:
                customer_name = row.get("Customer", {}).get("Name", "")
                if self.RETAIL_CUSTOMER in customer_name.lower():
                    result.append(row)
            total   = data.get("TotalRows", 0)
            fetched = (page - 1) * 50 + len(rows)
            if fetched >= total:
                break
            page += 1
        return result

    def get_entry_detail(self, entry_id: int) -> dict:
        return self._get(f"/stockentry/{entry_id}")

    # ── Zaloga po lotih ───────────────────────────────────────────────────────

    def get_stock_by_lots(self, warehouse_id: int) -> list[dict]:
        result = []
        page   = 1
        while True:
            data = self._get("/stocks", params={
                "WarehouseId":          warehouse_id,
                "ResultsByBatchNumber": "Y",
                "CurrentPage":          page,
                "PageSize":             200,
            })
            rows = data.get("Rows", [])
            result.extend(rows)
            if len(result) >= data.get("TotalRows", 0):
                break
            page += 1
        return result

    def get_stock_for_items(self, warehouse_id: int, item_ids: list[int]) -> list[dict]:
        """
        Izgradi lot zalogo iz prenosnih dokumentov (IL/IS) za dano skladišče.
        Sešteje prejete lote (IL prejemi) in odšteje prodane (IS potrjeni).
        """
        from collections import defaultdict
        from datetime import datetime, timedelta

        # Razreši numerični warehouse ID (npr. "MP-K2" → 27421)
        numeric_wh_id = warehouse_id
        try:
            for wh in self.get_warehouses():
                wh_num  = wh.get("WarehouseId") or wh.get("ID")
                wh_code = wh.get("Code", "")
                if str(wh_num) == str(warehouse_id) or wh_code == str(warehouse_id):
                    numeric_wh_id = wh_num
                    break
        except Exception:
            pass

        item_info = {}
        try:
            base = self.get_stock_by_lots(warehouse_id)
            for r in base:
                aid = (r.get("Item") or {}).get("ID")
                if aid:
                    item_info[aid] = {
                        "ItemName":          r.get("ItemName", ""),
                        "UnitOfMeasurement": r.get("UnitOfMeasurement", "kg"),
                    }
        except Exception:
            pass

        lot_qty   = defaultdict(lambda: defaultdict(float))
        lot_price = defaultdict(lambda: defaultdict(float))
        date_from = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00")

        for entry_type, subtype, sign in [("P", "L", 1.0), ("I", "S", -1.0)]:
            page = 1
            while True:
                try:
                    data = self._get("/stockentry", params={
                        "StockEntryType":    entry_type,
                        "StockEntrySubtype": subtype,
                        "Status":            "P",
                        "DateFrom":          date_from,
                        "CurrentPage":       page,
                        "PageSize":          50,
                    })
                    rows = data.get("Rows", [])
                    for entry in rows:
                        eid = entry.get("StockEntryId")
                        if not eid: continue
                        try:
                            detail = self.get_entry_detail(eid)
                            for row in (detail.get("StockEntryRows") or []):
                                wh_from = (row.get("WarehouseFrom") or {}).get("ID")
                                wh_to   = (row.get("WarehouseTo") or {}).get("ID")
                                if entry_type == "P" and str(wh_to) != str(numeric_wh_id): continue
                                if entry_type == "I" and str(wh_from) != str(numeric_wh_id): continue
                                item_id = (row.get("Item") or {}).get("ID")
                                batch   = row.get("BatchNumber", "") or ""
                                qty     = float(row.get("Quantity") or 0)
                                price = float(row.get("Price") or 0)
                                if item_id and batch and qty > 0:
                                    lot_qty[item_id][batch] += sign * qty
                                    if price > 0:
                                        lot_price[item_id][batch] = price
                                    if item_id not in item_info:
                                        item_info[item_id] = {
                                            "ItemName":          row.get("ItemName") or (row.get("Item") or {}).get("Name", ""),
                                            "UnitOfMeasurement": row.get("UnitOfMeasurement", "kg"),
                                        }
                        except Exception: continue
                    total   = data.get("TotalRows", 0)
                    fetched = (page - 1) * 50 + len(rows)
                    if fetched >= total: break
                    page += 1
                except Exception: break

        result = []
        for item_id, batches in lot_qty.items():
            info = item_info.get(item_id, {})
            for batch, qty in batches.items():
                if qty > 0.001:
                    result.append({
                        "Item":              {"ID": item_id},
                        "ItemName":          info.get("ItemName", ""),
                        "ItemCode":          "",
                        "BatchNumber":       batch,
                        "Quantity":          round(qty, 4),
                        "UnitOfMeasurement": info.get("UnitOfMeasurement", "kg"),
                        "Price":             lot_price.get(item_id, {}).get(batch, 0),
                    })
        return result

    def diagnose_lots(self, warehouse_id: int) -> dict:
        from datetime import datetime, timedelta
        date_from = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00")
        found = []
        for etype in ["P", "I"]:
            for subtype in ["S", "L", "P", "R"]:
                try:
                    data = self._get("/stockentry", params={
                        "StockEntryType": etype, "StockEntrySubtype": subtype,
                        "Status": "P", "DateFrom": date_from,
                        "CurrentPage": 1, "PageSize": 5,
                    })
                    rows = data.get("Rows", [])
                    if rows:
                        eid = rows[0].get("StockEntryId")
                        if eid:
                            detail = self.get_entry_detail(eid)
                            for r in (detail.get("StockEntryRows") or []):
                                if r.get("BatchNumber"):
                                    found.append({
                                        "type":    f"{etype}/{subtype}",
                                        "batch":   r.get("BatchNumber"),
                                        "wh_from": (r.get("WarehouseFrom") or {}).get("ID"),
                                        "wh_to":   (r.get("WarehouseTo") or {}).get("ID"),
                                        "our_wh":  warehouse_id,
                                    })
                except Exception: pass
        return {"found": found, "warehouse_id": warehouse_id}

    def get_item_units(self, item_ids: list[int]) -> dict[int, str]:
        result = {}
        try:
            page = 1
            while True:
                data    = self._get("/items/itemsdata", params={"CurrentPage": page, "PageSize": 500})
                rows    = data.get("Rows") or data if isinstance(data, list) else []
                if not rows and isinstance(data, dict):
                    rows = data.get("Rows", [])
                for row in rows:
                    aid  = row.get("ItemId") or (row.get("Item") or {}).get("ID")
                    unit = row.get("UnitOfMeasurement") or row.get("Unit") or ""
                    if aid and unit: result[int(aid)] = unit
                total   = data.get("TotalRows", 0) if isinstance(data, dict) else 0
                fetched = (page - 1) * 500 + len(rows)
                if fetched >= total or not rows: break
                page += 1
        except Exception:
            for item_id in item_ids:
                try:
                    d    = self._get(f"/items/{item_id}")
                    unit = d.get("UnitOfMeasurement") or d.get("Unit") or ""
                    if unit: result[item_id] = unit
                except Exception: continue
        return result

    def get_warehouses(self) -> list[dict]:
        data = self._get("/warehouses", params={"CurrentPage": 1, "PageSize": 100})
        return data.get("Rows", [])

    def update_entry_with_lots(self, entry_id: int, entry_data: dict, new_rows: list[dict]) -> dict:
        """
        Posodobi dokument z dodelitvami lotov.
        Originalne vrstice ohranimo z StockEntryRowId + dodamo BatchNumber.
        Dodatne vrstice (drugi loti) pošljemo brez StockEntryRowId.
        """
        fresh = self.get_entry_detail(entry_id)
        orig_rows = fresh.get("StockEntryRows") or []

        # Indeks originalnih vrstic po RowNumber (1-based → 0-based)
        orig_by_rownum = {r.get("RowNumber", 0) - 1: r for r in orig_rows}

        # Vzemi WarehouseFrom iz prve originalne vrstice
        default_wh_from = None
        if orig_rows:
            default_wh_from = orig_rows[0].get("WarehouseFrom")

        api_rows    = []
        used_row_ids = set()

        for r in new_rows:
            row_id            = r.get("row_id", 0)
            orig_for_writeoff = orig_by_rownum.get(row_id)

            if r.get("_writeoff"):
                orig_sp = orig_for_writeoff.get("SellingPrice") if orig_for_writeoff else None
                row = {
                    "Item":          {"ID": r["article_id"]},
                    "Quantity":      r["quantity_assigned"],
                    "Note":          r.get("opis", "") or "",
                    "BatchNumber":   r["lot"],
                    "WarehouseFrom": default_wh_from,
                }
                if orig_sp:
                    row["SellingPrice"] = orig_sp
                api_rows.append(row)
                continue
            orig              = orig_by_rownum.get(row_id)
            orig_article_id   = (orig.get("Item") or {}).get("ID") if orig else None
            result_article_id = r.get("article_id")

            if orig and orig_article_id == result_article_id and row_id not in used_row_ids:
                # Prva vrstica tega row_id — ohrani StockEntryRowId
                new_orig = {**orig}
                if r.get("lot"):
                    new_orig["BatchNumber"] = r["lot"]
                new_orig["Quantity"] = r["quantity_assigned"]
                api_rows.append(new_orig)
                used_row_ids.add(row_id)
            else:
                # Dodatna vrstica (drugi lot) ali zamenjava — nova vrstica brez StockEntryRowId
                row = {
                    "Item":         {"ID": result_article_id},
                    "Quantity":     r["quantity_assigned"],
                    "SellingPrice": r.get("selling_price"),
                    "Note":         r.get("opis", "") or "",
                }
                if r.get("lot"):
                    row["BatchNumber"] = r["lot"]
                if r.get("unit"):
                    row["UnitOfMeasurement"] = r["unit"]
                # Vzemi Price in WarehouseFrom iz originalne vrstice istega row_id
                orig_for_row = orig_by_rownum.get(row_id)
                if orig_for_row:
                    if orig_for_row.get("Price") is not None:
                        row["Price"] = orig_for_row.get("Price")
                    if orig_for_row.get("WarehouseFrom"):
                        row["WarehouseFrom"] = orig_for_row.get("WarehouseFrom")
                elif default_wh_from:
                    row["WarehouseFrom"] = default_wh_from
                api_rows.append(row)

        def _clean_row(row):
            """Ohrani samo nujna polja za vrstico."""
            KEEP = {"StockEntryRowId", "Item", "Quantity", "BatchNumber",
                    "WarehouseFrom", "SellingPrice", "UnitOfMeasurement", "Note"}
            cleaned = {}
            for k, v in row.items():
                if k not in KEEP:
                    continue
                if v is None:
                    continue
                # Ne pošiljaj praznega BatchNumber
                if k == "BatchNumber" and not v:
                    continue
                # Ne pošiljaj 0 vrednosti za cene
                if k in ("SellingPrice",) and v == 0.0:
                    continue
                if isinstance(v, dict) and "ID" in v:
                    cleaned[k] = {"ID": v["ID"]}
                else:
                    cleaned[k] = v
            return cleaned

        api_rows = [_clean_row(r) for r in api_rows]

        # Združi vrstice z istim artiklom in lotom v eno
        merged = {}
        merged_order = []
        for row in api_rows:
            item_id = (row.get("Item") or {}).get("ID")
            batch   = row.get("BatchNumber", "")
            key     = (item_id, batch)
            if key in merged:
                merged[key]["Quantity"] = round(
                    merged[key]["Quantity"] + row.get("Quantity", 0), 4
                )
            else:
                merged[key] = dict(row)
                merged_order.append(key)
        api_rows = [merged[k] for k in merged_order]

        # Očisti fresh — readonly polja in ResourceUrl iz FK objektov
        SKIP_KEYS = {"StockEntryId", "Number", "RowVersion", "RecordDtModified",
                     "ResourceUrl", "StockEntryRows", "AssociationWithIssuedInvoice"}

        def _clean_fk(v):
            if isinstance(v, dict) and "ID" in v:
                return {"ID": v["ID"]}
            return v

        body = {
            "StockEntryType":    fresh.get("StockEntryType"),
            "StockEntrySubtype": fresh.get("StockEntrySubtype"),
            "Date":              fresh.get("Date"),
            "Customer":          {"ID": (fresh.get("Customer") or {}).get("ID")},
            "Analytic":          {"ID": (fresh.get("Analytic") or {}).get("ID")},
            "Status":            fresh.get("Status"),
            "RowVersion":        fresh.get("RowVersion"),
            "StockEntryRows":    api_rows,
        }
        # Odstrani None vrednosti
        body = {k: v for k, v in body.items() if v is not None}
        return self._put(f"/stockentry/{entry_id}", body)


# ── Pretvorba ─────────────────────────────────────────────────────────────────

def parse_stock_to_engine_format(stock_rows: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in stock_rows:
        name  = row.get("ItemName", "")
        code  = row.get("ItemCode", "") or ""
        aid   = row.get("Item", {}).get("ID")
        batch = row.get("BatchNumber", "")
        qty   = float(row.get("Quantity") or 0)
        unit  = row.get("UnitOfMeasurement") or row.get("Unit") or ""
        if not aid or qty <= 0: continue
        key = str(aid)
        if key not in result:
            result[key] = {"article_id": aid, "article_code": code, "article_name": name, "lots": []}
        if batch:
            result[key]["lots"].append({"code": batch, "quantity": qty, "unit": unit, "price": float(row.get("Price") or 0)})
    return result


def parse_entry_to_lines(entry_detail: dict, item_units: dict = None) -> list[dict]:
    rows  = entry_detail.get("StockEntryRows") or []
    lines = []
    for i, item in enumerate(rows):
        item_fk = item.get("Item") or {}
        item_id = item_fk.get("ID")
        unit    = (item.get("UnitOfMeasurement") or item.get("Unit") or
                   item.get("UOM") or item.get("MeasureUnit") or
                   (item_units.get(item_id) if item_units and item_id else None) or "")
        lines.append({
            "row_id":             i,
            "stock_entry_row_id": item.get("StockEntryRowId"),
            "article_id":         item_id,
            "article_code":       item.get("ItemCode", "") or item_fk.get("Code", "") or str(item_id or ""),
            "article_name":       item.get("ItemName", "") or item_fk.get("Name", ""),
            "quantity":           float(item.get("Quantity") or 0),
            "unit":               unit,
            "selling_price":      item.get("SellingPrice") or item.get("Price"),
            "lot":                item.get("BatchNumber", "") or "",
            "opis":               item.get("SerialNumber", "") or "",
            "row_version":        item.get("RowVersion", ""),
        })
    return lines
