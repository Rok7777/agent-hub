Sporočite master chatu:

Za minimax_client.py — popravi get_stock_for_items po originalni zasnovi:
pythondef get_stock_for_items(self, warehouse_id, item_ids):
    from collections import defaultdict
    from datetime import datetime, timedelta

    # Korak 1: Dejanska zaloga iz /stocks (točna, ground truth)
    actual_qty = defaultdict(float)   # {item_id: skupna_qty}
    actual_info = {}                  # {item_id: {ItemName, UnitOfMeasurement}}
    try:
        for row in self.get_stock_by_lots(warehouse_id):
            aid = (row.get("Item") or {}).get("ID")
            qty = float(row.get("Quantity") or 0)
            if aid and qty > 0:
                actual_qty[aid] += qty
                if aid not in actual_info:
                    actual_info[aid] = {
                        "ItemName": row.get("ItemName", ""),
                        "UnitOfMeasurement": row.get("UnitOfMeasurement", "kg"),
                    }
    except Exception:
        pass

    # Korak 2: Loti in NC iz P/L prenosnih dokumentov
    lot_list  = defaultdict(list)   # {item_id: [{code, date, qty, price}]}
    date_from = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%dT00:00:00")

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

    page = 1
    while True:
        try:
            data = self._get("/stockentry", params={
                "StockEntryType": "P", "StockEntrySubtype": "L",
                "Status": "P", "DateFrom": date_from,
                "CurrentPage": page, "PageSize": 50,
            })
            rows = data.get("Rows", [])
            for entry in rows:
                eid = entry.get("StockEntryId")
                if not eid: continue
                try:
                    detail = self.get_entry_detail(eid)
                    for row in (detail.get("StockEntryRows") or []):
                        wh_to = (row.get("WarehouseTo") or {}).get("ID")
                        if str(wh_to) != str(numeric_wh_id): continue
                        item_id = (row.get("Item") or {}).get("ID")
                        batch   = row.get("BatchNumber", "") or ""
                        qty     = float(row.get("Quantity") or 0)
                        price   = float(row.get("Price") or 0)
                        if item_id and batch and qty > 0:
                            lot_list[item_id].append({
                                "code":  batch,
                                "qty":   qty,
                                "price": price,
                            })
                            if item_id not in actual_info:
                                actual_info[item_id] = {
                                    "ItemName": row.get("ItemName") or "",
                                    "UnitOfMeasurement": row.get("UnitOfMeasurement", "kg"),
                                }
                except Exception:
                    continue
            total   = data.get("TotalRows", 0)
            fetched = (page - 1) * 50 + len(rows)
            if fetched >= total: break
            page += 1
        except Exception:
            break

    # Korak 3: FIFO porazdelitev dejanske zaloge na lote
    result = []
    for item_id, total_qty in actual_qty.items():
        lots = lot_list.get(item_id, [])
        # Sortiraj po datumu (najstarejši prvi — FIFO)
        from lot_engine import parse_lot_date
        lots_sorted = sorted(lots, key=lambda x: parse_lot_date(x["code"]) or datetime(2099,1,1))
        remaining = total_qty
        info = actual_info.get(item_id, {})
        for lot in lots_sorted:
            if remaining <= 0: break
            use = round(min(lot["qty"], remaining), 4)
            result.append({
                "Item":              {"ID": item_id},
                "ItemName":          info.get("ItemName", ""),
                "ItemCode":          "",
                "BatchNumber":       lot["code"],
                "Quantity":          use,
                "UnitOfMeasurement": info.get("UnitOfMeasurement", "kg"),
                "Price":             lot["price"],
            })
            remaining = round(remaining - use, 4)
    return result
Logika:

/stocks = točna dejanska zaloga (ground truth, ni odvisna od smart match)
P/L = samo za lote in NC
FIFO porazdeli zalogo iz /stocks na lote iz P/L
I/S dokumenti se ne berejo več
