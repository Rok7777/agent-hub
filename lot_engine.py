"""
Lot assignment engine — FIFO + smart matching za ribje artikle.
"""

from datetime import datetime, timedelta
from typing import Optional
import re


# ─── Lot date parsing ─────────────────────────────────────────────────────────

def parse_lot_date(lot_code: str) -> Optional[datetime]:
    """
    Zadnjih 6 znakov lota je vedno DDMMYY.
    Primer: PR300326 → 30/03/2026, FP271125 → 27/11/2025
    """
    if not lot_code or len(lot_code) < 6:
        return None
    try:
        return datetime.strptime(lot_code[-6:], "%d%m%y")
    except ValueError:
        return None


# ─── Pogoji svežosti artikla ──────────────────────────────────────────────────

_FRESH_RE = re.compile('sve[žz]|sveži|svežih|svežim|bakala', re.IGNORECASE)
_DELI_RE  = re.compile(r'^\(deli', re.IGNORECASE)
_FROZEN_RE = re.compile(r'zamrznjen|odtaljen', re.IGNORECASE)

_SEAFOOD_RE = re.compile(
    'brancin|orada|losos|postrv|sard|oslič|oslic|huj|tun|lignji|kozice|'
    'skampi|škampi|klapavice|ostrig|hobotnica|sipa|lubin|kovac|kovač|'
    'šur|platesa|trska|polenovka|bakala|zobatec|špar|kirnja|arbun|morsk|'
    'som|lubin|romb|skuš|inčun|pic|mugilid|'
    'pokrovač|kočic',
    re.IGNORECASE
)
_MAQFINO_RE   = re.compile(r'maQfino', re.IGNORECASE)
_TESTENINE_RE = re.compile(r'testenin', re.IGNORECASE)
_V_OLJU_RE    = re.compile(r'v olju', re.IGNORECASE)
_MARINIRAN_RE = re.compile(r'mariniran', re.IGNORECASE)
_IZVLECEK_RE  = re.compile(r'izvle[cč]ek', re.IGNORECASE)
_KAVIAR_RE    = re.compile(r'kaviar', re.IGNORECASE)

def is_seafood(name: str) -> bool:
    """Vrne True če je artikel riba ali morska hrana."""
    return bool(_SEAFOOD_RE.search(name))

def is_fresh_or_deli(name: str) -> bool:
    """Vrne True če artikel zahteva 14-dnevno mejo lotov (sveže ribe + kaviar)."""
    return bool(_DELI_RE.search(name) or _FRESH_RE.search(name) or _KAVIAR_RE.search(name))

def get_lot_warning_days(name: str) -> int:
    if is_fresh_or_deli(name):
        return 10
    if _FROZEN_RE.search(name):
        return 330
    if _MAQFINO_RE.search(name):
        return 150
    if _MARINIRAN_RE.search(name):
        return 180
    if _V_OLJU_RE.search(name):
        return 365
    if _IZVLECEK_RE.search(name):
        return 365
    if _TESTENINE_RE.search(name):
        return 1095
    return 0


# ─── Kalo faktor ─────────────────────────────────────────────────────────────

_SARDELA_RE = re.compile('sard', re.IGNORECASE)
_LOSOS_RE   = re.compile('losos', re.IGNORECASE)
_TRIM_RE    = re.compile('trim', re.IGNORECASE)

KALO_FACTOR = 1.10

_LOSOSOVA_RE = re.compile(r'lososov', re.IGNORECASE)

def get_kalo_factor(article_name: str) -> float:
    return 1.0


# ─── Opozorilo starih lotov ───────────────────────────────────────────────────

def check_old_lots(stock: dict, today: datetime, article_ids: set = None, article_dates: dict = None) -> list[dict]:
    warnings = []
    for key, data in stock.items():
        art_name  = data.get('article_name', key)
        if article_ids is not None:
            art_id = data.get('article_id')
            if art_id not in article_ids:
                continue
        threshold = get_lot_warning_days(art_name)
        if threshold == 0:
            continue

        art_id   = data.get('article_id')
        ref_date = (article_dates.get(art_id) if article_dates and art_id else None) or today

        for lot in data.get('lots', []):
            if lot.get('quantity', 0) <= 0:
                continue
            lot_date = parse_lot_date(lot['code'])
            if lot_date is None:
                continue
            days_old = (ref_date - lot_date).days
            if days_old >= threshold:
                warnings.append({
                    'article':  art_name,
                    'lot':      lot['code'],
                    'days_old': days_old,
                    'qty':      round(lot['quantity'], 3),
                    'unit':     lot.get('unit', 'kg'),
                    'warning':  f"Lot star {days_old} dni (opozorilo pri {threshold} dneh)",
                })
    warnings.sort(key=lambda x: x['days_old'], reverse=True)
    return warnings


# ─── Filtriranje lotov (FIFO) ─────────────────────────────────────────────────

def get_eligible_lots(lots: list[dict], article_name: str, today: datetime) -> list[dict]:
    needs_14d = is_fresh_or_deli(article_name)

    result = []
    for lot in lots:
        if lot.get('quantity', 0) <= 0:
            continue
        d = parse_lot_date(lot['code'])
        if d is None:
            result.append({**lot, '_date': datetime(2099, 1, 1), '_aged': False})
            continue
        if d > today:
            continue
        days = (today - d).days
        if needs_14d and days > 30:
            continue
        result.append({**lot, '_date': d, '_aged': bool(needs_14d and 16 <= days <= 30), 'lot_price': lot.get('lot_price', lot.get('price', 0))})

    result.sort(key=lambda x: x['_date'])
    return result


# ─── Smart matching ───────────────────────────────────────────────────────────

_CODE_RE   = re.compile(r'^\(([^)]+)\)\s*')
_FILLET_RE = re.compile(r'\bfil[ei]', re.IGNORECASE)

_SIZE_G = [
    (0,100),(100,200),(200,300),(300,400),(400,600),
    (600,800),(800,1000),(1000,1500),(1500,2000),
    (2000,3000),(3000,5000),(5000,10000)
]
_SIZE_KG = [
    (0,1),(1,2),(2,3),(3,4),(4,5),(5,7),(7,10),(10,20),(20,50)
]
_SIZE_COUNT = [
    (1,5),(5,10),(10,20),(20,40),(40,80),(80,120),(120,200)
]

_ORIGINS = [
    'HRVAŠKA','GRČIJA','NORVEŠKA','TURČIJA','ŠPANIJA','ITALIJA',
    'PORTUGAL','MAROKO','PERU','VIETNAM','INDIJA','INDONEZIJA',
    'FILIPINI','TAJSKA','SLOVENIJA','FRANCIJA','DANSKA','ŠKOTSKA',
]

def _get_code(name: str) -> Optional[str]:
    m = _CODE_RE.match(name.strip())
    return m.group(1) if m else None

def _strip_code(name: str) -> str:
    return _CODE_RE.sub('', name).strip()

_LOSOSOVA_SPEC_RE = re.compile(r'lososov', re.IGNORECASE)

def _get_species(name: str) -> Optional[str]:
    clean = _strip_code(name).upper()
    if _LOSOSOVA_SPEC_RE.search(clean):
        return "LOSOSOVA POSTRV"
    seg = re.split(r'[,\(]', clean)[0].strip()
    return seg if seg else None

def _has_fillet(name: str) -> bool:
    return bool(_FILLET_RE.search(name))

def _get_size(name: str) -> Optional[tuple]:
    m = re.search(r'(\d+)[–\-](\d+)\s*(g|kg)?', name, re.IGNORECASE)
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    unit = (m.group(3) or '').lower()
    return (lo, hi, unit)

def _size_distance(s1: Optional[tuple], s2: Optional[tuple]) -> int:
    if s1 is None or s2 is None:
        return 3
    lo1, hi1, u1 = s1
    lo2, hi2, u2 = s2
    if u1 == 'kg': lo1, hi1, u1 = lo1*1000, hi1*1000, 'g'
    if u2 == 'kg': lo2, hi2, u2 = lo2*1000, hi2*1000, 'g'
    if not u1 and not u2 and lo1 < 200 and lo2 < 200:
        seq = _SIZE_COUNT
    else:
        seq = _SIZE_G

    def idx(lo, hi):
        for i, (slo, shi) in enumerate(seq):
            if slo <= lo and hi <= shi * 1.5:
                return i
        best_i, best_d = 0, float('inf')
        for i, (slo, shi) in enumerate(seq):
            d = abs(lo - slo)
            if d < best_d:
                best_d, best_i = d, i
        return best_i

    i1, i2 = idx(lo1, hi1), idx(lo2, hi2)
    return abs(i1 - i2)

def _get_origin(name: str) -> Optional[str]:
    nu = name.upper()
    for o in _ORIGINS:
        if o in nu:
            return o
    m = re.search(r'FAO\s*\d+', nu)
    return m.group(0) if m else None


def smart_match(
    sold_name: str,
    available: dict[str, list[dict]],
    unit: str
) -> tuple[Optional[str], str]:
    sold_sp     = _get_species(sold_name)
    sold_fillet = _has_fillet(sold_name)
    sold_size   = _get_size(sold_name)
    sold_origin = _get_origin(sold_name)
    sold_code   = _get_code(sold_name)

    if not sold_sp:
        return None, "vrsta ni določena"

    def has_stock(n):
        return any(l.get('quantity',0) > 0 for l in available.get(n, []))

    candidates = [
        n for n in available
        if _get_species(n) == sold_sp and has_stock(n)
    ]
    if not candidates and "LOSOSOVA POSTRV" in (sold_sp or ""):
        candidates = [
            n for n in available
            if "POSTRV" in (_get_species(n) or "").upper() and has_stock(n)
        ]
    if not candidates:
        return None, f"ni zaloge za {sold_sp}"

    _OCISCEN_RE = re.compile(r'oči[sš][cč]en', re.IGNORECASE)
    sold_ociscen = bool(_OCISCEN_RE.search(sold_name))

    if sold_fillet:
        fillet_cands = [n for n in candidates if _has_fillet(n)]
        if not fillet_cands:
            fillet_cands = [n for n in candidates if _OCISCEN_RE.search(n)]
        if not fillet_cands:
            fillet_cands = candidates
        candidates = fillet_cands
    elif sold_ociscen:
        ociscen_cands = [n for n in candidates if _OCISCEN_RE.search(n)]
        if not ociscen_cands:
            ociscen_cands = [n for n in candidates if not _has_fillet(n)]
        if not ociscen_cands:
            ociscen_cands = candidates
        candidates = ociscen_cands
    else:
        basic_cands = [n for n in candidates if not _has_fillet(n) and not _OCISCEN_RE.search(n)]
        candidates = basic_cands if basic_cands else candidates

    if not candidates:
        return None, f"ni ustreznega artikla za {sold_sp}"

    def score(n):
        size_dist = _size_distance(sold_size, _get_size(n))
        s = -size_dist * 10
        art_origin = _get_origin(n)
        if sold_origin and art_origin:
            s += 3 if art_origin == sold_origin else 0
        return s

    best = max(candidates, key=score)
    best_code = _get_code(best) or '?'
    sc = sold_code or '?'
    return best, f"({sc})→({best_code})"


# ─── Glavna funkcija dodelitve lotov ─────────────────────────────────────────

def assign_lots(
    document_lines: list[dict],
    stock: dict[str, dict],
    today: datetime
) -> list[dict]:
    by_id   = {str(v['article_id']): k for k, v in stock.items() if v.get('article_id')}
    by_code = {v['article_code']: k for k, v in stock.items() if v.get('article_code')}
    by_name = {v.get('article_name',''): k for k, v in stock.items()}
    by_name_ci = {v.get('article_name','').strip().lower(): k for k, v in stock.items()}

    virtual: dict[str, list[dict]] = {
        key: [lot.copy() for lot in data['lots']]
        for key, data in stock.items()
    }

    output = []

    for line in document_lines:
        art_id     = str(line.get('article_id') or '')
        art_code   = line.get('article_code', '')
        art_name   = line.get('article_name', '')
        qty_needed = round(float(line['quantity']), 4)
        unit       = line['unit']
        base_opis  = (line.get('opis') or '').strip()

        matched_note = ''

        kalo = get_kalo_factor(art_name)
        if kalo != 1.0:
            qty_needed = round(qty_needed * kalo, 4)

        stock_key = (by_id.get(art_id) or by_code.get(art_code) or
                     by_name.get(art_name) or by_name_ci.get(art_name.strip().lower()))

        has_vstock = (
            stock_key is not None and
            any(l.get('quantity',0) > 0 for l in virtual.get(stock_key, []))
        )

        if not has_vstock:
            avail_with_stock = {}
            for k, lots in virtual.items():
                if any(l.get('quantity',0) > 0 for l in lots):
                    sname = stock[k].get('article_name', k)
                    avail_with_stock[sname] = lots
            matched_name, note = smart_match(art_name, avail_with_stock, unit)
            if matched_name is None:
                output.append({**line,
                    'lot': None, 'quantity_assigned': qty_needed,
                    'opis': f"{base_opis} [brez lota: {note}]".strip(),
                    'status': 'no_match'})
                continue
            stock_key    = by_name.get(matched_name) or matched_name
            matched_note = note

        eligible = get_eligible_lots(virtual.get(stock_key, []), name_for_check, today)
        eligible = get_eligible_lots(virtual.get(stock_key, []), check_name, today)

        if not eligible:
            output.append({**line,
                'lot': None, 'quantity_assigned': qty_needed,
                'opis': f"{base_opis} [brez lota: ni ustreznih lotov]".strip(),
                'status': 'no_lots'})
            continue

        remaining   = qty_needed
        fresh_art   = is_fresh_or_deli(name_for_check)
        fresh_art   = is_fresh_or_deli(name_for_check)

        for lot in eligible:
            avail = round(lot['quantity'], 4)
            if avail <= 0:
                continue

            if lot.get('_aged') and fresh_art:
                lot_date = parse_lot_date(lot['code'])
                days_old = (today - lot_date).days if lot_date else 0
                use_sale = round(min(avail, remaining), 4)
                if use_sale > 0:
                    assignments.append((lot['code'], use_sale, 0, False, lot.get('lot_price', 0)))
                    remaining = round(remaining - use_sale, 4)
                writeoff = round(avail - use_sale, 4)
                if writeoff > 0:
                    assignments.append((lot['code'], writeoff, days_old, True, lot.get('lot_price', 0)))
                for vl in virtual[stock_key]:
                    if vl['code'] == lot['code']:
                        vl['quantity'] = 0.0
                        break
            else:
                if remaining <= 0:
                    break
                use = round(min(avail, remaining), 4)
                assignments.append((lot['code'], use, 0, False, lot.get('lot_price', 0)))
                remaining = round(remaining - use, 4)
                for vl in virtual[stock_key]:
                    if vl['code'] == lot['code']:
                        vl['quantity'] = round(vl['quantity'] - use, 4)
                        break

        opis = base_opis
        if matched_note:
            opis = (opis + ' ' + matched_note).strip() if opis else matched_note

        stock_data = stock.get(stock_key, {})
        for entry in assignments:
            lot_code, qty, forced_days = entry[0], entry[1], entry[2]
            is_writeoff = entry[3] if len(entry) > 3 else False
            lp = entry[4] if len(entry) > 4 else 0
            lot_opis = opis
            if forced_days > 0:
                lot_opis = (lot_opis + f' [odpis lota - star {forced_days} dni]').strip()
            output.append({
                **line,
                'article_id':   stock_data.get('article_id', line.get('article_id')),
                'article_code': stock_data.get('article_code', art_code),
                'article_name': stock_data.get('article_name', art_name),
                'lot':          lot_code,
                'quantity_assigned': qty,
                'opis':         lot_opis,
                'status':       'writeoff' if is_writeoff else ('matched' if matched_note else 'ok'),
                '_writeoff':    is_writeoff,
                '_writeoff_qty': qty if is_writeoff else 0,
                '_sale_qty':     qty if not is_writeoff else 0,
                'lot_price':    lp,
            })

        if remaining > 0:
            output.append({**line,
                'article_id':   stock_data.get('article_id', line.get('article_id')),
                'article_code': stock_data.get('article_code', art_code),
                'article_name': stock_data.get('article_name', art_name),
                'lot':  None,
                'quantity_assigned': remaining,
                'opis': (opis + ' [brez lota: premalo zaloge]').strip(),
                'status': 'partial',
                '_writeoff': False,
            })

    return _merge_lot_lines(output)

def _merge_lot_lines(lines: list[dict]) -> list[dict]:
    result = []
    seen   = {}
    for line in lines:
        key = (line.get('row_id', 0), line.get('article_code',''), line.get('lot'))
        if key not in seen:
            seen[key] = len(result)
            result.append({**line})
        else:
            existing = result[seen[key]]
            existing['quantity_assigned'] = round(
                existing['quantity_assigned'] + line['quantity_assigned'], 4
            )
            existing['_sale_qty']    = round(existing.get('_sale_qty', 0) + line.get('_sale_qty', 0), 4)
            existing['_writeoff_qty']= round(existing.get('_writeoff_qty', 0) + line.get('_writeoff_qty', 0), 4)
            if line.get('_writeoff') and line.get('opis'):
                existing['_writeoff_opis'] = line['opis']
            existing['_writeoff'] = False
            existing['status']    = 'ok' if existing.get('status') in ('ok','writeoff') else existing.get('status','ok')
    import re as _re
    for row in result:
        wo  = row.get('_writeoff_qty', 0)
        sal = row.get('_sale_qty', 0)
        if wo > 0 and sal > 0:
            wo_opis = row.get('_writeoff_opis', '')
            m = _re.search(r'star (\d+) dni', wo_opis)
            dni = m.group(1) if m else '?'
            base = (row.get('opis') or '').strip()
            row['opis'] = (base + f' [prodaja {sal}kg + odpis {wo}kg, lot star {dni} dni]').strip()
    return result


def assign_lots_with_virtual(
    document_lines: list[dict],
    stock: dict[str, dict],
    virtual: dict[str, list[dict]],
    today: datetime
) -> list[dict]:
    """
    Kot assign_lots ampak sprejme zunanjo virtual zalogo.
    Omogoča skupno obdelavo več dokumentov z deljeno virtualno zalogo.
    """
    by_id   = {str(v['article_id']): k for k, v in stock.items() if v.get('article_id')}
    by_code = {v['article_code']: k for k, v in stock.items() if v.get('article_code')}
    by_name = {v.get('article_name',''): k for k, v in stock.items()}
    by_name_ci = {v.get('article_name','').strip().lower(): k for k, v in stock.items()}
    output  = []

    for line in document_lines:
        art_id     = str(line.get('article_id') or '')
        art_code   = line.get('article_code', '')
        art_name   = line.get('article_name', '')
        qty_needed = round(float(line['quantity']), 4)
        unit       = line['unit']
        base_opis  = (line.get('opis') or '').strip()
        matched_note = ''

        kalo = get_kalo_factor(art_name)
        if kalo != 1.0:
            qty_needed = round(qty_needed * kalo, 4)

        stock_key = (by_id.get(art_id) or by_code.get(art_code) or
                     by_name.get(art_name) or by_name_ci.get(art_name.strip().lower()))
        has_vstock = (stock_key is not None and
                      any(l.get('quantity',0) > 0 for l in virtual.get(stock_key, [])))

        if not has_vstock:
            avail_with_stock = {}
            for k, lots in virtual.items():
                if any(l.get('quantity',0) > 0 for l in lots):
                    sname = stock[k].get('article_name', k)
                    avail_with_stock[sname] = lots
            matched_name, note = smart_match(art_name, avail_with_stock, unit)
            if matched_name is None:
                output.append({**line, 'lot': None, 'quantity_assigned': qty_needed,
                    'opis': f"{base_opis} [brez lota: {note}]".strip(), 'status': 'no_match'})
                continue
            stock_key    = by_name.get(matched_name) or matched_name
            matched_note = note

        name_for_check = art_name if not matched_note else stock.get(stock_key, {}).get('article_name', art_name)
        eligible = get_eligible_lots(virtual.get(stock_key, []), name_for_check, today)

        if not eligible:
            avail_sm = {}
            for k, lots in virtual.items():
                if any(l.get('quantity', 0) > 0 for l in lots):
                    sname = stock[k].get('article_name', k)
                    if sname != art_name:
                        avail_sm[sname] = lots
            matched_sm, note_sm = smart_match(art_name, avail_sm, unit)
            if matched_sm:
                stock_key    = by_name.get(matched_sm) or matched_sm
                matched_note = note_sm
                eligible     = get_eligible_lots(virtual.get(stock_key, []), matched_sm, today)
            if not eligible:
                output.append({**line, 'lot': None, 'quantity_assigned': qty_needed,
                    'opis': f"{base_opis} [brez lota: ni ustreznih lotov]".strip(),
                    'status': 'no_lots', '_writeoff': False})
                continue

        remaining  = qty_needed
        assignments = []
        fresh_art   = is_fresh_or_deli(name_for_check)

        for lot in eligible:
            avail = round(lot['quantity'], 4)
            if avail <= 0:
                continue

            if lot.get('_aged') and fresh_art:
                lot_date = parse_lot_date(lot['code'])
                days_old = (today - lot_date).days if lot_date else 0
                use_sale = round(min(avail, remaining), 4)
                if use_sale > 0:
                    assignments.append((lot['code'], use_sale, 0, False, lot.get('lot_price', 0)))
                    remaining = round(remaining - use_sale, 4)
                writeoff = round(avail - use_sale, 4)
                if writeoff > 0:
                    assignments.append((lot['code'], writeoff, days_old, True, lot.get('lot_price', 0)))
                for vl in virtual[stock_key]:
                    if vl['code'] == lot['code']:
                        vl['quantity'] = 0.0
                        break
            else:
                if remaining <= 0:
                    break
                use = round(min(avail, remaining), 4)
                assignments.append((lot['code'], use, 0, False, lot.get('lot_price', 0)))
                remaining = round(remaining - use, 4)
                for vl in virtual[stock_key]:
                    if vl['code'] == lot['code']:
                        vl['quantity'] = round(vl['quantity'] - use, 4)
                        break

        opis = base_opis
        if matched_note:
            opis = (opis + ' ' + matched_note).strip() if opis else matched_note

        stock_data = stock.get(stock_key, {})
        for entry in assignments:
            lot_code, qty, forced_days = entry[0], entry[1], entry[2]
            is_writeoff = entry[3] if len(entry) > 3 else False
            lp = entry[4] if len(entry) > 4 else 0
            lot_opis = opis
            if forced_days > 0:
                lot_opis = (lot_opis + f' [odpis lota - star {forced_days} dni]').strip()
            output.append({
                **line,
                'article_id':   stock_data.get('article_id', line.get('article_id')),
                'article_code': stock_data.get('article_code', art_code),
                'article_name': stock_data.get('article_name', art_name),
                'lot':          lot_code,
                'quantity_assigned': qty,
                'opis':         lot_opis,
                'status':       'writeoff' if is_writeoff else ('matched' if matched_note else 'ok'),
                '_writeoff':    is_writeoff,
                '_writeoff_qty': qty if is_writeoff else 0,
                '_sale_qty':     qty if not is_writeoff else 0,
                'lot_price':    lp,
            })

        if remaining > 0:
            tried_keys = {stock_key}
            rem_remaining = remaining

            while rem_remaining > 0:
                avail_for_remainder = {}
                for k, lots in virtual.items():
                    if k in tried_keys:
                        continue
                    if any(l.get('quantity', 0) > 0 for l in lots):
                        sname = stock[k].get('article_name', k)
                        avail_for_remainder[sname] = lots

                if not avail_for_remainder:
                    break

                matched_rem, note_rem = smart_match(art_name, avail_for_remainder, unit)
                rem_stock_key_candidate = by_name.get(matched_rem) or matched_rem

                if not matched_rem or rem_stock_key_candidate in tried_keys:
                    break

                tried_keys.add(rem_stock_key_candidate)
                rem_stock_key  = rem_stock_key_candidate
                rem_eligible   = get_eligible_lots(virtual.get(rem_stock_key, []), matched_rem, today)
                rem_stock_data = stock.get(rem_stock_key, {})

                if not rem_eligible:
                    continue

                for lot in rem_eligible:
                    if rem_remaining <= 0:
                        break
                    avail = round(lot['quantity'], 4)
                    if avail <= 0:
                        continue
                    use_lot = round(min(avail, rem_remaining), 4)
                    use_qty = rem_remaining
                    lot_shortfall = round(rem_remaining - use_lot, 4)
                    rem_opis = (opis + f' {note_rem} [zamenjava za razliko]').strip()
                    if lot_shortfall > 0:
                        rem_opis = (rem_opis + f' [lot pokrije {use_lot}{unit}, manjka {lot_shortfall}{unit}]').strip()
                    output.append({**line,
                        'article_id':        rem_stock_data.get('article_id', line.get('article_id')),
                        'article_code':      rem_stock_data.get('article_code', art_code),
                        'article_name':      rem_stock_data.get('article_name', art_name),
                        'lot':               lot['code'],
                        'quantity_assigned': use_qty,
                        'opis':              rem_opis,
                        'status':            'matched' if lot_shortfall == 0 else 'partial',
                        '_writeoff':         False,
                        'lot_price':         lot.get('lot_price', 0),
                    })
                    rem_remaining = round(rem_remaining - use_lot, 4)
                    for vl in virtual[rem_stock_key]:
                        if vl['code'] == lot['code']:
                            vl['quantity'] = round(vl['quantity'] - use_lot, 4)
                            break

            if rem_remaining > 0:
                output.append({**line,
                    'article_id':   stock_data.get('article_id', line.get('article_id')),
                    'article_code': stock_data.get('article_code', art_code),
                    'article_name': stock_data.get('article_name', art_name),
                    'lot': None, 'quantity_assigned': rem_remaining,
                    'opis': (opis + ' [brez lota: premalo zaloge]').strip(),
                    'status': 'partial', '_writeoff': False,
                })

    return _merge_lot_lines(output)
