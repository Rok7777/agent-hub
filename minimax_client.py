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
        ResultsByBatchNumber=Y → razdeli po serijah.
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
    { article_name: { 'article_id': int, 'article_code': str, 'lots': [...] } }
    """
    result: dict[str, dict] = {}
    for row in stock_rows:
        name  = row.get("ItemName", "")
        code  = row.get("ItemCode", "")
        aid   = row.get("Item", {}).get("ID")
        batch = row.get("BatchNumber", "")
        qty   = float(row.get("Quantity") or 0)
        unit  = row.get("UnitOfMeasurement", "kg")

        if not name or qty <= 0:
            continue

        if name not in result:
            result[name] = {"article_id": aid, "article_code": code, "lots": []}

        if batch:
            result[name]["lots"].append({"code": batch, "quantity": qty, "unit": unit})

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
            "article_code":      item_fk.get("Code", "") or "",
            "article_name":      item.get("ItemName", "") or item_fk.get("Name", ""),
            "quantity":          float(item.get("Quantity") or 0),
            "unit":              item.get("UnitOfMeasurement", "kg") or "kg",
            "selling_price":     item.get("SellingPrice") or item.get("Price"),
            "lot":               item.get("BatchNumber", "") or "",
            "opis":              item.get("SerialNumber", "") or "",
            "row_version":       item.get("RowVersion", ""),
        })
    return lines
