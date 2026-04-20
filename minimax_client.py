"""
Minimax API odjemalec.
Dokumentacija: https://moj.minimax.si/SI/API
"""

import requests
from datetime import datetime
from typing import Optional


BASE     = "https://moj.minimax.si/SI/API"
AUTH_URL = "https://moj.minimax.si/SI/AUT/OAuth20/Token"

# Analitike → WarehouseCode mapping
LOCATIONS = {
    "MPK1": {"name": "Potujoča 1",        "analytic_name": "MPK1"},
    "MPK2": {"name": "Potujoča 2",        "analytic_name": "MPK2"},
    "MPK3": {"name": "Potujoča 3",        "analytic_name": "MPK3"},
    "MPOC": {"name": "Ribarnica Domžale", "analytic_name": "MPOC"},
}

# Mapping analitika šifra → naziv blagajne
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
        from datetime import timedelta
        self._token_expiry = datetime.now() + timedelta(seconds=int(data.get("expires_in", 3600)) - 60)
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
        r.raise_for_status()
        return r.json()

    # ── Journal (Temeljnice) ──────────────────────────────────────────────────

    def get_journal_drafts(self) -> list[dict]:
        """Vrne vse osnutke temeljnic - filtrira lokalno po statusu."""
        result = []
        page   = 1
        while True:
            data = self._get("/journals", params={
                "CurrentPage": page,
                "PageSize":    50,
            })
            rows = data.get("Rows", [])
            for row in rows:
                status = str(row.get("Status", "")).upper()
                if status in ("O", "DRAFT", "0", "OSNUTEK"):
                    result.append(row)
            total   = data.get("TotalRows", 0)
            fetched = (page - 1) * 50 + len(rows)
            if fetched >= total or not rows:
                break
            page += 1
        return result

    def get_journal(self, journal_id: int) -> dict:
        """Vrne posamezno temeljnico z vsemi knjižbami."""
        return self._get(f"/journals/{journal_id}")

    def update_journal(self, journal_id: int, journal_data: dict) -> dict:
        """Posodobi temeljnico (PUT)."""
        return self._put(f"/journals/{journal_id}", journal_data)

    def parse_journal_placila(self, journal: dict) -> dict | None:
        """
        Iz temeljnice izvleče podatke za blagajno:
        - datum, analitika, znesek gotovine (1000), znesek kartice (1652)
        - vrne None če ni ustreznih knjižb
        """
        entries = journal.get("JournalEntries", [])

        datum        = journal.get("JournalDate", "")[:10]
        journal_id   = journal.get("JournalId")
        row_version  = journal.get("RowVersion", "")

        data_1652 = None
        data_1000 = None

        for entry in entries:
            account = str(entry.get("Account", {}).get("ID", ""))
            analytic_obj = entry.get("Analytic") or {}
            analytic_code = analytic_obj.get("Code", "") or ""

            # Izvleči šifro blagajne (MPK1/MPK2/MPK3/MPOC)
            import re
            m = re.match(r"^(MPK\d+|MPOC)", analytic_code)
            sifra = m.group(1) if m else analytic_code.split(" ")[0] if analytic_code else ""

            debit  = float(entry.get("Debit", 0) or 0)
            credit = float(entry.get("Credit", 0) or 0)
            znesek = debit if debit > 0 else credit

            if account == "1652" and not data_1652:
                data_1652 = {
                    "entry_id":    entry.get("JournalEntryId"),
                    "analitika":   analytic_code,
                    "sifra":       sifra,
                    "znesek":      znesek,
                    "row_version": entry.get("RowVersion", ""),
                }
            elif account == "1000" and not data_1000:
                data_1000 = {
                    "entry_id":    entry.get("JournalEntryId"),
                    "analitika":   analytic_code,
                    "sifra":       sifra,
                    "znesek":      znesek,
                    "row_version": entry.get("RowVersion", ""),
                }

        if not data_1652 and not data_1000:
            return None

        an_polno = (data_1652 or data_1000)["analitika"]
        sifra    = (data_1652 or data_1000)["sifra"]

        znesek_kartica  = data_1652["znesek"] if data_1652 else 0.0
        znesek_gotovina = data_1000["znesek"] if data_1000 else 0.0
        skupaj = round(znesek_kartica + znesek_gotovina, 2)

        if data_1652 and data_1000:
            rezim = "oba"
        elif data_1652:
            rezim = "samo_kartica"
        else:
            rezim = "samo_gotovina"

        return {
            "journal_id":       journal_id,
            "datum":            datum,
            "analitika_sifra":  sifra,
            "analitika_polno":  an_polno,
            "blagajna_naziv":   BLAGAJNE.get(sifra, sifra),
            "znesek_kartica":   znesek_kartica,
            "znesek_gotovina":  znesek_gotovina,
            "skupaj":           skupaj,
            "rezim":            rezim,
            "row_version":      row_version,
            "entries":          entries,
            "journal_raw":      journal,
        }

    def popravi_in_potrdi_journal(self, podatki: dict) -> bool:
        """
        Popravi knjižbe 1652/1000 → 120000 in potrdi temeljnico.
        Vrne True če uspešno.
        """
        journal = podatki["journal_raw"]
        entries = journal.get("JournalEntries", [])

        # Poišči stranko "Končni kupec - maloprodaja"
        # Stranka mora biti objekt z ID-jem — poiščemo iz obstoječih vnosov
        stranka_obj = None
        for e in entries:
            s = e.get("Customer") or e.get("Supplier")
            if s and s.get("ID"):
                stranka_obj = s
                break

        # Če stranke ni v obstoječih vnosih, jo poiščemo
        if not stranka_obj:
            try:
                stranke = self._get("/customers", params={"Search": "Končni kupec", "PageSize": 10})
                for s in stranke.get("Rows", []):
                    if "končni kupec" in s.get("Name", "").lower():
                        stranka_obj = {"ID": s["CustomerID"]}
                        break
            except Exception:
                pass

        nove_entries = []
        entry_1652 = None
        entry_1000 = None

        for entry in entries:
            account = str(entry.get("Account", {}).get("ID", ""))
            if account == "1652":
                entry_1652 = entry
            elif account == "1000":
                entry_1000 = entry
            else:
                # Ostale knjižbe pustimo kot so
                nove_entries.append(entry)

        # Ustvari eno novo knjižbo 120000 z vsoto
        skupaj = podatki["skupaj"]
        analitika_id = None

        # Izvleci analitika ID iz obstoječe knjižbe
        ref_entry = entry_1652 or entry_1000
        if ref_entry:
            an = ref_entry.get("Analytic") or {}
            analitika_id = an.get("ID")

        nova_knjizba = {
            "Account":  {"ID": 120000},
            "Analytic": {"ID": analitika_id} if analitika_id else None,
            "Customer": stranka_obj,
            "Debit":    skupaj,
            "Credit":   0,
        }
        if ref_entry:
            # Ohrani datum in opis
            nova_knjizba["EntryDate"]   = ref_entry.get("EntryDate")
            nova_knjizba["Description"] = ref_entry.get("Description")

        nove_entries.append(nova_knjizba)

        # Posodobi journal objekt
        journal_update = {
            **journal,
            "Status":        "P",  # Potrdi
            "JournalEntries": nove_entries,
        }

        self.update_journal(podatki["journal_id"], journal_update)
        return True

    # ── Analitike ─────────────────────────────────────────────────────────────

    def get_analytics(self) -> list[dict]:
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
        rows = self.get_analytics()
        for row in rows:
            if row.get("Code", "").upper() == analytic_code.upper():
                return row.get("AnalyticId")
        return None

    # ── Osnutki dokumentov (zaloge) ───────────────────────────────────────────

    RETAIL_CUSTOMER = "končni kupec - maloprodaja"

    def get_draft_entries(self, analytic_id: int) -> list[dict]:
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
        from collections import defaultdict
        from datetime import datetime, timedelta

        item_info = {}
        try:
            base = self.get_stock_by_lots(warehouse_id)
            for r in base:
                aid = (r.get("Item") or {}).get("ID")
                if aid:
                    item_info[aid] = {
                        "ItemName": r.get("ItemName", ""),
                        "UnitOfMeasurement": r.get("UnitOfMeasurement", "kg"),
                    }
        except Exception:
            pass

        lot_qty = defaultdict(lambda: defaultdict(float))
        date_from = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00")
        for entry_type, subtype, sign in [("P", "L", 1.0), ("I", "S", -1.0)]:
            page = 1
            while True:
                try:
                    params = {
                        "StockEntryType": entry_type, "StockEntrySubtype": subtype,
                        "Status": "P", "DateFrom": date_from,
                        "CurrentPage": page, "PageSize": 50,
                    }
                    data = self._get("/stockentry", params=params)
                    rows = data.get("Rows", [])
                    for entry in rows:
                        eid = entry.get("StockEntryId")
                        if not eid:
                            continue
                        try:
                            detail = self.get_entry_detail(eid)
                            for row in (detail.get("StockEntryRows") or []):
                                wh_from = (row.get("WarehouseFrom") or {}).get("ID")
                                wh_to   = (row.get("WarehouseTo") or {}).get("ID")
                                if entry_type == "P" and wh_to != warehouse_id:
                                    continue
                                if entry_type == "I" and wh_from != warehouse_id:
                                    continue
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
                        except Exception:
                            continue
                    total   = data.get("TotalRows", 0)
                    fetched = (page - 1) * 50 + len(rows)
                    if fetched >= total:
                        break
                    page += 1
                except Exception:
                    break

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
                        "Status": "P", "DateFrom": date_from,
                        "CurrentPage": 1, "PageSize": 5,
                    })
                    rows = data.get("Rows", [])
                    if rows:
                        eid = rows[0].get("StockEntryId")
                        if eid:
                            detail = self.get_entry_detail(eid)
                            for r in (detail.get("StockEntryRows") or []):
                                batch = r.get("BatchNumber", "")
                                if batch:
                                    found.append({
                                        "type":    f"{etype}/{subtype}",
                                        "batch":   batch,
                                        "wh_from": (r.get("WarehouseFrom") or {}).get("ID"),
                                        "wh_to":   (r.get("WarehouseTo") or {}).get("ID"),
                                        "our_wh":  warehouse_id,
                                    })
                except Exception:
                    pass
        return {"found": found, "warehouse_id": warehouse_id}

    def get_item_units(self, item_ids: list[int]) -> dict[int, str]:
        result = {}
        try:
            page = 1
            while True:
                data = self._get("/items/itemsdata", params={"CurrentPage": page, "PageSize": 500})
                rows = data.get("Rows") or data if isinstance(data, list) else []
                if not rows and isinstance(data, dict):
                    rows = data.get("Rows", [])
                for row in rows:
                    aid  = row.get("ItemId") or (row.get("Item") or {}).get("ID")
                    unit = row.get("UnitOfMeasurement") or row.get("Unit") or ""
                    if aid and unit:
                        result[int(aid)] = unit
                total   = data.get("TotalRows", 0) if isinstance(data, dict) else 0
                fetched = (page - 1) * 500 + len(rows)
                if fetched >= total or not rows:
                    break
                page += 1
        except Exception:
            for item_id in item_ids:
                try:
                    d    = self._get(f"/items/{item_id}")
                    unit = d.get("UnitOfMeasurement") or d.get("Unit") or ""
                    if unit:
                        result[item_id] = unit
                except Exception:
                    continue
        return result

    def get_warehouses(self) -> list[dict]:
        data = self._get("/warehouses", params={"CurrentPage": 1, "PageSize": 100})
        return data.get("Rows", [])

    def update_entry_with_lots(self, entry_id: int, entry_data: dict, new_rows: list[dict]) -> dict:
        api_rows = []
        for r in new_rows:
            row = {
                "Item":     {"ID": r["article_id"]},
                "Quantity": r["quantity_assigned"],
                "Note":     r.get("opis", "") or "",
            }
            if r.get("lot"):
                row["BatchNumber"] = r["lot"]
            if r.get("selling_price") is not None:
                row["Price"] = r["selling_price"]
            if r.get("unit"):
                row["UnitOfMeasurement"] = r["unit"]
            api_rows.append(row)
        body = {**entry_data, "StockEntryItems": api_rows}
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
        if not aid or qty <= 0:
            continue
        key = str(aid)
        if key not in result:
            result[key] = {"article_id": aid, "article_code": code, "article_name": name, "lots": []}
        if batch:
            result[key]["lots"].append({"code": batch, "quantity": qty, "unit": unit})
    return result


def parse_entry_to_lines(entry_detail: dict, item_units: dict = None) -> list[dict]:
    rows  = entry_detail.get("StockEntryRows") or []
    lines = []
    for i, item in enumerate(rows):
        item_fk  = item.get("Item") or {}
        item_id  = item_fk.get("ID")
        unit = (item.get("UnitOfMeasurement") or item.get("Unit") or
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
