"""commands_spotlight.py — Spotlight (entertainment lighting) verbs.

Lives OUTSIDE commands.py on purpose (see QUICKSTART "Rules for this fork" #4):
commands.py is vendored upstream and stays rebaseable; Spotlight grows here and
is registered by the pump (`vwx_pump._dispatch` falls back to this module).

WHY THIS FILE IS DATA-DRIVEN
----------------------------
A Lighting Device is a plug-in object whose parameters are addressed by their
**universal name** (the "worksheet name"), not by index:

    vs.LDevice_GetParamStr(h, cellIndex, accessoryIndex, 'channel')
        cellIndex      0 = first cell
        accessoryIndex -1 = the device itself (>=0 = an attached accessory)

Nobody publishes the universal-name list, and it is not the same as the
localized field labels shown in the Object Info palette, so hardcoding guesses
would fail silently (a wrong name returns '' rather than raising). Therefore:

  1. `dump_spotlight_params` enumerates the real catalog from a live document
     via vs.GetParametricRecord + vs.NumFields/GetFldName/GetFldType and writes
     vwx-plugin/spotlight_params.json.
  2. Every read verb resolves its logical keys (channel, universe, position,
     ...) through that catalog and reports what it could NOT resolve in
     `unresolved` instead of returning a quietly empty field.
  3. `raw: true` returns every field the object actually has, so a wrong or
     missing mapping still lets the caller read the data.

If the catalog file is absent the verbs still work: they fall back to
`_FALLBACK_KEYS` (best-known universal names) and mark the result
`"catalog": "fallback"` so nobody mistakes it for verified data.
"""
import os, json, re, time

import vs

import commands as _c          # _safe/_oid/_h/_collect/_bbox live there

_HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS_PATH = os.path.join(_HERE, 'spotlight_params.json')

# A Lighting Device is a plug-in object; VW's criteria engine names it by its
# localized plug-in name. English is the default; the dump records whatever the
# live document reports so a localized install can be corrected in one place.
_DEFAULT_PLUGIN_NAME = 'Lighting Device'

# Record field types as returned by vs.GetFldType, verified against a live
# VW2027 Lighting Device ("Symbol Name"=4, "Fixture Mode"=8, "GDTF Fixture
# Name"=14, "UseGDTFGeometry"=2, "Num Channels"=1):
#   1 long, 2 bool, 3 real, 4 text — everything above (control point, popup,
#   coordinate, class, layer, ...) is read as text, which is what
#   LDevice_GetParamStr returns for it anyway.
_TYPE_READER = {1: 'Long', 2: 'Bool', 3: 'Real', 4: 'Str'}

# A field name that is not printable ASCII is not a parameter name: VW2027's
# Lighting Device record starts with one such junk field (private-use code
# points, GetFldType -23248) and passing it to LDevice_GetParamStr CRASHES
# Vectorworks (verified 2026-11-14 — hard process death, no dialog).
def _valid_name(name):
    if not name or not isinstance(name, str):
        return False
    for ch in name:
        o = ord(ch)
        if o < 0x20 or 0x7F <= o <= 0xA0 or 0xE000 <= o <= 0xF8FF:
            return False
    return True

# logical key -> normalized universal-name candidates, best first. Only used to
# map the catalog; a miss is reported, never guessed at silently.
_SYNONYMS = {
    'channel':       ('channel', 'ch', 'channelnumber', 'channelnum'),
    'dimmer':        ('dimmer', 'dim', 'dimmerchannel', 'dimmernumber'),
    'universe':      ('universe', 'univ', 'universenumber', 'universenum'),
    'address':       ('address', 'dmxaddress', 'addr', 'dmxaddr', 'startaddress'),
    'position':      ('position', 'pos', 'hangingposition', 'positionname'),
    'focus':         ('focus', 'focuspoint', 'focusarea', 'focusname'),
    'color':         ('color', 'colour', 'gel', 'colorframe', 'gelframe',
                      'color1', 'colour1'),
    'gobo':          ('gobodata', 'gobo', 'gobopattern', 'pattern', 'gobo1',
                      'goboindex'),
    'accessory':     ('accessoryinventory', 'accessory', 'accessories',
                      'accessoryname'),
    'unit_number':   ('unitnumber', 'unit', 'unitno', 'unitnum'),
    'device_type':   ('devicetype', 'instrumenttype', 'type', 'fixturetype'),
    'symbol_name':   ('symbolname', 'symbol', 'instrumentsymbol', 'devicesymbol'),
    'purpose':       ('purpose', 'use', 'purposeofuse'),
    'pan':           ('pan',),
    'tilt':          ('tilt',),
    'rotation':      ('zrotation', 'rotation', 'zrot', 'rotationz'),
    'weight':        ('weight',),
    'power':         ('power', 'wattage', 'watts', 'load'),
    'dmx_footprint': ('numchannels', 'dmxfootprint', 'footprint', 'channelsused'),
    'device_id':     ('deviceid', 'fixtureid', 'id'),
    'console_id':    ('lightwrightid', 'consoleid', 'console', 'uid'),
    # Verified VW2027 names that have no synonym above; kept here so the
    # catalog's key map stays the single place a caller looks.
    'universe_address': ('universeaddress', 'universe_address'),
    'absolute_address': ('absoluteaddress', 'absolute_address'),
    'circuit':       ('circuitnumber', 'circuitname', 'circuit'),
    'mark':          ('mark',),
    'system':        ('system',),
    'device_name':   ('symbolname', 'name'),
}

# Used only when spotlight_params.json is missing (fresh deploy, or a document
# that has no Lighting Device to dump from). Deliberately small and marked
# unverified in every result that relies on it.
_FALLBACK_KEYS = {
    'channel': 'channel', 'dimmer': 'dimmer', 'universe': 'universe',
    'address': 'address', 'position': 'position', 'focus': 'focus',
    'color': 'color', 'gobo': 'gobo', 'accessory': 'accessory',
    'unit_number': 'unit_number', 'device_type': 'device_type',
    'symbol_name': 'symbol_name', 'purpose': 'purpose',
    'pan': 'pan', 'tilt': 'tilt', 'rotation': 'rotation',
    'weight': 'weight', 'power': 'power',
    'dmx_footprint': 'dmx_footprint', 'device_id': 'device_id',
    'console_id': 'console_id',
}

# Keys that make up a patch sheet, in the order a lighting designer reads them.
# The flat row every device carries: the patch sheet's own columns plus the
# handful of fields a focus/rigging question needs. Everything else is one
# `raw: true` away (the catalog lists all 150 fields of a VW2027 device).
_PATCH_KEYS = ('channel', 'dimmer', 'universe', 'address', 'universe_address',
               'absolute_address', 'dmx_footprint', 'position', 'unit_number',
               'device_type', 'symbol_name', 'purpose', 'color', 'gobo', 'focus',
               'circuit', 'mark', 'system', 'pan', 'tilt', 'weight', 'power')


# ── catalog ────────────────────────────────────────────────────────────────

_catalog_cache = {'mtime': None, 'data': None}


def _norm(s):
    return ''.join(ch for ch in (s or '').lower() if ch.isalnum())


def _load_catalog(force=False):
    """spotlight_params.json, cached by mtime. None when it does not exist."""
    try:
        mt = os.path.getmtime(PARAMS_PATH)
    except Exception:
        return None
    if not force and _catalog_cache['mtime'] == mt:
        return _catalog_cache['data']
    try:
        with open(PARAMS_PATH, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return None
    _catalog_cache['mtime'] = mt
    _catalog_cache['data'] = data
    return data


def _keys():
    """(logical -> universal name, source label) from the catalog file."""
    cat = _load_catalog()
    if cat and cat.get('keys'):
        return dict(cat['keys']), 'catalog'
    return dict(_FALLBACK_KEYS), 'fallback'


def _keys_for(hs):
    """(keys, source, unresolved) for these objects.

    Live resolution wins: the object's own parametric record is the ground
    truth, so a stale or absent spotlight_params.json cannot silently blank a
    field. The catalog file is the fallback (and the human-readable reference),
    the built-in table the last resort.
    """
    if hs:
        names = [n for _i, n, _t, _f in _field_names(hs[0])]
        if names:
            keys, unresolved = _resolve_keys(names)
            return keys, 'live', unresolved
    keys, source = _keys()
    return keys, source, []


def _resolve_keys(field_names):
    """Map logical keys onto the universal names an object actually has."""
    by_norm = {}
    for name in field_names:
        by_norm.setdefault(_norm(name), name)
    keys, unresolved = {}, []
    for logical, candidates in _SYNONYMS.items():
        for cand in candidates:
            hit = by_norm.get(cand)
            if hit:
                keys[logical] = hit
                break
        else:
            unresolved.append(logical)
    return keys, unresolved


# ── object inspection ──────────────────────────────────────────────────────

def _pio_record_name(h):
    """Universal/localized name of the parametric record, or ''."""
    try:
        rec = vs.GetParametricRecord(h)
        if not rec:
            return ''
        return vs.GetName(rec) or ''
    except Exception:
        return ''


def _field_names(h):
    """[(index, universal name, type, flag)] for a plug-in object's record."""
    out = []
    try:
        rec = vs.GetParametricRecord(h)
        if not rec:
            return out
        n = int(vs.NumFields(rec) or 0)
    except Exception:
        return out
    for i in range(n):
        try:
            name = vs.GetFldName(rec, i)
        except Exception:
            continue
        if not _valid_name(name):
            continue
        out.append((i, name,
                    _c._safe(lambda i=i: int(vs.GetFldType(rec, i)), None),
                    _c._safe(lambda i=i: int(vs.GetFldFlag(rec, i)), None)))
    return out


_READERS = {
    'Str':  lambda h, c, a, n: vs.LDevice_GetParamStr(h, c, a, n),
    'Real': lambda h, c, a, n: vs.LDevice_GetParamReal(h, c, a, n),
    'Long': lambda h, c, a, n: vs.LDevice_GetParamLong(h, c, a, n),
    'Bool': lambda h, c, a, n: vs.LDevice_GetParamBool(h, c, a, n),
}


def _cast(v, typed):
    """Record values are strings; give the caller the field's own type back."""
    if v in (None, ''):
        return v
    try:
        if typed == 'Long':
            return int(float(str(v).replace(',', '.')))
        if typed == 'Real':
            return float(str(v).replace(',', '.'))
        if typed == 'Bool':
            return str(v).strip().lower() in ('1', 'true', 'yes', 'ja')
    except (TypeError, ValueError):
        return v
    return v


def _read_param(h, cell, acc, name, ftype=None):
    """One parameter, typed by the record field type when known.

    Two sources, and which one wins depends on what is being asked:

      * **device level** (`cell` 0, `acc` -1): the record (`vs.GetRField`) is
        authoritative — it is what the Object Info palette shows, and it is
        what SetRField writes. Verified live: `LDevice_GetParamLong` returns 0
        for `DMX Address`/`Num Channels` while the record holds the real value,
        so preferring the LDevice reader here would report an unpatched device
        that is patched.
      * **a specific cell / accessory**: `LDevice_GetParam*` is the only reader
        that knows about cells, so it wins and the record is the fallback.

    In both cases popup / control-point / coordinate fields (GetFldType 8, 14,
    20, ...) have no LDevice reader at all and only exist in the record.
    """
    if not _valid_name(name):
        return None           # see _valid_name: this crashes VW, not just fails
    if cell is not None and cell >= _cells(h):
        return None           # index past the last cell is an engine error
    typed = _TYPE_READER.get(ftype)
    rec = _pio_record_name(h)
    recv = _c._safe(lambda: vs.GetRField(h, rec, name)) if rec else None
    device_level = acc == -1 and cell in (0, None)
    if device_level and recv not in (None, ''):
        return _cast(recv, typed)
    try:
        if typed:
            v = _READERS[typed](h, cell, acc, name)
        else:
            v = vs.LDevice_GetParamStr(h, cell, acc, name)
    except Exception:
        v = None
    if v not in (None, ''):
        return v
    if recv not in (None, ''):
        return _cast(recv, typed)
    # A text field that resolved but is empty is "", not None: None means the
    # name did not resolve at all, and callers distinguish the two.
    return '' if typed == 'Str' else None


def _cells(h):
    return max(0, _c._safe(lambda: int(vs.LDevice_GetCellCount(h)), 0) or 0)


def _accessory_count(h, cell):
    return max(0, _c._safe(lambda: int(vs.LDevice_GetAccCount(h, cell)), 0) or 0)


def _is_lighting_device(h):
    """Cheap, non-destructive test: a Lighting Device has at least one cell.

    Called only on objects the criteria already matched, so this is a sanity
    filter rather than a document-wide classifier (LDevice_* on an unrelated
    object is untested and could raise an engine error dialog).
    """
    if _c._safe(lambda: vs.GetTypeN(h), 0) != 86:
        return False
    return _cells(h) > 0


def _devices(p):
    """Handles of the lighting devices a request selects.

    criteria: raw VW criteria string (default the Lighting Device plug-in).
    Falls back to a name-filtered document scan when the criteria match nothing
    — a localized Vectorworks names the plug-in differently, and an empty result
    would otherwise look like an empty plot.
    """
    crit = (p.get('criteria') or '').strip()
    limit = int(p.get('limit') or 500)
    if not crit:
        crit = "((PON='%s'))" % _DEFAULT_PLUGIN_NAME
    hs = [h for h in _c._collect(crit, limit) if _is_lighting_device(h)]
    strategy = 'criteria'
    if not hs and not p.get('criteria'):
        hs = [h for h in _c._collect('ALL', 20000)
              if _is_lighting_device(h)][:limit]
        strategy = 'scan'
    # Optional post-filters (cheap string compare, no extra vs.* calls).
    pos = (p.get('position') or '').strip().lower()
    if pos and hs:
        keys, _src, _un = _keys_for(hs)
        pname = keys.get('position', 'position')
        hs = [h for h in hs
              if str(_read_param(h, 0, -1, pname) or '').strip().lower() == pos]
    return hs, strategy


def _geom(h):
    bb = _c._bbox(h) or {}
    if bb.get('x1') is None:
        return {}
    return {'x': round((bb['x1'] + bb['x2']) / 2.0, 4),
            'y': round((bb['y1'] + bb['y2']) / 2.0, 4),
            'x1': bb['x1'], 'y1': bb['y1'], 'x2': bb['x2'], 'y2': bb['y2']}


def _device_row(h, keys, ftypes, want_raw=False):
    """One device as a flat dict. Only fields that resolve are read."""
    row = {'object_id': _c._oid(h),
           'name': _c._safe(lambda: vs.GetName(h)),
           'class': _c._safe(lambda: vs.GetClass(h)),
           'layer': _c._safe(lambda: vs.GetLName(vs.GetLayer(h))),
           'record': _pio_record_name(h),
           'cells': _cells(h)}
    row.update(_geom(h))
    for logical in _PATCH_KEYS:
        name = keys.get(logical)
        if name:
            row[logical] = _read_param(h, 0, -1, name, ftypes.get(name))
    if want_raw:
        row['raw'] = {name: _read_param(h, 0, -1, name, ftypes.get(name))
                      for name in ftypes}
    return row


def _int(v, default=None):
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _digits(v):
    """First run of digits in a string ('U1' -> 1, '001' -> 1, 'A' -> None)."""
    m = re.search(r'\d+', str(v or ''))
    return int(m.group(0)) if m else None


def _universe_address(row):
    """(universe, address) from the device fields, tolerating 'U1/001' forms.

    VW2027 keeps the patch in **`UniverseAddress`** as "universe/address"
    (verified live: `SetRField` into it sticks, `LDevice_GetParamStr` lags a
    reset behind, and the separate `Universe` / `DMX Address` fields are not
    derived from it at all). "0/0" is Vectorworks' "not patched" sentinel.

    The separate fields stay as a fallback: they are free text in the Object
    Info palette (a designer may write 'U1/001' into address, or leave universe
    empty), so integer parsing has to survive prefixes rather than assume a
    clean number.
    """
    ua = row.get('universe_address')
    if isinstance(ua, str) and '/' in ua:
        head, _, tail = ua.partition('/')
        uni, addr = _digits(head), _digits(tail)
        if addr is not None:
            if uni == 0 and addr == 0:
                return None, None          # VW's "no patch" sentinel
            return uni, addr
    uni = _int(row.get('universe'))
    addr = _int(row.get('address'))
    if addr is None and isinstance(row.get('address'), str) and '/' in row['address']:
        head, _, tail = row['address'].partition('/')
        if uni is None:
            uni = _digits(head)
        addr = _digits(tail)
    if uni is None:
        uni = _digits(row.get('universe'))
    if addr is None:
        addr = _digits(row.get('address'))
    return uni, addr


# ── verbs: discovery ───────────────────────────────────────────────────────

def find_objects(p):
    """Find objects by VW criteria string; returns UUIDs + a count.

    The generic entry point the Spotlight verbs build on: any criteria the
    Vectorworks worksheet engine accepts works here, e.g.
    "(PON='Lighting Device')", "((R in ['Part Info']))", "C='Rigging'",
    "SEL=TRUE". Returns the UUID (`object_id`) every other tool takes.
    """
    crit = (p.get('criteria') or 'ALL').strip()
    limit = int(p.get('limit') or 500)
    hs = _c._collect(crit, limit)
    out = []
    for h in hs:
        row = _c._summary(h)
        t = row.get('type')
        if t == 86:
            row['plugin'] = _pio_record_name(h)
        out.append(row)
    return {'criteria': crit, 'count': len(out),
            'truncated': len(out) >= limit, 'objects': out}


def get_spotlight_devices(p):
    """List Lighting Devices with their patch/focus fields.

    params: criteria, position, limit, raw (all record fields per device).
    """
    hs, strategy = _devices(p)
    keys, source, unresolved = _keys_for(hs)
    ftypes = {}
    if hs:
        ftypes = {name: t for _i, name, t, _f in _field_names(hs[0])}
    rows = [_device_row(h, keys, ftypes, p.get('raw')) for h in hs]
    res = {'count': len(rows), 'strategy': strategy, 'catalog': source,
           'devices': rows}
    if unresolved:
        # Honest about what this document does not expose — an empty field and
        # a field that does not exist must not look the same.
        res['unresolved'] = unresolved
    if source == 'fallback':
        res['warning'] = ('no parametric record readable — field names are '
                          'best-effort. Run dump_spotlight_params once against '
                          'a document containing a Lighting Device.')
    return res


def get_spotlight_device(p):
    """Everything one Lighting Device exposes: mapped fields, raw fields,
    cells and accessories. params: object_id."""
    h = _c._h(p.get('object_id'))
    if not h:
        return {'error': 'Object not found'}
    if not _is_lighting_device(h):
        return {'error': 'Not a Lighting Device (no cells)',
                'record': _pio_record_name(h),
                'object_id': p.get('object_id')}
    fields = _field_names(h)
    keys, source, unresolved = _keys_for([h])
    ftypes = {name: t for _i, name, t, _f in fields}
    row = _device_row(h, keys, ftypes, True)
    row['catalog'] = source
    row['field_count'] = len(fields)
    if unresolved:
        row['unresolved'] = unresolved
    row['accessories'] = _accessories_of(h, keys)
    return row


def _accessories_of(h, keys=None):
    """Per-cell accessory list with 2D/3D placement."""
    if keys is None:
        keys = _keys_for([h])[0]
    out = []
    for cell in range(_cells(h)):
        n = _accessory_count(h, cell)
        accs = []
        for acc in range(n):
            entry = {'index': acc}
            # Both return a flat tuple (x, y[, z], rotation…) with no ok-flag;
            # _nums keeps the numbers and drops nothing else.
            pos2 = _c._safe(lambda: vs.LDevice_GetAccPos2D(h, cell, acc))
            if pos2:
                entry['pos2d'] = _c._nums(pos2)
            pos3 = _c._safe(lambda: vs.LDevice_GetAccPos3D(h, cell, acc))
            if pos3:
                entry['pos3d'] = _c._nums(pos3)
            for logical in ('symbol_name', 'accessory', 'device_type', 'purpose'):
                name = keys.get(logical)
                if name:
                    v = _read_param(h, cell, acc, name)
                    if v not in (None, ''):
                        entry[logical] = v
            accs.append(entry)
        out.append({'cell': cell, 'count': n, 'accessories': accs})
    return out


def get_spotlight_accessories(p):
    """Accessory inventory across the selected devices (or one device)."""
    if p.get('object_id'):
        h = _c._h(p.get('object_id'))
        if not h:
            return {'error': 'Object not found'}
        hs = [h]
    else:
        hs, _s = _devices(p)
    keys = _keys_for(hs)[0]
    devices, total = [], 0
    for h in hs:
        acc = _accessories_of(h, keys)
        n = sum(c['count'] for c in acc)
        total += n
        devices.append({'object_id': _c._oid(h),
                        'name': _c._safe(lambda h=h: vs.GetName(h)),
                        'count': n, 'cells': acc})
    return {'devices': len(devices), 'accessories': total, 'detail': devices}


def get_spotlight_positions(p):
    """Devices grouped by hanging position, with counts and bounds."""
    hs, strategy = _devices(p)
    keys, source, unresolved = _keys_for(hs)
    ftypes = {name: t for _i, name, t, _f in (_field_names(hs[0]) if hs else [])}
    groups = {}
    for h in hs:
        name = str(_read_param(h, 0, -1, keys.get('position', 'position'),
                               ftypes.get(keys.get('position', ''))) or '').strip()
        g = groups.setdefault(name or '(none)', {'position': name or '(none)',
                                                 'count': 0, 'devices': []})
        g['count'] += 1
        if len(g['devices']) < 200:
            g['devices'].append(_c._oid(h))
    out = sorted(groups.values(), key=lambda g: (-g['count'], g['position']))
    res = {'count': len(out), 'catalog': source, 'strategy': strategy,
           'positions': out}
    if unresolved:
        res['unresolved'] = unresolved
    return res


def get_spotlight_patch(p):
    """Patch sheet: one row per device plus the conflicts a patch sheet exists
    to catch (duplicate channel, duplicate universe/address, missing values)."""
    hs, strategy = _devices(p)
    keys, source, unresolved = _keys_for(hs)
    ftypes = {name: t for _i, name, t, _f in (_field_names(hs[0]) if hs else [])}
    rows = []
    for h in hs:
        row = {'object_id': _c._oid(h),
               'name': _c._safe(lambda h=h: vs.GetName(h)),
               'layer': _c._safe(lambda h=h: vs.GetLName(vs.GetLayer(h)))}
        for logical in _PATCH_KEYS:
            name = keys.get(logical)
            if name:
                row[logical] = _read_param(h, 0, -1, name, ftypes.get(name))
        uni, addr = _universe_address(row)
        row['universe_num'], row['address_num'] = uni, addr
        fp = _int(row.get('dmx_footprint'), 1) or 1
        row['footprint'] = fp
        if addr is not None:
            row['address_range'] = [addr, addr + fp - 1]
        rows.append(row)

    by_channel, by_slot, overlaps = {}, {}, []
    for row in rows:
        ch = _int(row.get('channel'))
        if ch is not None:
            by_channel.setdefault(ch, []).append(row['object_id'])
        if row.get('address_num') is not None:
            key = (row.get('universe_num') or 0, row['address_num'])
            by_slot.setdefault(key, []).append(row['object_id'])
    # Address-range overlaps (a footprint that collides with another device).
    used = {}
    for row in rows:
        if row.get('address_num') is None:
            continue
        uni = row.get('universe_num') or 0
        for a in range(row['address_num'], row['address_num'] + row['footprint']):
            other = used.get((uni, a))
            if other and other != row['object_id']:
                overlaps.append({'universe': uni, 'address': a,
                                 'objects': [other, row['object_id']]})
            used[(uni, a)] = row['object_id']

    conflicts = {
        'duplicate_channel': [{'channel': ch, 'objects': ids}
                              for ch, ids in sorted(by_channel.items())
                              if len(ids) > 1],
        'duplicate_address': [{'universe': k[0], 'address': k[1], 'objects': ids}
                              for k, ids in sorted(by_slot.items())
                              if len(ids) > 1],
        'address_overlap': overlaps[:200],
        'missing_channel': [r['object_id'] for r in rows
                            if _int(r.get('channel')) is None],
        'missing_address': [r['object_id'] for r in rows
                            if r.get('address_num') is None],
    }
    conflicts['unpatchable'] = len(conflicts['missing_channel'])
    res = {'count': len(rows), 'catalog': source, 'strategy': strategy,
           'devices': rows, 'conflicts': conflicts}
    if unresolved:
        res['unresolved'] = unresolved
    return res


def get_spotlight_focus(p):
    """Devices grouped by focus, with colour/gobo per device (the focus chart)."""
    hs, strategy = _devices(p)
    keys, source, unresolved = _keys_for(hs)
    ftypes = {name: t for _i, name, t, _f in (_field_names(hs[0]) if hs else [])}
    groups = {}
    for h in hs:
        focus = str(_read_param(h, 0, -1, keys.get('focus', 'focus'),
                                ftypes.get(keys.get('focus', ''))) or '').strip()
        g = groups.setdefault(focus or '(none)',
                              {'focus': focus or '(none)', 'count': 0,
                               'devices': []})
        g['count'] += 1
        if len(g['devices']) < 200:
            entry = {'object_id': _c._oid(h),
                     'name': _c._safe(lambda h=h: vs.GetName(h))}
            for logical in ('position', 'channel', 'color', 'gobo',
                            'pan', 'tilt', 'purpose'):
                name = keys.get(logical)
                if name:
                    v = _read_param(h, 0, -1, name, ftypes.get(name))
                    if v not in (None, ''):
                        entry[logical] = v
            g['devices'].append(entry)
    out = sorted(groups.values(), key=lambda g: (-g['count'], g['focus']))
    res = {'count': len(out), 'catalog': source, 'strategy': strategy,
           'focus_groups': out}
    if unresolved:
        res['unresolved'] = unresolved
    return res


# ── verbs: parameter catalog ───────────────────────────────────────────────

def get_spotlight_params(p):
    """The Lighting Device parameter catalog (universal names + types).

    Reads vwx-plugin/spotlight_params.json. `live: true` re-enumerates from the
    devices in the current document instead (same work as the dump, without
    writing the file) — use it to check a catalog against a localized install.
    """
    if p.get('live'):
        hs, strategy = _devices({'limit': p.get('limit') or 50,
                                 'criteria': p.get('criteria')})
        if not hs:
            return {'error': 'No Lighting Device in the active document',
                    'hint': 'Place one, or pass criteria.'}
        return _catalog_from(hs, write=False)
    cat = _load_catalog(force=True)
    if not cat:
        return {'error': 'spotlight_params.json not found',
                'path': PARAMS_PATH,
                'hint': 'Run dump_spotlight_params against a document that '
                        'contains a Lighting Device.'}
    return cat


def dump_spotlight_params(p):
    """Enumerate the Lighting Device parameter catalog from the live document
    and write vwx-plugin/spotlight_params.json.

    The prerequisite for every other Spotlight verb: it is the only way to know
    the universal names (worksheet names) that LDevice_GetParam* addresses.
    params: limit (devices to sample, default 50), path (override output).
    """
    hs, strategy = _devices({'limit': p.get('limit') or 50,
                             'criteria': p.get('criteria')})
    if not hs:
        return {'error': 'No Lighting Device in the active document',
                'strategy': strategy,
                'hint': 'Open a plot (or place a Lighting Device) and retry — '
                        'the catalog is read from a real object.'}
    out_path = p.get('path') or PARAMS_PATH
    return _catalog_from(hs, write=True, path=out_path, strategy=strategy)


def _sample_value(h, rec_name, field):
    """One sample value through the record API.

    Deliberately NOT LDevice_GetParam*: that needs a cell (and accessory) index
    and an engine error there takes Vectorworks down instead of raising, so the
    catalog is read the boring way.
    """
    if not rec_name:
        return None
    return _c._safe(lambda: vs.GetRField(h, rec_name, field))


def _catalog_from(hs, write, path=None, strategy='criteria'):
    """Union of the record fields across devices, with one sample value each."""
    fields, order, seen = {}, [], set()
    per_device = []
    for h in hs:
        names = _field_names(h)
        rec_name = _pio_record_name(h)
        per_device.append(len(names))
        for _i, name, ftype, flag in names:
            if name not in seen:
                seen.add(name)
                order.append(name)
                fields[name] = {'name': name, 'type': ftype, 'flag': flag,
                                'type_name': {1: 'integer', 2: 'boolean',
                                              3: 'real', 4: 'text'}.get(ftype, 'other'),
                                'devices': 0, 'sample': None}
            fields[name]['devices'] += 1
            if fields[name]['sample'] in (None, ''):
                v = _sample_value(h, rec_name, name)
                if v not in (None, ''):
                    fields[name]['sample'] = v
    keys, unresolved = _resolve_keys(order)
    rec_names = sorted({_pio_record_name(h) for h in hs if _pio_record_name(h)})
    cat = {
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'verified': True,
        'source': 'vs.GetParametricRecord + NumFields/GetFldName/GetFldType',
        'strategy': strategy,
        'vw_version': _c._safe(lambda: list(vs.GetVersion())),
        'document': _c._safe(vs.GetFName),
        'plugin_names': rec_names,
        'record_name': rec_names[0] if rec_names else None,
        'devices_sampled': len(hs),
        'fields_per_device': per_device,
        'field_count': len(order),
        'fields': [fields[n] for n in order],
        'keys': keys,
        'unresolved_keys': unresolved,
    }
    if write:
        try:
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(cat, f, indent=1, ensure_ascii=False)
            os.replace(tmp, path)
            cat['written'] = path
            _catalog_cache['mtime'] = None       # force a reload next read
        except Exception as e:
            cat['write_error'] = str(e)
    return cat


# ── writes: journal ────────────────────────────────────────────────────────
#
# A write verb that cannot be undone is not usable on a real plot: the designer
# has spent hours on those numbers, and Vectorworks' own undo is one level deep
# and dies with the document. So every write goes through `_apply`, which
#
#   1. reads the current value of every field it is about to touch,
#   2. writes, resets, and reads back (a SetRField that silently no-ops is the
#      failure mode this whole file exists to avoid),
#   3. appends before/after to spotlight_journal.json,
#
# and `revert_last` replays a batch backwards. The journal is per document: a
# UUID from another file addresses nothing here, so a mismatch is refused
# instead of half-restored.

JOURNAL_PATH = os.path.join(_HERE, 'spotlight_journal.json')
JOURNAL_KEEP = 20


def _journal_load():
    try:
        with open(JOURNAL_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('batches'), list):
            return data
    except Exception:
        pass
    return {'batches': []}


def _journal_save(data):
    batches = data.get('batches') or []
    data['batches'] = batches[-JOURNAL_KEEP:]
    try:
        tmp = JOURNAL_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, JOURNAL_PATH)
        return None
    except Exception as e:
        return str(e)


def _doc_name():
    return _c._safe(lambda: vs.GetFName()) or ''


def _batch_id():
    return (time.strftime('%Y%m%d-%H%M%S') + '-'
            + ('%04x' % (int(time.time() * 1000) % 0x10000)))


def _num(v):
    try:
        return float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None


def _same(a, b):
    """Semantic equality for a read-back check.

    Vectorworks normalizes on reset ('1/001' -> '1/1', '01' -> '1'), so a strict
    string compare would report a successful write as failed. Numbers compare as
    numbers, 'U/A' pairs as pairs, everything else case/space-insensitively.
    """
    if a is None or b is None:
        return a is b
    sa, sb = str(a).strip(), str(b).strip()
    if sa == sb:
        return True
    if '/' in sa and '/' in sb:
        pa = [x.strip() for x in sa.split('/')]
        pb = [x.strip() for x in sb.split('/')]
        return len(pa) == len(pb) and all(_same(x, y) for x, y in zip(pa, pb))
    na, nb = _num(sa), _num(sb)
    if na is not None and nb is not None:
        return abs(na - nb) < 1e-9
    return sa.casefold() == sb.casefold()


def _apply(h, record, writes, entries, dry_run=False):
    """Write {field: value} on one object, verify, journal into `entries`.

    Returns {field: item}. `writes` is ordered, so a caller can rely on Channel
    being set before UniverseAddress (independent, but the journal reads better
    in that order).
    """
    out = {}
    todo = []
    for field, value in writes.items():
        before = _c._safe(lambda f=field: vs.GetRField(h, record, f))
        if value is None:
            # Writing None would store the string "None" in the record.
            out[field] = {'object_id': _c._oid(h), 'record': record,
                          'field': field, 'before': before, 'after': None,
                          'ok': False, 'error': 'refusing to write None'}
            continue
        item = {'object_id': _c._oid(h), 'record': record, 'field': field,
                'before': before, 'after': str(value)}
        if dry_run:
            item['ok'] = True
            item['dry_run'] = True
        else:
            try:
                vs.SetRField(h, record, field, str(value))
                todo.append(field)
            except Exception as e:
                item['ok'] = False
                item['error'] = 'SetRField failed: %s' % e
        out[field] = item
        entries.append(item)
    if todo and not dry_run:
        try:
            vs.ResetObject(h)          # VW applies record values on reset
        except Exception:
            pass
        for field in todo:
            item = out[field]
            back = _c._safe(lambda f=field: vs.GetRField(h, record, f))
            item['readback'] = back
            item['ok'] = _same(back, item['after'])
            if not item['ok']:
                item['error'] = 'read-back differs (the write did not take)'
    return out


def _map_fields(fields, keys, skipped):
    """({universal name: value}, {universal name: logical key}).

    The caller thinks in logical keys (`channel`), the record in universal names
    (`Channel`); the label map is what lets a result speak the caller's language
    while the journal keeps the name that actually got written.
    """
    out, labels = {}, {}
    known = set(keys.values())
    for logical, value in fields.items():
        name = keys.get(logical) or (logical if logical in known else None)
        if not name or not _valid_name(name):
            skipped.append({'field': logical, 'reason': 'no universal name'})
            continue
        out[name] = value
        labels[name] = logical if logical in keys else name
    return out, labels


def _resolve_writes(p, hs, keys):
    """(per-object {universal: value}, skipped, {universal: logical})."""
    by_uuid = {_c._oid(h): h for h in hs}
    skipped, plan, labels = [], {}, {}
    assignments = p.get('assignments')
    if assignments:
        for a in assignments or []:
            oid = str(a.get('object_id') or '')
            if oid not in by_uuid:
                skipped.append({'object_id': oid, 'reason': 'not selected'})
                continue
            mapped, lab = _map_fields(a.get('fields') or {}, keys, skipped)
            plan.setdefault(oid, {}).update(mapped)
            labels.update(lab)
        return plan, skipped, labels
    fields = p.get('fields')
    if not isinstance(fields, dict) or not fields:
        return None, skipped, labels
    mapped, labels = _map_fields(fields, keys, skipped)
    for oid in by_uuid:
        plan[oid] = dict(mapped)
    return plan, skipped, labels


def _selected(p):
    """Devices for a write: explicit object_ids win over criteria."""
    ids = p.get('object_ids')
    if ids:
        hs = []
        for oid in ids:
            h = _c._safe(lambda o=oid: vs.GetObjectByUuid(str(o)))
            if h and _is_lighting_device(h):
                hs.append(h)
        return hs, 'object_ids'
    return _devices(p)


def _finish_batch(out, batch, dry):
    """Journal a batch and attach the revert handle to the result dict."""
    if dry:
        return out
    if not batch['entries']:
        out['error'] = 'nothing written'
        return out
    data = _journal_load()
    data['batches'].append(batch)
    err = _journal_save(data)
    out['journal'] = JOURNAL_PATH
    if err:
        out['journal_error'] = err
        out['warning'] = ('changes are NOT revertable: the journal could not be '
                          'written (%s)' % err)
    return out


def set_spotlight_patch(p):
    """Write patch/focus fields on Lighting Devices, with a before-value journal.

    params:
      object_ids   explicit selection (otherwise `criteria`, default all devices)
      fields       {logical_key: value} applied to every selected device
      assignments  [{object_id, fields}] for per-device values
      dry_run      true = report what would change, write nothing
      limit        device cap (default 500)

    Logical keys are the ones the read verbs return (channel, universe_address,
    position, focus, color, gobo, dimmer, circuit, mark, system, purpose,
    unit_number, ...). A key with no universal name is reported in `skipped`
    rather than written to a guessed field.

    Every write is read back: a SetRField that does not take is reported as
    `ok: false` with the value the object actually has. The returned batch id is
    what `revert_last` takes.
    """
    hs, strategy = _selected(p)
    if not hs:
        return {'error': 'No Lighting Device selected', 'strategy': strategy}
    keys, source, unresolved = _keys_for(hs)
    plan, skipped, labels = _resolve_writes(p, hs, keys)
    if plan is None:
        return {'error': 'pass `fields` or `assignments`',
                'fields': sorted(keys), 'catalog': source}
    dry = bool(p.get('dry_run'))
    batch = {'batch_id': _batch_id(), 'ts': time.time(),
             'verb': 'set_spotlight_patch', 'document': _doc_name(),
             'dry_run': dry, 'reverted': False, 'entries': []}
    devices, written = [], 0
    for h in hs:
        oid = _c._oid(h)
        writes = plan.get(oid)
        if not writes:
            continue
        record = _pio_record_name(h)
        if not record:
            devices.append({'object_id': oid, 'ok': False,
                            'error': 'not a plug-in object'})
            continue
        res = _apply(h, record, writes, batch['entries'], dry_run=dry)
        written += sum(1 for i in res.values() if i.get('ok'))
        devices.append({'object_id': oid,
                        'ok': all(i.get('ok') for i in res.values()),
                        'fields': {labels.get(f, f): {'field': f,
                                                      'before': i['before'],
                                                      'after': i['after'],
                                                      'readback': i.get('readback'),
                                                      'ok': i.get('ok')}
                                   for f, i in res.items()}})
    out = {'batch_id': batch['batch_id'], 'dry_run': dry, 'catalog': source,
           'strategy': strategy, 'count': len(devices), 'written': written,
           'ok': all(d.get('ok') for d in devices), 'devices': devices}
    if skipped:
        out['skipped'] = skipped
    if unresolved:
        out['unresolved'] = unresolved
    return _finish_batch(out, batch, dry)


def _order_devices(hs, order):
    """Stable ordering for a renumber: the order a plot is read in."""
    order = (order or 'x').lower()
    if order in ('x', 'y'):
        axis = 'x' if order == 'x' else 'y'
        return sorted(hs, key=lambda h: _geom(h).get(axis) or 0.0)
    if order == 'name':
        return sorted(hs, key=lambda h: str(_c._safe(lambda: vs.GetName(h)) or ''))
    if order in ('channel', 'address'):
        keys, _src, _un = _keys_for(hs)
        name = keys.get('channel' if order == 'channel' else 'universe_address')

        def key(h):
            v = _read_param(h, 0, -1, name) if name else None
            if order == 'channel':
                return _int(v, 10 ** 9)
            uni, addr = _universe_address({'universe_address': v})
            return (uni or 0, addr if addr is not None else 10 ** 9)
        return sorted(hs, key=key)
    return list(hs)


def renumber_spotlight(p):
    """Sequential channel + DMX renumber across a selection (one undo step).

    params:
      criteria / object_ids   what to renumber (default: all devices)
      order                   x (default, left to right), y, name, channel, address
      start_channel, channel_step        default 1, 1
      start_universe, start_address      default 1, 1
      universe_size                      default 512
      footprint_key                      default 'dmx_footprint'
      dry_run                            report only

    Addresses step by each device's footprint (its DMX channel count) and roll
    over to the next universe when a fixture would not fit — the arithmetic a
    patch sheet has to get right and a human gets wrong at 2 a.m.
    """
    hs, strategy = _selected(p)
    if not hs:
        return {'error': 'No Lighting Device selected', 'strategy': strategy}
    hs = _order_devices(hs, p.get('order'))
    keys, source, unresolved = _keys_for(hs)
    ftypes = {name: t for _i, name, t, _f in _field_names(hs[0])}
    ch_name = keys.get('channel')
    ua_name = keys.get('universe_address') or keys.get('address')
    if not ch_name or not ua_name:
        return {'error': 'cannot address Channel/UniverseAddress on these devices',
                'resolved': sorted(keys), 'unresolved': unresolved}
    ch = _int(p.get('start_channel'), 1)
    step = _int(p.get('channel_step'), 1) or 1
    uni = _int(p.get('start_universe'), 1) or 1
    addr = _int(p.get('start_address'), 1) or 1
    size = _int(p.get('universe_size'), 512) or 512
    fp_name = keys.get(p.get('footprint_key') or 'dmx_footprint')
    dry = bool(p.get('dry_run'))
    batch = {'batch_id': _batch_id(), 'ts': time.time(),
             'verb': 'renumber_spotlight', 'document': _doc_name(),
             'dry_run': dry, 'reverted': False, 'entries': []}
    devices, rows = [], []
    for h in hs:
        fp = _int(_read_param(h, 0, -1, fp_name, ftypes.get(fp_name))) if fp_name else 1
        fp = max(1, fp or 1)
        if addr + fp - 1 > size:           # does not fit: next universe
            uni += 1
            addr = 1
        record = _pio_record_name(h)
        fields = {}
        ok = False
        if record:
            res = _apply(h, record, {ch_name: str(ch),
                                     ua_name: '%d/%d' % (uni, addr)},
                         batch['entries'], dry_run=dry)
            ok = all(i.get('ok') for i in res.values())
            fields = {lab: {'field': f, 'before': i['before'],
                            'after': i['after'],
                            'readback': i.get('readback'), 'ok': i.get('ok')}
                      for f, i in res.items()
                      for lab in (('channel',) if f == ch_name
                                  else ('universe_address',))}
        oid = _c._oid(h)
        devices.append({'object_id': oid, 'ok': ok, 'channel': ch,
                        'universe_address': '%d/%d' % (uni, addr),
                        'footprint': fp, 'fields': fields})
        rows.append({'object_id': oid, 'channel': ch,
                     'universe_address': '%d/%d' % (uni, addr), 'footprint': fp})
        ch += step
        addr += fp
    out = {'batch_id': batch['batch_id'], 'dry_run': dry, 'catalog': source,
           'strategy': strategy, 'order': p.get('order') or 'x',
           'count': len(devices), 'ok': all(d.get('ok') for d in devices),
           'devices': devices, 'rows': rows}
    if unresolved:
        out['unresolved'] = unresolved
    return _finish_batch(out, batch, dry)


def revert_last(p):
    """Undo the most recent Spotlight write batch from the journal.

    params: batch_id (default: the newest batch not yet reverted),
            dry_run (report the restore without writing)

    Refuses when the batch belongs to another document (a UUID from a different
    file addresses nothing here) and skips entries that already hold their
    `before` value (someone undid it by hand — restoring would re-apply it).
    """
    data = _journal_load()
    batches = data.get('batches') or []
    want = (p.get('batch_id') or '').strip()
    batch = None
    for b in reversed(batches):
        if want:
            if b.get('batch_id') == want:
                batch = b
                break
        elif not b.get('reverted') and not b.get('dry_run'):
            batch = b
            break
    if batch is None:
        return {'error': 'Batch not found' if want else 'No batch to revert',
                'batch_id': want or None,
                'available': [b.get('batch_id') for b in batches[-5:]]}
    doc = _doc_name()
    if batch.get('document') and doc and batch['document'] != doc:
        return {'error': 'Batch belongs to another document',
                'batch_document': batch['document'], 'document': doc,
                'batch_id': batch['batch_id'],
                'hint': 'Open %s and run revert_last there.' % batch['document']}
    if batch.get('reverted'):
        return {'error': 'Batch already reverted', 'batch_id': batch['batch_id'],
                'reverted_at': batch.get('reverted_at')}
    dry = bool(p.get('dry_run'))
    by_obj = {}
    for e in batch.get('entries') or []:
        by_obj.setdefault(e['object_id'], []).append(e)
    restored, failed, unchanged = [], [], []
    for oid, entries in by_obj.items():
        h = _c._safe(lambda o=oid: vs.GetObjectByUuid(str(o)))
        if not h:
            failed.append({'object_id': oid, 'error': 'object not found'})
            continue
        record = entries[0].get('record') or _pio_record_name(h)
        writes, todo = {}, []
        for e in entries:
            if e.get('before') is None:
                # The field had no value before the write; there is nothing to
                # restore, and writing the string "None" would corrupt it.
                failed.append({'object_id': oid, 'field': e['field'],
                               'error': 'no before value recorded'})
                continue
            cur = _c._safe(lambda f=e['field']: vs.GetRField(h, record, f))
            if _same(cur, e.get('before')):
                unchanged.append({'object_id': oid, 'field': e['field'],
                                  'value': cur})
                continue
            writes[e['field']] = e.get('before')
            todo.append(e)
        if not writes:
            continue
        if dry:
            for e in todo:
                restored.append({'object_id': oid, 'field': e['field'],
                                 'from': e.get('after'), 'to': e.get('before'),
                                 'ok': True, 'dry_run': True})
            continue
        res = _apply(h, record, writes, [])
        for field, item in res.items():
            row = {'object_id': oid, 'field': field, 'from': item['before'],
                   'to': item['after'], 'readback': item.get('readback'),
                   'ok': item.get('ok')}
            (restored if item.get('ok') else failed).append(row)
    out = {'batch_id': batch['batch_id'], 'verb': batch.get('verb'),
           'dry_run': dry, 'restored': len(restored),
           'failed': len(failed), 'ok': not failed, 'changes': restored}
    if failed:
        out['errors'] = failed
        out['warning'] = ('the batch is NOT marked reverted — fix the errors and '
                          'run revert_last again')
    if unchanged:
        out['already_before'] = unchanged
    if not dry and not failed:
        batch['reverted'] = True
        batch['reverted_at'] = time.time()
        err = _journal_save(data)
        if err:
            out['journal_error'] = err
    return out


# ── paperwork (M5) ─────────────────────────────────────────────────────────
#
# The deliverables a lighting designer actually hands over: channel hookup,
# instrument schedule, patch sheet, focus chart, weight report. Each is the
# same device data in a different order and column set, so they share one
# definition table and one builder.
#
# Two rules, both learned the hard way:
#
#   * the column formulas use the **universal names resolved from the live
#     record** (`_keys_for`), never hardcoded ones — a wrong field name in a
#     worksheet is an empty column, which looks exactly like an empty plot;
#   * after building, the sheet is **read back and compared** with the same
#     data the JSON report returns. A worksheet that silently shows nothing is
#     the failure mode this file exists to prevent, and only a read-back
#     catches it (VW's first RecalculateWS can leave subrows empty).

_REPORTS = {
    'channel_hookup': {
        'title': 'Channel Hookup',
        'columns': [('Ch', 'channel', 20), ('Dim', 'dimmer', 16),
                    ('U/A', 'universe_address', 30), ('Pos', 'position', 40),
                    ('Unit', 'unit_number', 22), ('Type', 'device_type', 90),
                    ('Purpose', 'purpose', 80), ('Color', 'color', 20),
                    ('Gobo', 'gobo', 40), ('Focus', 'focus', 40)],
    },
    'instrument_schedule': {
        'title': 'Instrument Schedule',
        'columns': [('Pos', 'position', 40), ('Unit', 'unit_number', 22),
                    ('Type', 'device_type', 90), ('Ch', 'channel', 20),
                    ('U/A', 'universe_address', 30), ('Dim', 'dimmer', 16),
                    ('Purpose', 'purpose', 80), ('Weight', 'weight', 45)],
    },
    'patch_sheet': {
        'title': 'Patch Sheet',
        'columns': [('U/A', 'universe_address', 30), ('Ch', 'channel', 20),
                    ('Type', 'device_type', 90), ('DMX Ch', 'dmx_footprint', 18),
                    ('Pos', 'position', 40), ('Circuit', 'circuit', 25),
                    ('Dimmer', 'dimmer', 16)],
    },
    'focus_chart': {
        'title': 'Focus Chart',
        'columns': [('Focus', 'focus', 45), ('Pos', 'position', 40),
                    ('Ch', 'channel', 20), ('Type', 'device_type', 90),
                    ('Color', 'color', 20), ('Gobo', 'gobo', 40),
                    ('Purpose', 'purpose', 80)],
    },
    'weight_report': {
        'title': 'Weight Report',
        'columns': [('Pos', 'position', 40), ('Unit', 'unit_number', 22),
                    ('Type', 'device_type', 90), ('Ch', 'channel', 20),
                    ('Weight', 'weight', 45), ('Power', 'power', 40)],
    },
}


def _measure(v):
    """Leading number of a measurement string ('12,5 kg' -> 12.5, '' -> None).

    VW stores weight/power as localized text with a unit suffix, so a sum needs
    the number pulled out — and a comma decimal separator on a German install.
    """
    if v is None:
        return None
    s = str(v).strip().replace('\u00a0', ' ')
    if not s:
        return None
    m = re.match(r'^[^\d\-+]*([-+]?\d+(?:[.,]\d+)?)', s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', '.'))
    except ValueError:
        return None


def _report_def(kind):
    kind = (kind or 'channel_hookup').strip().lower()
    if kind not in _REPORTS:
        return None
    return kind, _REPORTS[kind]


def _report_rows(kind, hs, keys, ftypes):
    """[{object_id, <logical key>: value, ...}] in document order."""
    rows = []
    for h in hs:
        row = {'object_id': _c._oid(h)}
        for _header, logical, _w in _REPORTS[kind]['columns']:
            name = keys.get(logical)
            row[logical] = (_read_param(h, 0, -1, name, ftypes.get(name))
                            if name else None)
        if kind == 'weight_report':
            row['weight_kg'] = _measure(row.get('weight'))
            row['power_w'] = _measure(row.get('power'))
        rows.append(row)
    return rows


def _sort_rows(rows, key):
    """Sort by a logical key, numbers before text, blanks last."""
    if not key:
        return rows

    def sort_key(row):
        v = row.get(key)
        n = _num(v)
        if n is not None:
            return (0, n, '')
        s = str(v or '').strip()
        return (1 if s else 2, 0.0, s)
    return sorted(rows, key=sort_key)


def _weight_summary(rows):
    """Per-position totals — the number a rigger asks for first."""
    groups = {}
    for row in rows:
        pos = str(row.get('position') or '').strip() or '(no position)'
        g = groups.setdefault(pos, {'position': pos, 'count': 0,
                                    'weight_kg': 0.0, 'power_w': 0.0,
                                    'weighted': 0, 'powered': 0})
        g['count'] += 1
        if row.get('weight_kg') is not None:
            g['weight_kg'] += row['weight_kg']
            g['weighted'] += 1
        if row.get('power_w') is not None:
            g['power_w'] += row['power_w']
            g['powered'] += 1
    out = []
    for pos in sorted(groups):
        g = groups[pos]
        g['weight_kg'] = round(g['weight_kg'], 3)
        g['power_w'] = round(g['power_w'], 1)
        out.append(g)
    return out


def get_spotlight_report(p):
    """The data behind a paperwork sheet, as JSON (no worksheet needed).

    params: kind (channel_hookup | instrument_schedule | patch_sheet |
                  focus_chart | weight_report), criteria, limit, sort_by

    Same rows the worksheet gets, so a caller can print, diff or archive a
    report without touching the document. `weight_report` adds `weight_kg` /
    `power_w` per device and `by_position` totals.
    """
    found = _report_def(p.get('kind'))
    if not found:
        return {'error': 'unknown kind', 'kinds': sorted(_REPORTS)}
    kind, spec = found
    hs, strategy = _devices(p)
    if not hs:
        return {'kind': kind, 'count': 0, 'strategy': strategy,
                'devices': [], 'columns': [h for h, _k, _w in spec['columns']]}
    keys, source, unresolved = _keys_for(hs)
    ftypes = {name: t for _i, name, t, _f in _field_names(hs[0])}
    rows = _report_rows(kind, hs, keys, ftypes)
    out = {'kind': kind, 'title': spec['title'], 'count': len(rows),
           'strategy': strategy, 'catalog': source,
           'columns': [h for h, _k, _w in spec['columns']],
           'devices': _sort_rows(rows, p.get('sort_by'))}
    if kind == 'weight_report':
        out['by_position'] = _weight_summary(rows)
    if unresolved:
        out['unresolved'] = unresolved
    return out


def _ws_cell_text(ws, row, col, subrow):
    return _c._safe(lambda: vs.GetWSSubrowCellString(ws, row, col, subrow))


def _verify_sheet(ws, db_row, columns, expected):
    """Compare every worksheet column against the report data.

    Multiset comparison per column: subrow order is VW's business (document
    order), but the *set* of values must match exactly. Returns
    (verified, per-column detail) with up to three examples per column.
    """
    subrows = _c._safe(lambda: vs.GetWSSubrowCount(ws, db_row)) or 0
    if isinstance(subrows, tuple):
        subrows = subrows[0] if subrows else 0
    detail, ok = [], True
    for idx, (_header, logical, _w) in enumerate(columns, start=1):
        got = [_ws_cell_text(ws, db_row, idx, s) for s in range(1, subrows + 1)]
        want = [str(r.get(logical) if r.get(logical) is not None else '')
                for r in expected]
        got_n = sorted(g.strip() for g in got if g is not None)
        want_n = sorted(w.strip() for w in want)
        same = len(got_n) == len(want_n) and all(
            _same(a, b) for a, b in zip(got_n, want_n))
        ok = ok and same
        entry = {'column': _header, 'key': logical, 'ok': same,
                 'filled': sum(1 for g in got_n if g)}
        if not same:
            entry['expected'] = want_n[:3]
            entry['got'] = got_n[:3]
        detail.append(entry)
    return ok, subrows, detail


def spotlight_worksheet(p):
    """Build a real Vectorworks worksheet for a paperwork deliverable.

    params:
      kind      channel_hookup (default) | instrument_schedule | patch_sheet |
                focus_chart | weight_report
      name      worksheet name (default: the report title; must not exist)
      criteria  which devices (default: all Lighting Devices)
      sort_by   logical key to sort the rows by (e.g. 'position', 'channel')
      place     true = also place it on the drawing
      x, y      placement point (default 0,0)
      verify    default true: read every cell back and compare

    The column formulas are built from the universal names the live record
    reports, so a localized Vectorworks still produces filled columns. The
    read-back comparison is the point: `verified: false` with a per-column
    `detail` means the sheet on screen does not match the plot.
    """
    found = _report_def(p.get('kind'))
    if not found:
        return {'error': 'unknown kind', 'kinds': sorted(_REPORTS)}
    kind, spec = found
    hs, strategy = _devices(p)
    if not hs:
        return {'error': 'No Lighting Device selected', 'strategy': strategy}
    keys, source, unresolved = _keys_for(hs)
    ftypes = {name: t for _i, name, t, _f in _field_names(hs[0])}
    record = _pio_record_name(hs[0])
    if not record:
        return {'error': 'not a plug-in object (no parametric record)'}

    name = (p.get('name') or spec['title']).strip()
    old = _c._safe(lambda: vs.GetObject(name))
    if old and _c._safe(lambda: vs.GetTypeN(old)) != 0:
        return {'error': "worksheet '%s' already exists — pick another name" % name,
                'hint': 'delete it first, or pass name="<something else>"'}

    columns = spec['columns']
    ws = vs.CreateWS(name, 2, len(columns))
    if not ws:
        return {'error': 'CreateWS failed'}
    for idx, (header, logical, width) in enumerate(columns, start=1):
        vs.SetWSCellFormula(ws, 1, idx, 1, idx, header)
        field = keys.get(logical)
        if field:
            vs.SetWSCellFormula(ws, 2, idx, 2, idx,
                                "='%s'.'%s'" % (record, field))
        _c._safe(lambda w=width, i=idx: vs.SetWSColumnWidth(ws, i, i, w))
    # Row 2 column 0 binds the row to the criteria database.
    vs.SetWSCellFormula(ws, 2, 0, 2, 0, '=DATABASE(%s)' % _criteria(p))
    vs.RecalculateWS(ws)

    expected = _report_rows(kind, hs, keys, ftypes)
    expected = _sort_rows(expected, p.get('sort_by'))
    out = {'kind': kind, 'worksheet': name, 'columns': len(columns),
           'devices': len(expected), 'strategy': strategy, 'catalog': source}
    if unresolved:
        out['unresolved'] = unresolved
    if p.get('verify', True):
        ok, subrows, detail = _verify_sheet(ws, 2, columns, expected)
        if not subrows:
            # VW's first recalc can leave a fresh database row empty.
            vs.RecalculateWS(ws)
            ok, subrows, detail = _verify_sheet(ws, 2, columns, expected)
        out.update({'subrows': subrows, 'verified': ok, 'detail': detail})
        if not ok:
            out['warning'] = ('the worksheet does not match the plot — see '
                              'detail; the columns are empty or shifted')
    else:
        sub = _c._safe(lambda: vs.GetWSSubrowCount(ws, 2))
        out['subrows'] = sub
    if p.get('place'):
        img = vs.CreateWSImage(ws, (float(p.get('x') or 0),
                                    float(p.get('y') or 0)))
        out['image_id'] = _c._oid(img) if img else None
    return out


def _criteria(p):
    crit = (p.get('criteria') or '').strip()
    if crit:
        return crit
    return "((PON='%s'))" % _DEFAULT_PLUGIN_NAME
