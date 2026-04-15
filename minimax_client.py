"""
Minimax API odjemalec.
Dokumentacija: https://moj.minimax.si/SI/API
"""

import requests
from datetime import datetime
from typing import Optional


BASE     = "https://moj.minimax.si/SI/API"
AUTH_URL = "https://moj.minimax.si/SI/AUT/OAuth20/Token"

# Analitike → WarehouseCode mapping (nastavi glede na vaš Minimax)
LOCATIONS = {
    "MPK1": {"name": "Potujoča 1",        "analytic_name": "MPK1"},
    "MPK2": {"name": "Potujoča 2",        "analytic_name": "MPK2"},
    "MPK3": {"name": "Potujoča 3",        "analytic_name": "MPK3"},
    "MPOC": {"name": "Ribarnica Domžale", "analytic_name": "MPOC"},
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
            raise Exception(
                f"Prijava neuspešna ({r.status_code}): {r.text[:300]}"
            )
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
        r.raise_for_status()
        return r.json()

    # ── Analitike ─────────────────────────────────────────────────────────────

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
        rows = self.get_analytics()
        for row in rows:
            if row.get("Code", "").upper() == analytic_code.upper():
                return row.get("AnalyticId")
        return None

    # ── Osnutki dokumentov ────────────────────────────────────────────────────

    # Samo dokumenti s to stranko so maloprodajni — vsi ostali so veleprodaja
    RETAIL_CUSTOMER = "končni kupec - maloprodaja"

    def get_draft_entries(self, analytic_id: int) -> list[dict]:
        """
        Vrne osnutke (Status=O) izdaj strank za dano analitiko.
        Filtrira SAMO dokumente s stranko "Končni kupec - maloprodaja"
        da ne obdelamo veleprodajnih dokumentov.
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
            # Varnostni filter: samo maloprodajni dokumenti
            for row in rows:
                customer_name = row.get("Customer", {}).get("Name", "")
                if self.RETAIL_CUSTOMER in customer_name.lower():
                    result.append(row)
            total = data.get("TotalRows", 0)
            fetched = (page - 1) * 50 + len(rows)
            if fetched >= total:
                break
            page += 1
        return result

    def get_entry_detail(self, entry_id: int) -> dict:
        """Vrne podrobnosti posameznega dokumenta (vrstice)."""
        return self._get(f"/stockentry/{entry_id}")

    # ── Zaloga po lotih ───────────────────────────────────────────────────────

    def get_stock_by_lots(self, warehouse_id: int) -> list[dict]:
        """
        Vrne zalogo po lotih za dano skladišče.
        Najprej poskusi ResultsByBatchNumber=Y za celotno skladišče.
        Če loti niso vrnjeni, jih poišče po posameznem artiklu.
        """
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

        # Baza za artikel info (ime, enota)
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

        lot_qty = defaultdict(lambda: defaultdict(float))  # {item_id: {batch: qty}}

        # 1. IL dokumenti — prenosi V to skladišče (subtype L = Storage)
        date_from = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00")
        for entry_type, subtype, sign in [
            ("P", "L", 1.0),   # Prejem iz skladišča = prenos v maloprodajo
            ("I", "S", -1.0),  # Potrjene prodaje (IS) = odbitek
        ]:
            page = 1
            while True:
                try:
                    params = {
                        "StockEntryType":    entry_type,
                        "StockEntrySubtype": subtype,
                        "Status":            "P",
                        "DateFrom":          date_from,
                        "CurrentPage":       page,
                        "PageSize":          50,
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
                                # Samo vrstice ki se nanašajo na naše skladišče
                                if entry_type == "P" and wh_to != warehouse_id:
                                    continue
                                if entry_type == "I" and wh_from != warehouse_id:
                                    continue
                                item_id = (row.get("Item") or {}).get("ID")
                                batch   = row.get("BatchNumber", "") or ""
                                qty     = float(row.get("Quantity") or 0)
                                if item_id and batch and qty > 0:
                                    lot_qty[item_id][batch] += sign * qty
                                    # Shrani info o artiklu
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

        # Sestavi rezultat
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

    def get_warehouses(self) -> list[dict]:
        """Vrne seznam skladišč za iskanje WarehouseId."""
        data = self._get("/warehouses", params={"CurrentPage": 1, "PageSize": 100})
        return data.get("Rows", [])

    # ── Shranjevanje dokumenta z loti ─────────────────────────────────────────

    def update_entry_with_lots(
        self,
        entry_id:    int,
        entry_data:  dict,
        new_rows:    list[dict]
    ) -> dict:
        """
        Posodobi dokument z dodelitvami lotov.
        new_rows: [{'article_id', 'quantity_assigned', 'lot', 'unit', 'selling_price', 'opis'}, ...]
        """
        # Zgradimo nove vrstice v formatu Minimax API
        api_rows = []
        for r in new_rows:
            row = {
                "Item":     {"ID": r["article_id"]},
                "Quantity": r["quantity_assigned"],
                "Note":     r.get("opis", "") or "",
            }
            if r.get("lot"):
                row["BatchNumber"] = r["lot"]
            # Ohrani ceno iz originalnega dokumenta
            if r.get("selling_price") is not None:
                row["Price"] = r["selling_price"]
            api_rows.append(row)

        body = {**entry_data, "StockEntryItems": api_rows}
        return self._put(f"/stockentry/{entry_id}", body)


# ── Pretvorba API odgovora v format za lot_engine ─────────────────────────────

def parse_stock_to_engine_format(stock_rows: list[dict]) -> dict[str, dict]:
    """
    Pretvori /stocks odgovor v format ki ga pričakuje assign_lots():
    Primarni ključ je article_id (int) za zanesljivo ujemanje.
    { article_name: { 'article_id': int, 'article_code': str, 'lots': [...] } }
    Hkrati gradi id_to_name mapo za hitro iskanje po ID.
    """
    result: dict[str, dict] = {}
    for row in stock_rows:
        name  = row.get("ItemName", "")
        code  = row.get("ItemCode", "") or ""
        aid   = row.get("Item", {}).get("ID")
        batch = row.get("BatchNumber", "")
        qty   = float(row.get("Quantity") or 0)
        unit  = row.get("UnitOfMeasurement", "kg")

        if not aid or qty <= 0:
            continue

        # Ključ je artikel ID pretvorjen v string za zanesljivo ujemanje
        key = str(aid)
        if key not in result:
            result[key] = {
                "article_id":   aid,
                "article_code": code,
                "article_name": name,
                "lots": []
            }

        if batch:
            result[key]["lots"].append({"code": batch, "quantity": qty, "unit": unit})

    return result


def parse_entry_to_lines(entry_detail: dict) -> list[dict]:
    """
    Pretvori /stockentry/{id} odgovor v seznam vrstic za assign_lots().
    Polja po API dokumentaciji StockEntryRow:
    Item (FK), ItemName, Quantity, Price, SellingPrice, BatchNumber, SerialNumber, Mass
    """
    rows = entry_detail.get("StockEntryRows") or []
    lines = []
    for i, item in enumerate(rows):
        item_fk   = item.get("Item") or {}
        lines.append({
            "row_id":            i,
            "stock_entry_row_id": item.get("StockEntryRowId"),
            "article_id":        item_fk.get("ID"),
            "article_code":      item.get("ItemCode", "") or item_fk.get("Code", "") or str(item_fk.get("ID", "")),
            "article_name":      item.get("ItemName", "") or item_fk.get("Name", ""),
            "quantity":          float(item.get("Quantity") or 0),
            "unit":              item.get("UnitOfMeasurement", "kg") or "kg",
            "selling_price":     item.get("SellingPrice") or item.get("Price"),
            "lot":               item.get("BatchNumber", "") or "",
            "opis":              item.get("SerialNumber", "") or "",
            "row_version":       item.get("RowVersion", ""),
        })
    return lines
