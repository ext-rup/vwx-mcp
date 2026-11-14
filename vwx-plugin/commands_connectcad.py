"""commands_connectcad.py — ConnectCAD verbs (M6).

Lives outside commands.py for the same reason commands_spotlight.py does: the
vendored file stays rebaseable, the fork grows here, and `vwx_verbs.MODULES`
registers the module with both the pump and `list_commands`.

WHAT CONNECTCAD ACTUALLY IS (verified live on VW2027, 2026-11-14)
----------------------------------------------------------------
Every ConnectCAD object is a type-86 plug-in object whose parameters live in a
parametric record. The record name IS the plug-in name, and the field names are
lowercase-ish and stable:

    Device          35 fields  tag, name, type, make, model, loc_room, loc_rack,
                               loc_rackU, loc_slot, power, weight, heightU,
                               width_R, modular, nslots, HasEquipment, BTU
    Circuit         62 fields  Number, Signal, Cable, Circuits, Src_Dev_Name,
                               Src_Dev_Tag, Src_Skt_Name, Src_Signal,
                               Src_Skt_Conn, Src_Room/Rack/RackU/Slot,
                               Dst_* (same shape), CableCalculatedLength
    CablePathObject 13 fields  ID, Location, CableCount, Length, Cable Area,
                               __Circuits Count, AssignedAutoID
    Room2D           7 fields  RoomID, ExtrudeHeight, Is2DOnly
    Rack19in3D      35 fields  RackID, Height/Width/Depth, Weight, RoomID, ...
    RackFrame       40 fields  name, make, model, loc_room, loc_rack, heightRU
    EquipItem       49 fields  name, make, model, rack ID, rack U, slot ID, ...
    CC Drop Point   10 fields  Category, Name, Symbol, RoomID, CableSlack

So the whole layer is record-driven — the same architecture as the Spotlight
module, and the same honesty rule: a field that cannot be resolved is reported,
never silently blanked.

THE CIRCUIT TOPOLOGY IS ALREADY IN THE RECORD
---------------------------------------------
`CC_GetCircuitSource(hCircuit)` and `CC_GetCircuitDest(hCircuit)` exist in the
SDK but **hard-crash Vectorworks** on VW2027 (verified twice: the process dies
mid-script with no dialog, no Python exception — the pump never returns). They
are not used anywhere in this module. The Src_*/Dst_* record fields carry the
same information (device, tag, socket, signal, connector, room, rack, rack U,
slot), so nothing is lost.

NUMBERS ARE LOCALIZED TEXT
--------------------------
ConnectCAD stores measurements as localized strings, exponent included:
'-1,2e01', '4,826e02', '7,252844172117577e03'. `float()` fails on both the
comma and the exponent, so `_cnum()` normalizes first. Values are in document
units (mm on a metric document); the result carries `units` so a caller never
has to guess.

THE SIGNAL/CONNECTOR CATALOGS ARE 1-BASED
-----------------------------------------
`CC_GetSignalData(name, col)` and `CC_GetConnectorData(name, col)` take a NAME
and a column index. Column 0 returns '', columns start at 1, and the last
column returns ''. The labels are inferred from live samples and every result
carries `raw_columns` plus `labels_verified` so nobody mistakes an inference
for documentation.
"""
import os, re

import vs

import commands as _c
import commands_spotlight as _spot             # for the shared read-back check

_HERE = os.path.dirname(os.path.abspath(__file__))

# record name == plug-in name; used both as the criteria (PON=...) and as the
# record name in worksheet formulas.
PIO_DEVICE = 'Device'
PIO_CIRCUIT = 'Circuit'
PIO_CABLE = 'CablePathObject'
PIO_ROOM = 'Room2D'
PIO_RACK = 'Rack19in3D'
PIO_RACKFRAME = 'RackFrame'
PIO_EQUIP = 'EquipItem'
PIO_DROP = 'CC Drop Point'

# logical key -> record field candidates, best first. A miss is reported in
# `unresolved`, never guessed at.
_DEVICE_KEYS = {
    'tag': ('tag',),
    'name': ('name',),
    'type': ('type',),
    'make': ('make',),
    'model': ('model',),
    'room': ('loc_room',),
    'rack': ('loc_rack',),
    'rack_u': ('loc_rackU',),
    'slot': ('loc_slot',),
    'power': ('power',),
    'weight': ('weight',),
    'btu': ('BTU',),
    'height_u': ('heightU',),
    'rack_width': ('width_R',),
    'modular': ('modular',),
    'slots': ('nslots',),
    'symbol': ('symbol',),
    'has_equipment': ('HasEquipment',),
}

_CIRCUIT_KEYS = {
    'number': ('Number',),
    'signal': ('Signal',),
    'cable': ('Cable',),
    'circuits': ('Circuits',),
    'source_device': ('Src_Dev_Name',),
    'source_tag': ('Src_Dev_Tag',),
    'source_socket': ('Src_Skt_Name',),
    'source_signal': ('Src_Signal',),
    'source_connector': ('Src_Skt_Conn',),
    'source_room': ('Src_Room',),
    'source_rack': ('Src_Rack',),
    'source_rack_u': ('Src_RackU',),
    'source_slot': ('Src_Slot',),
    'dest_device': ('Dst_Dev_Name',),
    'dest_tag': ('Dst_Dev_Tag',),
    'dest_socket': ('Dst_Skt_Name',),
    'dest_signal': ('Dst_Signal',),
    'dest_connector': ('Dst_Skt_Conn',),
    'dest_room': ('Dst_Room',),
    'dest_rack': ('Dst_Rack',),
    'dest_rack_u': ('Dst_RackU',),
    'dest_slot': ('Dst_Slot',),
    'length': ('CableCalculatedLength',),
    'length_mode': ('CableLength',),
    'route_type': ('CircuitType',),
}

_CABLE_KEYS = {
    'id': ('ID',),
    'location': ('Location',),
    'cable_count': ('CableCount',),
    'length': ('Length',),
    'circuits': ('__Circuits Count',),
    'area': ('Cable Area',),
    'auto_id': ('AssignedAutoID',),
}

_ROOM_KEYS = {
    'room': ('RoomID',),
    'height': ('ExtrudeHeight',),
    'is_2d': ('Is2DOnly',),
}

_RACK_KEYS = {
    'rack': ('RackID',),
    'height': ('Height',),
    'width': ('Width',),
    'depth': ('Depth',),
    'weight': ('Weight',),
    'room': ('RoomID',),
    'type': ('RackType',),
    'power': ('Power',),
}

_DROP_KEYS = {
    'name': ('Name',),
    'category': ('Category',),
    'symbol': ('Symbol',),
    'room': ('RoomID',),
    'slack': ('CableSlack',),
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

_NUM_RE = re.compile(r'[-+]?\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?')


def _cnum(v):
    """Number out of a ConnectCAD value, localized exponent included.

    '-1,2e01' -> -12.0, '4,826e02' -> 482.6, '0 sq m' -> 0.0, '' -> None.
    When both separators appear the LAST one is the decimal separator,
    otherwise ',' is decimal (a German install writes 1234,5; an English one
    1,234.5).
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace('\u00a0', '').replace(' ', '')
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    t = m.group(0)
    exp = ''
    for i, ch in enumerate(t):
        if ch in 'eE':
            t, exp = t[:i], t[i:]
            break
    if ',' in t and '.' in t:
        if t.rfind(',') > t.rfind('.'):
            t = t.replace('.', '').replace(',', '.')
        else:
            t = t.replace(',', '')
    else:
        t = t.replace(',', '.')
    try:
        return float(t + exp)
    except ValueError:
        return None


def _verify_sheet(ws, db_row, columns, expected, types=None):
    """The generic worksheet read-back comparison, from commands_spotlight.

    Looked up through the module at CALL time, deliberately: a
    `from commands_spotlight import _verify_sheet` freezes the function object
    at import time, so after a redeploy this module would keep running the old
    comparison while the file on disk says otherwise — a stale check that
    reports verified:false on data that is fine (or worse, the reverse).
    """
    return _spot._verify_sheet(ws, db_row, columns, expected, types)


def _units():
    """Document units as a small dict.

    vs.GetUnits() returns a tuple on VW2027 — (fractional, ?, ?, scale,
    'mm', ' sq m') — so handing it back raw gives the caller a list of numbers
    with no meaning. The unit strings are the part anyone actually needs.
    """
    raw = _c._safe(lambda: vs.GetUnits())
    out = {'raw': raw}
    if isinstance(raw, (list, tuple)):
        if len(raw) > 4 and isinstance(raw[4], str):
            out['unit'] = raw[4].strip()
        if len(raw) > 5 and isinstance(raw[5], str):
            out['area_unit'] = raw[5].strip()
        if len(raw) > 3:
            out['scale'] = raw[3]
    elif isinstance(raw, str):
        out['unit'] = raw.strip()
    return out


def _fields(h):
    """Every field of the object's parametric record, as {name: value}."""
    rec = _c._safe(lambda: vs.GetParametricRecord(h))
    if not rec:
        return {}
    name = _c._safe(lambda: vs.GetName(rec)) or ''
    n = _c._safe(lambda: vs.NumFields(rec)) or 0
    out = {}
    for i in range(1, n + 1):
        fn = _c._safe(lambda: vs.GetFldName(rec, i))
        if not fn:
            continue
        out[fn] = _c._safe(lambda: vs.GetRField(h, name, fn))
    return out


def _pick(fields, keys, unresolved, logical):
    """First present candidate for a logical key; records a miss."""
    for cand in keys.get(logical, ()):
        if cand in fields:
            return fields[cand]
    unresolved.add(logical)
    return None


def _map(fields, keys):
    """{logical: value} for one object, plus the keys that did not resolve."""
    unresolved = set()
    out = {k: _pick(fields, keys, unresolved, k) for k in keys}
    return out, unresolved


def _collect(pio, extra=''):
    """Handles of every object whose parametric record is named `pio`.

    Criteria first (fast, and what the document itself uses); if that matches
    nothing — a localized plug-in name, or a criteria engine that does not know
    this PIO — fall back to a document scan and say so in `strategy`.
    """
    hs = []

    def cb(h):
        hs.append(h)

    crit = "((PON='%s'))" % pio if not extra else "((PON='%s') %s)" % (pio, extra)
    _c._safe(lambda: vs.ForEachObject(cb, crit))
    if hs:
        return hs, 'criteria'

    def cb2(h):
        rec = _c._safe(lambda: vs.GetParametricRecord(h))
        if rec and _c._safe(lambda: vs.GetName(rec)) == pio:
            hs.append(h)

    _c._safe(lambda: vs.ForEachObject(cb2, '(ALL)'))
    return hs, 'scan'


def _limit(p, default=500):
    try:
        n = int(p.get('limit') or default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, 5000))


def _sort_rows(rows, key):
    """Sort by one logical key: numbers before text, blanks last."""
    if not key:
        return rows

    def sort_key(r):
        v = r.get(key)
        n = _cnum(v)
        if n is not None:
            return (0, n, '')
        s = '' if v is None else str(v)
        return (1, 0.0, s.lower()) if s else (2, 0.0, '')

    return sorted(rows, key=sort_key)


def _matches(row, filters):
    """Every filter value must equal (case-insensitively) the row's field."""
    for k, want in filters.items():
        if want in (None, ''):
            continue
        got = row.get(k)
        if got is None:
            return False
        if str(got).strip().lower() != str(want).strip().lower():
            return False
    return True


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

def get_connectcad_devices(p):
    """ConnectCAD devices with their location, power, weight and BTU.

    params: room, rack, type, criteria, limit, raw
    """
    hs, strategy = _collect(PIO_DEVICE, (p.get('criteria') or '').strip())
    filters = {k: p.get(k) for k in ('room', 'rack', 'type')}
    rows, unresolved, raw = [], set(), {}
    for h in hs:
        f = _fields(h)
        row, miss = _map(f, _DEVICE_KEYS)
        unresolved |= miss
        if not _matches(row, filters):
            continue
        row['object_id'] = _c._safe(lambda: vs.GetObjectUuid(h))
        if p.get('raw'):
            raw[row['object_id']] = f
        rows.append(row)
    rows = _sort_rows(rows, p.get('sort_by') or 'tag')[: _limit(p)]
    out = {'count': len(rows), 'devices': rows, 'strategy': strategy,
           'units': _units(), 'catalog': 'live'}
    if unresolved:
        out['unresolved'] = sorted(unresolved)
    if p.get('raw'):
        out['raw'] = raw
    return out


def get_connectcad_circuits(p):
    """Circuits with full source -> destination topology.

    params: signal, device, criteria, limit, sort_by, raw

    `device` matches either end (device name or tag). The topology comes from
    the record, never from CC_GetCircuitSource/Dest — those crash VW2027.
    """
    hs, strategy = _collect(PIO_CIRCUIT, (p.get('criteria') or '').strip())
    want_signal = (p.get('signal') or '').strip().lower()
    want_dev = (p.get('device') or '').strip().lower()
    rows, unresolved, raw = [], set(), {}
    for h in hs:
        f = _fields(h)
        row, miss = _map(f, _CIRCUIT_KEYS)
        unresolved |= miss
        if want_signal and str(row.get('signal') or '').strip().lower() != want_signal:
            continue
        if want_dev:
            ends = [row.get('source_device'), row.get('source_tag'),
                    row.get('dest_device'), row.get('dest_tag')]
            if not any(str(e or '').strip().lower() == want_dev for e in ends):
                continue
        row['object_id'] = _c._safe(lambda: vs.GetObjectUuid(h))
        row['length_num'] = _cnum(row.get('length'))
        if p.get('raw'):
            raw[row['object_id']] = f
        rows.append(row)
    rows = _sort_rows(rows, p.get('sort_by') or 'number')[: _limit(p)]
    out = {'count': len(rows), 'circuits': rows, 'strategy': strategy,
           'units': _units(), 'catalog': 'live'}
    if unresolved:
        out['unresolved'] = sorted(unresolved)
    if p.get('raw'):
        out['raw'] = raw
    return out


def get_connectcad_cables(p):
    """Cable paths (CablePathObject): id, cable count, length, circuits."""
    hs, strategy = _collect(PIO_CABLE, (p.get('criteria') or '').strip())
    rows, unresolved = [], set()
    for h in hs:
        row, miss = _map(_fields(h), _CABLE_KEYS)
        unresolved |= miss
        row['object_id'] = _c._safe(lambda: vs.GetObjectUuid(h))
        row['length_num'] = _cnum(row.get('length'))
        rows.append(row)
    rows = _sort_rows(rows, p.get('sort_by') or 'id')[: _limit(p)]
    out = {'count': len(rows), 'cables': rows, 'strategy': strategy,
           'units': _units(), 'catalog': 'live',
           'total_length': sum(r['length_num'] or 0.0 for r in rows)}
    if unresolved:
        out['unresolved'] = sorted(unresolved)
    return out


def get_connectcad_rooms(p):
    """Rooms with what is in them: device, rack and drop-point counts."""
    hs, strategy = _collect(PIO_ROOM)
    devices, _ = _collect(PIO_DEVICE)
    racks, _ = _collect(PIO_RACK)
    drops, _ = _collect(PIO_DROP)

    def room_of(h, key):
        f = _fields(h)
        return str(f.get(key) or '').strip()

    dev_by_room, rack_by_room, drop_by_room = {}, {}, {}
    for h in devices:
        dev_by_room[room_of(h, 'loc_room')] = dev_by_room.get(room_of(h, 'loc_room'), 0) + 1
    for h in racks:
        rack_by_room[room_of(h, 'RoomID')] = rack_by_room.get(room_of(h, 'RoomID'), 0) + 1
    for h in drops:
        drop_by_room[room_of(h, 'RoomID')] = drop_by_room.get(room_of(h, 'RoomID'), 0) + 1

    rows = []
    for h in hs:
        row, _miss = _map(_fields(h), _ROOM_KEYS)
        rid = str(row.get('room') or '').strip()
        row['object_id'] = _c._safe(lambda: vs.GetObjectUuid(h))
        row['devices'] = dev_by_room.get(rid, 0)
        row['racks'] = rack_by_room.get(rid, 0)
        row['drop_points'] = drop_by_room.get(rid, 0)
        row['height_num'] = _cnum(row.get('height'))
        rows.append(row)
    rows = _sort_rows(rows, p.get('sort_by') or 'room')[: _limit(p)]
    return {'count': len(rows), 'rooms': rows, 'strategy': strategy,
            'units': _units(), 'catalog': 'live'}


def get_connectcad_racks(p):
    """Racks with the equipment items assigned to them."""
    hs, strategy = _collect(PIO_RACK)
    frames, _ = _collect(PIO_RACKFRAME)
    equip, _ = _collect(PIO_EQUIP)

    by_rack = {}
    for h in equip:
        f = _fields(h)
        rid = str(f.get('rack ID') or '').strip()
        if not rid:
            continue
        by_rack.setdefault(rid, []).append({
            'name': f.get('name'), 'make': f.get('make'), 'model': f.get('model'),
            'u': _cnum(f.get('rack U')), 'height_u': _cnum(f.get('heightU')),
            'slot': f.get('slot ID'),
            'object_id': _c._safe(lambda: vs.GetObjectUuid(h)),
        })

    rows = []
    for h in hs:
        row, _miss = _map(_fields(h), _RACK_KEYS)
        rid = str(row.get('rack') or '').strip()
        row['object_id'] = _c._safe(lambda: vs.GetObjectUuid(h))
        row['contents'] = sorted(by_rack.get(rid, []),
                                 key=lambda e: (e.get('u') is None, e.get('u') or 0))
        row['content_count'] = len(row['contents'])
        for k in ('height', 'width', 'depth', 'weight', 'power'):
            row[k + '_num'] = _cnum(row.get(k))
        rows.append(row)
    rows = _sort_rows(rows, p.get('sort_by') or 'rack')[: _limit(p)]
    out = {'count': len(rows), 'racks': rows, 'strategy': strategy,
           'units': _units(), 'catalog': 'live'}
    if not hs and frames:
        out['note'] = ('%d RackFrame object(s) present but no Rack19in3D — '
                       'this verb reads the 3D rack, not the frame' % len(frames))
    return out


def _catalog(names, reader, labels, echo_col=None):
    """Probe a ConnectCAD data catalog (CC_GetSignalData / CC_GetConnectorData).

    Columns are 1-based; column 0 and the first empty column return ''. The
    labels are inferred from live samples, so every entry keeps `raw_columns`.

    `echo_col` is the column that must echo the queried name (2 for signals).
    When a catalog has no such column the labels cannot be checked at all, and
    the result says `labels_verified: None` rather than claiming a pass.
    """
    out, verified = [], (True if echo_col else None)
    for name in names:
        cols = {}
        for col in range(1, 7):
            v = _c._safe(lambda: reader(name, col))
            if v in (None, ''):
                continue
            cols[col] = v
        entry = {'name': name, 'raw_columns': cols}
        for col, label in labels.items():
            entry[label] = cols.get(col)
        if echo_col and cols.get(echo_col) != name:
            verified = False
        out.append(entry)
    res = {'count': len(out), 'entries': out, 'columns': sorted(labels),
           'labels': labels, 'labels_verified': verified,
           'labels_source': 'inferred from live samples; raw_columns is authoritative'}
    if verified is False:
        res['warning'] = ('the name column did not echo every queried name — '
                          'read raw_columns, the label map may be off')
    elif verified is None:
        res['note'] = ('no column echoes the queried name, so the label map '
                       'cannot be checked; raw_columns is authoritative')
    return res


def get_connectcad_signals(p):
    """The signal catalog (CC_GetSignalData), one entry per signal name.

    params: names (list) — default: every distinct Circuit.Signal in the doc.
    """
    names = p.get('names') or []
    if not names:
        hs, _ = _collect(PIO_CIRCUIT)
        seen = []
        for h in hs:
            s = str(_fields(h).get('Signal') or '').strip()
            if s and s not in seen:
                seen.append(s)
        names = seen
    if not names:
        return {'count': 0, 'entries': [],
                'note': 'no signal names given and no Circuit in the document'}
    res = _catalog(names, vs.CC_GetSignalData,
                   {1: 'code', 2: 'name', 3: 'description', 4: 'connector',
                    6: 'category'}, echo_col=2)
    res['catalog'] = 'live'
    return res


def get_connectcad_connectors(p):
    """The connector catalog (CC_GetConnectorData), one entry per connector.

    params: names (list) — default: every distinct circuit connector.
    """
    names = p.get('names') or []
    if not names:
        hs, _ = _collect(PIO_CIRCUIT)
        seen = []
        for h in hs:
            f = _fields(h)
            for k in ('Src_Skt_Conn', 'Dst_Skt_Conn'):
                s = str(f.get(k) or '').strip()
                if s and s not in seen:
                    seen.append(s)
        names = seen
    if not names:
        return {'count': 0, 'entries': [],
                'note': 'no connector names given and no Circuit in the document'}
    res = _catalog(names, vs.CC_GetConnectorData,
                   {1: 'description', 2: 'symbol', 3: 'signal', 4: 'type'})
    res['catalog'] = 'live'
    return res


# --------------------------------------------------------------------------
# schedules + worksheets
# --------------------------------------------------------------------------

_SCHEDULES = {
    'equipment': {
        'pio': PIO_DEVICE, 'keys': _DEVICE_KEYS,
        'columns': [('Tag', 'tag', 24), ('Name', 'name', 90), ('Type', 'type', 60),
                    ('Room', 'room', 24), ('Rack', 'rack', 30),
                    ('U', 'rack_u', 18), ('Power', 'power', 30),
                    ('Weight', 'weight', 30), ('BTU', 'btu', 24)],
        'sort': 'tag',
    },
    'circuit': {
        'pio': PIO_CIRCUIT, 'keys': _CIRCUIT_KEYS,
        'columns': [('No', 'number', 24), ('Signal', 'signal', 36),
                    ('Src Dev', 'source_device', 80), ('Src Skt', 'source_socket', 70),
                    ('Dst Dev', 'dest_device', 80), ('Dst Skt', 'dest_socket', 70),
                    ('Length', 'length', 36), ('Circuits', 'circuits', 24)],
        'sort': 'number',
    },
    'cable': {
        'pio': PIO_CABLE, 'keys': _CABLE_KEYS,
        'columns': [('ID', 'id', 24), ('Cables', 'cable_count', 24),
                    ('Length', 'length', 40), ('Circuits', 'circuits', 24),
                    ('Location', 'location', 90)],
        'sort': 'id',
    },
    'rack': {
        'pio': PIO_RACK, 'keys': _RACK_KEYS,
        'columns': [('Rack', 'rack', 30), ('Room', 'room', 24),
                    ('Height', 'height', 30), ('Width', 'width', 30),
                    ('Depth', 'depth', 30), ('Weight', 'weight', 30)],
        'sort': 'rack',
    },
    'room': {
        'pio': PIO_ROOM, 'keys': _ROOM_KEYS,
        'columns': [('Room', 'room', 30), ('Height', 'height', 36),
                    ('2D only', 'is_2d', 30)],
        'sort': 'room',
    },
}


def _schedule_def(kind):
    return _SCHEDULES.get((kind or 'equipment').strip().lower())


def _field_types(h):
    """{field name: vs.GetFldType code} for one object's parametric record."""
    rec = _c._safe(lambda: vs.GetParametricRecord(h))
    if not rec:
        return {}
    out = {}
    for i in range(1, (_c._safe(lambda: vs.NumFields(rec)) or 0) + 1):
        fn = _c._safe(lambda: vs.GetFldName(rec, i))
        if fn:
            out[fn] = _c._safe(lambda: vs.GetFldType(rec, i))
    return out


def _schedule_rows(kind, p):
    """Rows for a schedule, plus the field type of every logical key.

    The types matter for verification: a popup field (type 8) renders its
    choice label in a worksheet cell, so comparing its text would report a
    correct sheet as wrong.
    """
    d = _schedule_def(kind)
    hs, strategy = _collect(d['pio'], (p.get('criteria') or '').strip())
    rows, unresolved = [], set()
    for h in hs:
        row, miss = _map(_fields(h), d['keys'])
        unresolved |= miss
        row['object_id'] = _c._safe(lambda: vs.GetObjectUuid(h))
        rows.append(row)
    ftypes = _field_types(hs[0]) if hs else {}
    types = {}
    for logical, cands in d['keys'].items():
        for cand in cands:
            if cand in ftypes:
                types[logical] = ftypes[cand]
                break
    rows = _sort_rows(rows, p.get('sort_by') or d['sort'])[: _limit(p)]
    return d, rows, sorted(unresolved), strategy, types


def get_connectcad_schedule(p):
    """A paperwork schedule as JSON rows.

    params: kind (equipment|circuit|cable|rack|room), criteria, sort_by, limit
    """
    kind = (p.get('kind') or 'equipment').strip().lower()
    if not _schedule_def(kind):
        return {'error': 'unknown kind %r' % kind,
                'kinds': sorted(_SCHEDULES)}
    d, rows, unresolved, strategy, _types = _schedule_rows(kind, p)
    out = {
        'kind': kind,
        'count': len(rows),
        'columns': [{'header': h, 'key': k, 'width': w} for h, k, w in d['columns']],
        'rows': rows,
        'strategy': strategy,
        'units': _units(),
        'catalog': 'live',
    }
    if unresolved:
        out['unresolved'] = unresolved
    return out


def _ws_formula(record, field):
    return "='%s'.'%s'" % (record, field)


def connectcad_worksheet(p):
    """Build a real Vectorworks database worksheet and verify it cell by cell.

    params: kind, name, criteria, sort_by, limit, place, x, y, verify

    Same contract as spotlight_worksheet: the column formulas are generated
    from the record fields the objects actually report, then every subrow is
    read back and compared with the JSON schedule. `verified: false` names the
    column instead of handing back a sheet that silently shows nothing.
    """
    kind = (p.get('kind') or 'equipment').strip().lower()
    d = _schedule_def(kind)
    if not d:
        return {'error': 'unknown kind %r' % kind, 'kinds': sorted(_SCHEDULES)}
    name = (p.get('name') or '').strip() or ('CC %s' % kind.title())
    existing = _c._safe(lambda: vs.GetObject(name))
    if existing and _c._safe(lambda: vs.GetTypeN(existing)) != 0:
        return {'error': 'a worksheet or object named %r already exists' % name,
                'hint': 'pass a different name'}

    _d, rows, unresolved, strategy, types = _schedule_rows(kind, p)
    if not rows:
        return {'error': 'no %s objects matched' % kind,
                'criteria': p.get('criteria') or '', 'strategy': strategy}

    cols = d['columns']
    ws = _c._safe(lambda: vs.CreateWS(name, 2, len(cols)))
    if not ws:
        return {'error': 'vs.CreateWS failed', 'name': name}

    for i, (header, _key, width) in enumerate(cols, start=1):
        _c._safe(lambda: vs.SetWSCellFormula(ws, 1, i, 1, i, header))
        _c._safe(lambda: vs.SetWSColumnWidth(ws, i, i, width))

    # Row 2, COLUMN 0 binds the row to the criteria database. Column 1 stores
    # the same text as a plain string and recalculates to zero subrows — which
    # is exactly what an empty sheet looks like, so it is worth stating: the
    # worksheet API's data columns are 1-based, but the database binding cell
    # is column 0.
    crit = (p.get('criteria') or '').strip() or "((PON='%s'))" % d['pio']
    _c._safe(lambda: vs.SetWSCellFormula(ws, 2, 0, 2, 0, '=DATABASE(%s)' % crit))
    for i, (_header, key, _w) in enumerate(cols, start=1):
        field = d['keys'][key][0]
        _c._safe(lambda: vs.SetWSCellFormula(ws, 2, i, 2, i,
                                             _ws_formula(d['pio'], field)))

    _c._safe(lambda: vs.RecalculateWS(ws))
    subrows = _c._safe(lambda: vs.GetWSSubrowCount(ws, 2)) or 0
    if isinstance(subrows, tuple):
        subrows = subrows[0] if subrows else 0
    if subrows == 0:                       # VW leaves a fresh db row empty
        _c._safe(lambda: vs.RecalculateWS(ws))
        subrows = _c._safe(lambda: vs.GetWSSubrowCount(ws, 2)) or 0
        if isinstance(subrows, tuple):
            subrows = subrows[0] if subrows else 0

    out = {'worksheet': name, 'kind': kind, 'subrows': subrows,
           'columns': len(cols), 'strategy': strategy, 'catalog': 'live'}
    if p.get('verify', True):
        ok, subrows, detail = _verify_sheet(ws, 2, cols, rows, types)
        out['subrows'] = subrows
        out['verified'] = bool(ok) and subrows > 0
        out['detail'] = detail
        if not out['verified']:
            out['warning'] = ('the worksheet does not match the schedule — '
                              'see detail[] for the column that differs')
    if p.get('place'):
        loc = (float(p.get('x') or 0), float(p.get('y') or 0))
        img = _c._safe(lambda: vs.CreateWSImage(ws, loc))
        if img:
            out['image_id'] = _c._safe(lambda: vs.GetObjectUuid(img))
        else:
            out['placement_error'] = 'vs.CreateWSImage returned no object'
    if unresolved:
        out['unresolved'] = unresolved
    return out
