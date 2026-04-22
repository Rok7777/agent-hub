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
        self._token        = None
        self._token_expiry = datetime.min

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
        from datetime import timedelta
        self._token_expiry = datetime.now() + timedelta(seconds=int(data.get("expires_in", 3600)) - 60)
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}", "Content-Type": "application/json"}

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{BASE}/api/orgs/{self.org_id}{path}"
        r = requests.get(url, headers=self._headers(), params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, body: dict) -> dict:
        url = f"{BASE}/api/orgs/{self.org_id}{path}"
        r = requests.put(url, headers=self._headers(), json=body, timeout=20)
        r.raise_for_status()
        return r.json()

    # ── Journal ───────────────────────────────────────────────────────────────

    def get_journal_drafts(self) -> list[dict]:
        """
        Vrne osnutke temeljnic tipa DI.
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
        # Korak 1: get_journal_drafts
        try:
            osnutki = self.get_journal_drafts()
            k1 = {"najdeno": len(osnutki), "ids": [j.get("JournalId") for j in osnutki]}
        except Exception as e:
            k1 = {"napaka": str(e)}
            osnutki = []

        # Korak 2: parse_journal_placila za vsak osnutek
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

        # Korak 3: pokaži cel Account objekt
        k3 = {}
        for jid in [225001987, 225001984]:
            try:
                j       = self.get_journal(jid)
                entries = j.get("JournalEntries", [])
                k3[jid] = {
                    "Status":        j.get("Status"),
                    "entries_count": len(entries),
                    "entries_raw":   [e.get("Account") for e in entries[:6]],
                }
            except Exception as e:
                k3[jid] = {"napaka": str(e)}

        return {"k1_get_drafts": k1, "k2_parse": k2, "k3_direktno": k3}

    def get_journal(self, journal_id: int) -> dict:
        return self._get(f"/journals/{journal_id}")

    def update_journal(self, journal_id: int, journal_data: dict) -> dict:
        return self._put(f"/journals/{journal_id}", journal_data)

    def parse_journal_placila(self, journal: dict) -> dict | None:
        entries     = journal.get("JournalEntries", [])
        datum       = journal.get("JournalDate", "")[:10]
        journal_id  = journal.get("JournalId")
        row_version = journal.get("RowVersion", "")

        data_1652 = None
        data_1000 = None

        # Interni ID-ji za konte 1000 in 1652 v Minimax (Oltre Con d.o.o.)
        ID_GOTOVINA = 72537347   # konto 1000
        ID_KARTICA  = 72537491   # konto 1652

        import re

        # Analitiko (MPK2/MPK3/...) izvlečemo iz opisa journala
        # Opis je npr. "DI:20260418_120000" — analitika je v Description AccountEntry-ja
        # ali iz opisa samega journala ki se začne z "DI:"
        journal_desc = journal.get("Description", "") or ""
        # Poiščemo MPKx ali MPOC v opisu vseh entries
        sifra_journal = ""
        an_polno_journal = ""
        for entry in entries:
            desc = entry.get("Description", "") or ""
            acc_name = (entry.get("Account") or {}).get("Name", "") or ""
            an_obj = entry.get("Analytic") or {}
            an_code_try = an_obj.get("Code", "") or ""
            if not an_code_try:
                # Poskusi iz ResourceUrl zadnji segment
                url = an_obj.get("ResourceUrl", "") or ""
            m = re.search(r"(MPK\d+|MPOC)", desc + " " + an_code_try + " " + journal_desc)
            if m and not sifra_journal:
                sifra_journal    = m.group(1)
                an_polno_journal = an_code_try or sifra_journal

        for entry in entries:
            acc_obj = entry.get("Account") or {}
            acc_id  = acc_obj.get("ID")

            debit  = float(entry.get("Debit", 0) or 0)
            credit = float(entry.get("Credit", 0) or 0)
            znesek = debit if debit > 0 else credit

            if acc_id == ID_KARTICA and not data_1652:
                data_1652 = {"analitika": an_polno_journal, "sifra": sifra_journal, "znesek": znesek}
            elif acc_id == ID_GOTOVINA and not data_1000:
                data_1000 = {"analitika": an_polno_journal, "sifra": sifra_journal, "znesek": znesek}

        if not data_1652 and not data_1000:
            return None

        an_polno        = (data_1652 or data_1000)["analitika"]
        sifra           = (data_1652 or data_1000)["sifra"]
        znesek_kartica  = data_1652["znesek"] if data_1652 else 0.0
        znesek_gotovina = data_1000["znesek"] if data_1000 else 0.0
        skupaj          = round(znesek_kartica + znesek_gotovina, 2)
        rezim = "oba" if (data_1652 and data_1000) else ("samo_kartica" if data_1652 else "samo_gotovina")

        return {
            "journal_id": journal_id, "datum": datum,
            "analitika_sifra": sifra, "analitika_polno": an_polno,
            "blagajna_naziv": BLAGAJNE.get(sifra, sifra),
            "znesek_kartica": znesek_kartica, "znesek_gotovina": znesek_gotovina,
            "skupaj": skupaj, "rezim": rezim, "row_version": row_version,
            "entries": entries, "journal_raw": journal,
        }

    def popravi_in_potrdi_journal(self, podatki: dict) -> bool:
        journal = podatki["journal_raw"]
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

        # Interni ID-ji za konte 1000 in 1652
        ID_GOTOVINA = 72537347
        ID_KARTICA  = 72537491

        nove_entries, entry_1652, entry_1000 = [], None, None
        for entry in entries:
            acc_id = (entry.get("Account") or {}).get("ID")
            if acc_id == ID_KARTICA:   entry_1652 = entry
            elif acc_id == ID_GOTOVINA: entry_1000 = entry
            else:                       nove_entries.append(entry)

        ref_entry    = entry_1652 or entry_1000
        analitika_id = (ref_entry.get("Analytic") or {}).get("ID") if ref_entry else None
        entry_date   = ref_entry.get("EntryDate") if ref_entry else None
        description  = ref_entry.get("Description") if ref_entry else None

        # Poišči interni ID za konto 120000
        konto_120000_id = None
        try:
            acc_rows = self._get("/accounts", params={"Code": "120000", "PageSize": 5})
            for a in acc_rows.get("Rows", []):
                if str(a.get("Code", "")) == "120000":
                    konto_120000_id = a.get("AccountId") or a.get("ID")
                    break
        except Exception:
            pass

        nova = {
            "Account":     {"ID": konto_120000_id} if konto_120000_id else {"Code": "120000"},
            "Analytic":    {"ID": analitika_id} if analitika_id else None,
            "Customer":    stranka_obj,
            "Debit":       podatki["skupaj"],
            "Credit":      0,
            "EntryDate":   entry_date,
            "Description": description,
        }
        nove_entries.append(nova)

        # Svež GetJournal za pravilni RowVersion
        svez = self.get_journal(podatki["journal_id"])
        self.update_journal(podatki["journal_id"], {
            **svez,
            "Status":         "P",
            "JournalEntries": nove_entries,
        })
        return True

    # ── Analitike ─────────────────────────────────────────────────────────────

    def get_analytics(self) -> list[dict]:
        result, page = [], 1
        while True:
            data = self._get("/analytics", params={"CurrentPage": page, "PageSize": 100})
            rows = data.get("Rows", [])
            result.extend(rows)
            if len(result) >= data.get("TotalRows", 0): break
            page += 1
        return result

    def get_analytic_id(self, analytic_code: str) -> Optional[int]:
        for row in self.get_analytics():
            if row.get("Code", "").upper() == analytic_code.upper():
                return row.get("AnalyticId")
        return None

    RETAIL_CUSTOMER = "končni kupec - maloprodaja"

    def get_draft_entries(self, analytic_id: int) -> list[dict]:
        result, page = [], 1
        while True:
            data = self._get("/stockentry", params={
                "StockEntryType": "I", "StockEntrySubtype": "S",
                "Status": "O", "AnalyticId": analytic_id,
                "CurrentPage": page, "PageSize": 50,
            })
            rows = data.get("Rows", [])
            for row in rows:
                if self.RETAIL_CUSTOMER in row.get("Customer", {}).get("Name", "").lower():
                    result.append(row)
            total   = data.get("TotalRows", 0)
            fetched = (page - 1) * 50 + len(rows)
            if fetched >= total: break
            page += 1
        return result

    def get_entry_detail(self, entry_id: int) -> dict:
        return self._get(f"/stockentry/{entry_id}")

    def get_stock_by_lots(self, warehouse_id: int) -> list[dict]:
        result, page = [], 1
        while True:
            data = self._get("/stocks", params={
                "WarehouseId": warehouse_id, "ResultsByBatchNumber": "Y",
                "CurrentPage": page, "PageSize": 200,
            })
            rows = data.get("Rows", [])
            result.extend(rows)
            if len(result) >= data.get("TotalRows", 0): break
            page += 1
        return result

    def get_stock_for_items(self, warehouse_id: int, item_ids: list[int]) -> list[dict]:
        from collections import defaultdict
        from datetime import datetime, timedelta

        item_info = {}
        try:
            for r in self.get_stock_by_lots(warehouse_id):
                aid = (r.get("Item") or {}).get("ID")
                if aid:
                    item_info[aid] = {"ItemName": r.get("ItemName", ""), "UnitOfMeasurement": r.get("UnitOfMeasurement", "kg")}
        except Exception:
            pass

        lot_qty   = defaultdict(lambda: defaultdict(float))
        date_from = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00")

        for entry_type, subtype, sign in [("P", "L", 1.0), ("I", "S", -1.0)]:
            page = 1
            while True:
                try:
                    data = self._get("/stockentry", params={
                        "StockEntryType": entry_type, "StockEntrySubtype": subtype,
                        "Status": "P", "DateFrom": date_from,
                        "CurrentPage": page, "PageSize": 50,
                    })
                    for entry in data.get("Rows", []):
                        eid = entry.get("StockEntryId")
                        if not eid: continue
                        try:
                            for row in (self.get_entry_detail(eid).get("StockEntryRows") or []):
                                wh_from = (row.get("WarehouseFrom") or {}).get("ID")
                                wh_to   = (row.get("WarehouseTo") or {}).get("ID")
                                if entry_type == "P" and wh_to != warehouse_id: continue
                                if entry_type == "I" and wh_from != warehouse_id: continue
                                item_id = (row.get("Item") or {}).get("ID")
                                batch   = row.get("BatchNumber", "") or ""
                                qty     = float(row.get("Quantity") or 0)
                                if item_id and batch and qty > 0:
                                    lot_qty[item_id][batch] += sign * qty
                                    if item_id not in item_info:
                                        item_info[item_id] = {
                                            "ItemName": row.get("ItemName") or (row.get("Item") or {}).get("Name", ""),
                                            "UnitOfMeasurement": row.get("UnitOfMeasurement", "kg"),
                                        }
                        except Exception: continue
                    total   = data.get("TotalRows", 0)
                    fetched = (page - 1) * 50 + len(data.get("Rows", []))
                    if fetched >= total: break
                    page += 1
                except Exception: break

        result = []
        for item_id, batches in lot_qty.items():
            info = item_info.get(item_id, {})
            for batch, qty in batches.items():
                if qty > 0.001:
                    result.append({
                        "Item": {"ID": item_id}, "ItemName": info.get("ItemName", ""),
                        "ItemCode": "", "BatchNumber": batch,
                        "Quantity": round(qty, 4), "UnitOfMeasurement": info.get("UnitOfMeasurement", "kg"),
                    })
        return result

    def diagnose_lots(self, warehouse_id: int) -> dict:
        from datetime import datetime, timedelta
        date_from = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00")
        found = []
        for etype in ["P", "I"]:
            for subtype in ["S", "L", "P", "R"]:
                try:
                    data = self._get("/stockentry", params={
                        "StockEntryType": etype, "StockEntrySubtype": subtype,
                        "Status": "P", "DateFrom": date_from, "CurrentPage": 1, "PageSize": 5,
                    })
                    for row in data.get("Rows", [])[:1]:
                        eid = row.get("StockEntryId")
                        if eid:
                            for r in (self.get_entry_detail(eid).get("StockEntryRows") or []):
                                if r.get("BatchNumber"):
                                    found.append({
                                        "type": f"{etype}/{subtype}", "batch": r.get("BatchNumber"),
                                        "wh_from": (r.get("WarehouseFrom") or {}).get("ID"),
                                        "wh_to": (r.get("WarehouseTo") or {}).get("ID"),
                                        "our_wh": warehouse_id,
                                    })
                except Exception: pass
        return {"found": found, "warehouse_id": warehouse_id}

    def get_item_units(self, item_ids: list[int]) -> dict[int, str]:
        result = {}
        try:
            page = 1
            while True:
                data = self._get("/items/itemsdata", params={"CurrentPage": page, "PageSize": 500})
                rows = data.get("Rows", []) if isinstance(data, dict) else data
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
        return self._get("/warehouses", params={"CurrentPage": 1, "PageSize": 100}).get("Rows", [])

    def update_entry_with_lots(self, entry_id: int, entry_data: dict, new_rows: list[dict]) -> dict:
        api_rows = []
        for r in new_rows:
            row = {"Item": {"ID": r["article_id"]}, "Quantity": r["quantity_assigned"], "Note": r.get("opis", "") or ""}
            if r.get("lot"):                       row["BatchNumber"]       = r["lot"]
            if r.get("selling_price") is not None: row["Price"]             = r["selling_price"]
            if r.get("unit"):                      row["UnitOfMeasurement"] = r["unit"]
            api_rows.append(row)
        return self._put(f"/stockentry/{entry_id}", {**entry_data, "StockEntryItems": api_rows})


# ── Pretvorba ─────────────────────────────────────────────────────────────────

def parse_stock_to_engine_format(stock_rows: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in stock_rows:
        aid   = row.get("Item", {}).get("ID")
        batch = row.get("BatchNumber", "")
        qty   = float(row.get("Quantity") or 0)
        if not aid or qty <= 0: continue
        key = str(aid)
        if key not in result:
            result[key] = {"article_id": aid, "article_code": row.get("ItemCode", "") or "",
                           "article_name": row.get("ItemName", ""), "lots": []}
        if batch:
            result[key]["lots"].append({"code": batch, "quantity": qty,
                                        "unit": row.get("UnitOfMeasurement") or row.get("Unit") or ""})
    return result


def parse_entry_to_lines(entry_detail: dict, item_units: dict = None) -> list[dict]:
    lines = []
    for i, item in enumerate(entry_detail.get("StockEntryRows") or []):
        item_fk = item.get("Item") or {}
        item_id = item_fk.get("ID")
        unit    = (item.get("UnitOfMeasurement") or item.get("Unit") or
                   (item_units.get(item_id) if item_units and item_id else None) or "")
        lines.append({
            "row_id": i, "stock_entry_row_id": item.get("StockEntryRowId"),
            "article_id": item_id,
            "article_code": item.get("ItemCode", "") or item_fk.get("Code", "") or str(item_id or ""),
            "article_name": item.get("ItemName", "") or item_fk.get("Name", ""),
            "quantity": float(item.get("Quantity") or 0), "unit": unit,
            "selling_price": item.get("SellingPrice") or item.get("Price"),
            "lot": item.get("BatchNumber", "") or "",
            "opis": item.get("SerialNumber", "") or "",
            "row_version": item.get("RowVersion", ""),
        })
    return lines
