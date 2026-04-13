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

_FRESH_RE = re.compile(
    r'\bsve[žz][aeiou]?\b|\bsveži\b|\bsvežih\b|\bsvežim\b',
    re.IGNORECASE
)
_DELI_RE  = re.compile(r'^\(deli', re.IGNORECASE)
_FROZEN_RE = re.compile(
    r'\bzamrznjen[aoe]?\b|\bodtaljen[aoe]?\b',
    re.IGNORECASE
)

def is_fresh_or_deli(name: str) -> bool:
    """Vrne True če artikel zahteva mejo 14 dni za lote."""
    return bool(_DELI_RE.search(name) or _FRESH_RE.search(name))


# ─── Filtriranje lotov (FIFO) ─────────────────────────────────────────────────

def get_eligible_lots(lots: list[dict], article_name: str, today: datetime) -> list[dict]:
    """
    Vrne lote ustrezne za artikel, sortirane FIFO (najstarejši prvi).
    Vsak lot: {'code': str, 'quantity': float, 'unit': str}
    """
    needs_14d = is_fresh_or_deli(article_name)
    cutoff    = today - timedelta(days=14) if needs_14d else None

    result = []
    for lot in lots:
        if lot.get('quantity', 0) <= 0:
            continue
        d = parse_lot_date(lot['code'])
        if d is None:
            result.append({**lot, '_date': datetime(2099, 1, 1)})
            continue
        if cutoff and d < cutoff:
            continue
        result.append({**lot, '_date': d})

    result.sort(key=lambda x: x['_date'])
    return result


# ─── Smart matching — razčlenjevanje artiklov ─────────────────────────────────

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

def _get_species(name: str) -> Optional[str]:
    """Prva beseda po šifri (npr. BRANCIN, ORADA, LIGNJI ...)"""
    clean = _strip_code(name).upper()
    # vzami vse do prve vejice ali oklepaja
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
    # Normalizacija na grame
    if u1 == 'kg': lo1, hi1, u1 = lo1*1000, hi1*1000, 'g'
    if u2 == 'kg': lo2, hi2, u2 = lo2*1000, hi2*1000, 'g'
    # Kosi (škampi, kozice) — manjše vrednosti
    if not u1 and not u2 and lo1 < 200 and lo2 < 200:
        seq = _SIZE_COUNT
    elif lo1 >= 1000 or lo2 >= 1000:
        seq = _SIZE_KG
        lo1,hi1 = lo1/1000, hi1/1000
        lo2,hi2 = lo2/1000, hi2/1000
    else:
        seq = _SIZE_G

    def idx(lo, hi):
        for i,(slo,shi) in enumerate(seq):
            if slo <= lo and hi <= shi*1.5:
                return i
            if abs(lo-slo)<50:
                return i
        return None

    i1, i2 = idx(lo1,hi1), idx(lo2,hi2)
    if i1 is None or i2 is None:
        return 5 if abs(lo1-lo2)>300 else 1
    return abs(i1-i2)

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
    """
    Poišče najboljši dostopen artikel za prodan artikel.
    available: {article_name: [lots]}
    Vrne (matched_name, opis_notacija) ali (None, razlog)
    """
    sold_sp     = _get_species(sold_name)
    sold_fillet = _has_fillet(sold_name)
    sold_size   = _get_size(sold_name)
    sold_origin = _get_origin(sold_name)
    sold_code   = _get_code(sold_name)

    if not sold_sp:
        return None, "vrsta ni določena"

    def has_stock(n):
        return any(l.get('quantity',0) > 0 for l in available.get(n, []))

    # Korak 1: Ista vrsta (obvezno) + ista ME
    candidates = [
        n for n in available
        if _get_species(n) == sold_sp and has_stock(n)
    ]
    if not candidates:
        return None, f"ni zaloge za {sold_sp}"

    # Korak 2: File logika
    if sold_fillet:
        fillet_cands = [n for n in candidates if _has_fillet(n)]
        candidates = fillet_cands if fillet_cands else [n for n in candidates if not _has_fillet(n)]
    else:
        non_fillet = [n for n in candidates if not _has_fillet(n)]
        candidates = non_fillet if non_fillet else candidates

    if not candidates:
        return None, f"ni ustreznega artikla za {sold_sp}"

    # Korak 3: Točkovanje (origin + teža)
    def score(n):
        s = 0
        art_origin = _get_origin(n)
        if sold_origin and art_origin:
            s += 10 if art_origin == sold_origin else -3
        s -= _size_distance(sold_size, _get_size(n)) * 3
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
    """
    Dodeli FIFO lote vrsticam dokumenta.

    document_lines: [
      { 'row_id': int, 'article_id': int, 'article_code': str,
        'article_name': str, 'quantity': float, 'unit': str,
        'selling_price': float, 'opis': str }
    ]

    stock: {
      article_name: {
        'article_id': int,
        'article_code': str,
        'lots': [{'code': str, 'quantity': float, 'unit': str}]
      }
    }

    Vrne seznam outputnih vrstic z: lot, quantity_assigned, opis, status
    """
    # Indeks: article_code → article_name v zalogi
    by_code = {v['article_code']: k for k, v in stock.items()}

    # Virtualna zaloga (za sledenje znotraj dokumenta pred potrditvijo)
    virtual: dict[str, list[dict]] = {
        name: [lot.copy() for lot in data['lots']]
        for name, data in stock.items()
    }

    output = []

    for line in document_lines:
        art_code   = line['article_code']
        art_name   = line['article_name']
        qty_needed = round(float(line['quantity']), 4)
        unit       = line['unit']
        base_opis  = (line.get('opis') or '').strip()

        matched_note = ''
        stock_name   = by_code.get(art_code)

        # Preverimo ali ima zaloga
        has_vstock = (
            stock_name is not None and
            any(l.get('quantity',0) > 0 for l in virtual.get(stock_name, []))
        )

        if not has_vstock:
            # Smart matching
            avail_with_stock = {
                n: lots for n, lots in virtual.items()
                if any(l.get('quantity',0) > 0 for l in lots)
            }
            matched, note = smart_match(art_name, avail_with_stock, unit)
            if matched is None:
                output.append({**line,
                    'lot': None, 'quantity_assigned': qty_needed,
                    'opis': f"{base_opis} [brez lota: {note}]".strip(),
                    'status': 'no_match'})
                continue
            stock_name   = matched
            matched_note = note

        # FIFO filtriranje
        name_for_check = art_name if not matched_note else stock_name
        eligible = get_eligible_lots(virtual.get(stock_name, []), name_for_check, today)

        if not eligible:
            output.append({**line,
                'lot': None, 'quantity_assigned': qty_needed,
                'opis': f"{base_opis} [brez lota: ni ustreznih lotov]".strip(),
                'status': 'no_lots'})
            continue

        # Dodelitev po FIFO
        remaining   = qty_needed
        assignments = []

        for lot in eligible:
            if remaining <= 0:
                break
            avail = round(lot['quantity'], 4)
            if avail <= 0:
                continue
            use = round(min(avail, remaining), 4)
            assignments.append((lot['code'], use))
            remaining = round(remaining - use, 4)
            # Odbitek iz virtualne zaloge
            for vl in virtual[stock_name]:
                if vl['code'] == lot['code']:
                    vl['quantity'] = round(vl['quantity'] - use, 4)
                    break

        opis = base_opis
        if matched_note:
            opis = (opis + ' ' + matched_note).strip() if opis else matched_note

        # Ena vrstica na lot
        stock_data = stock.get(stock_name, {})
        for lot_code, qty in assignments:
            output.append({
                **line,
                'article_id':   stock_data.get('article_id', line['article_id']),
                'article_code': stock_data.get('article_code', art_code),
                'article_name': stock_name,
                'lot':          lot_code,
                'quantity_assigned': qty,
                'opis':         opis,
                'status':       'matched' if matched_note else 'ok'
            })

        # Preostala količina brez lota
        if remaining > 0:
            output.append({**line,
                'article_id':   stock_data.get('article_id', line['article_id']),
                'article_code': stock_data.get('article_code', art_code),
                'article_name': stock_name,
                'lot':  None,
                'quantity_assigned': remaining,
                'opis': (opis + ' [brez lota: premalo zaloge]').strip(),
                'status': 'partial'
            })

    return _merge_lot_lines(output)


def _merge_lot_lines(lines: list[dict]) -> list[dict]:
    """Združi vrstice z istim (article_code, lot)."""
    seen  = {}
    order = []
    for line in lines:
        key = (line['article_code'], line.get('lot'))
        if key not in seen:
            seen[key] = {**line}
            order.append(key)
        else:
            seen[key]['quantity_assigned'] = round(
                seen[key]['quantity_assigned'] + line['quantity_assigned'], 4
            )
    return [seen[k] for k in order]
