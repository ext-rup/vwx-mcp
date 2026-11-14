"""commands_braceworks.py — Braceworks rigging verbs (M6).

Registered through `vwx_verbs.MODULES`, like the other fork modules.

WHAT IS ACTUALLY THERE (verified live on VW2027, 2026-11-14)
-----------------------------------------------------------
Braceworks ships as `BraceWorxsVwxPlg.vlb` and exposes almost nothing through
the SDK: `HO_GetNumHoistOrigin`, `HO_GetHoistOriginAt`, `HO_GetHoistColorLbl`
and a pile of `OLD*` legacy calls. Everything a rigger wants is in the
parametric records instead:

    HoistVW        101 fields  MotorNumber, MotorLabel, Location, Type,
                               MaximumLoadStr, MaximumLoad, BrakeType,
                               Function, Manufacturer, HiHook, LoHook,
                               HookToHook, LoadTrim, ChainLength, Speed,
                               Phasing, Voltage, HoistWt, ChainWt, LoadWt,
                               PointLoad, ReactionForce, ReactionForceStr,
                               ControlID, ControlType, ControllerLoc,
                               RefOriginID, Notes
    Straight Truss  30 fields  Name, Index, LineLength, Profile, Connection,
                               Height, Width, Chord/Ladder/Lacing profiles,
                               DistrWeightStr, DistributedWeight, Hanging Angle
    Curved Truss    29 fields  Diameter, Total Arc, Segment Arc, Radius, ...
                               (same profile/weight fields as Straight Truss)

Note the plug-in name: the hoist is **HoistVW**, not 'Hoist'. 'Hoist' resolves
to a different, legacy object ("Hoist (Legacy)") with a small record and none
of the load fields. Reading 'Hoist' would have produced a schedule full of
blanks that looked like an empty rig.

CREATING ONE IS NOT HEADLESS
----------------------------
`vs.CreateCustomObject('HoistVW', p, 0)` pops "Object Properties: HoistVW", and
the first hoist in a document also triggers a symbol import with a "Resource
Name Conflict" dialog. Both need a button press, so a scripted rig build is a
dialog dance, not a one-liner. The READS below need none of that.

LOADS ARE LOCALIZED TEXT
------------------------
'50,00 kg', '1,3e04', '0,00 kg/m'. `_cnum` (commands_connectcad) parses them;
this module never re-implements it, so a parsing fix lands in one place.
"""
import os

import vs

import commands as _c
import commands_connectcad as _cc

_HERE = os.path.dirname(os.path.abspath(__file__))

PIO_HOIST = 'HoistVW'
PIO_TRUSS = 'Straight Truss'
PIO_TRUSS_CURVED = 'Curved Truss'

_HOIST_KEYS = {
    'number': ('MotorNumber',),
    'label': ('MotorLabel',),
    'location': ('Location',),
    'type': ('Type',),
    'max_load': ('MaximumLoad',),
    'max_load_str': ('MaximumLoadStr',),
    'brake': ('BrakeType',),
    'function': ('Function',),
    'manufacturer': ('Manufacturer',),
    'hook_height': ('HiHook',),
    'low_hook': ('LoHook',),
    'hook_to_hook': ('HookToHook',),
    'load_trim': ('LoadTrim',),
    'chain_length': ('ChainLength',),
    'speed': ('Speed',),
    'phasing': ('Phasing',),
    'voltage': ('Voltage',),
    'hoist_weight': ('HoistWt',),
    'chain_weight': ('ChainWt',),
    'load_weight': ('LoadWt',),
    'point_load': ('PointLoad',),
    'reaction_force': ('ReactionForce',),
    'reaction_force_str': ('ReactionForceStr',),
    'control_id': ('ControlID',),
    'control_type': ('ControlType',),
    'controller': ('ControllerLoc',),
    'origin': ('RefOriginID',),
    'notes': ('Notes',),
}

_TRUSS_KEYS = {
    'name': ('Name',),
    'index': ('Index',),
    'length': ('LineLength',),
    'profile': ('Profile',),
    'connection': ('Connection',),
    'height': ('Height',),
    'width': ('Width',),
    'cross_section': ('CrossSection',),
    'distributed_weight': ('DistributedWeight',),
    'distributed_weight_str': ('DistrWeightStr',),
    'hanging_angle': ('Hanging Angle',),
    'rotation': ('Rotation',),
    'message': ('Message',),
}

_CURVED_KEYS = {
    'name': ('Name',),
    'index': ('Index',),
    'diameter': ('Diameter',),
    'radius': ('Radius',),
    'total_arc': ('Total Arc',),
    'segment_arc': ('Segment Arc',),
    'profile': ('Profile',),
    'connection': ('Connection',),
    'height': ('Height',),
    'width': ('Width',),
    'distributed_weight': ('DistributedWeight',),
    'distributed_weight_str': ('DistrWeightStr',),
    'message': ('Message',),
}


def _num(v):
    """Localized number, via the ConnectCAD parser (single implementation)."""
    return _cc._cnum(v)


def _collect(pio):
    return _cc._collect(pio)


def _map(fields, keys):
    return _cc._map(fields, keys)


def _fields(h):
    return _cc._fields(h)


def _limit(p, default=500):
    return _cc._limit(p, default)


def _sort_rows(rows, key):
    return _cc._sort_rows(rows, key)


def _hoist_row(h):
    """One hoist, with the numbers a rigger checks, in kilograms.

    The record keeps two parallel values: a localized string with the unit
    ('50,00 kg') and a raw number in the document's INTERNAL mass unit — on a
    metric document that is grams, so a 1/2-ton hoist reports MaximumLoad =
    50000 next to MaximumLoadStr = '50,00 kg'. Reporting the raw number as kg
    would understate every load by 1000x, so the scale is derived from the pair
    the object itself reports, and the raw values are kept alongside.
    """
    row, unresolved = _map(_fields(h), _HOIST_KEYS)
    row['object_id'] = _c._safe(lambda: vs.GetObjectUuid(h))

    raw_max = _num(row.get('max_load'))
    str_max = _num(row.get('max_load_str'))
    scale = None
    if raw_max and str_max:
        scale = raw_max / str_max          # 1000 on a metric document
    row['mass_scale'] = scale

    load_raw = _num(row.get('point_load'))
    if load_raw is None:
        load_raw = _num(row.get('load_weight'))
    react_raw = _num(row.get('reaction_force'))

    row['max_load_raw'] = raw_max
    row['load_raw'] = load_raw
    row['reaction_force_raw'] = react_raw
    if scale:
        row['max_load_kg'] = round(str_max if str_max is not None
                                   else raw_max / scale, 4)
        row['load_kg'] = None if load_raw is None else round(load_raw / scale, 4)
        row['reaction_force_kg'] = (None if react_raw is None
                                    else round(react_raw / scale, 4))
    else:
        row['max_load_kg'] = str_max
        row['load_kg'] = None
        row['reaction_force_kg'] = None

    # A capacity check is the reason to read a rig at all. Both numbers must be
    # present to make the call — a missing capacity is reported as unknown, not
    # as "fine".
    if load_raw is not None and raw_max:
        row['load_ratio'] = round(load_raw / raw_max, 4)
        row['overloaded'] = load_raw > raw_max
    else:
        row['load_ratio'] = None
        row['overloaded'] = None
        row['capacity_known'] = False
    return row, unresolved


def get_braceworks_hoists(p):
    """Braceworks hoists with capacity, point load and reaction force.

    params: origin, function, overloaded_only, criteria, sort_by, limit, raw

    `overloaded_only: true` returns just the hoists whose point load exceeds
    their rated maximum — the list you actually want before a show.
    """
    hs, strategy = _collect(PIO_HOIST)
    want_origin = (p.get('origin') or '').strip().lower()
    want_fn = (p.get('function') or '').strip().lower()
    only_over = bool(p.get('overloaded_only'))
    rows, unresolved, raw, unknown_capacity = [], set(), {}, 0
    for h in hs:
        row, miss = _hoist_row(h)
        unresolved |= miss
        if row.get('capacity_known') is False:
            unknown_capacity += 1
        if want_origin and str(row.get('origin') or '').strip().lower() != want_origin:
            continue
        if want_fn and str(row.get('function') or '').strip().lower() != want_fn:
            continue
        if only_over and not row.get('overloaded'):
            continue
        if p.get('raw'):
            raw[row['object_id']] = _fields(h)
        rows.append(row)
    rows = _sort_rows(rows, p.get('sort_by') or 'number')[: _limit(p)]
    out = {'count': len(rows), 'hoists': rows, 'strategy': strategy,
           'catalog': 'live', 'units': _cc._units(),
           'mass_unit': 'kg',
           'total_load_kg': round(sum(r.get('load_kg') or 0.0 for r in rows), 3)}
    if unknown_capacity:
        out['capacity_unknown'] = unknown_capacity
        out['note'] = ('%d hoist(s) report no maximum load — their capacity '
                       'check is null, not "ok"' % unknown_capacity)
    if unresolved:
        out['unresolved'] = sorted(unresolved)
    if p.get('raw'):
        out['raw'] = raw
    return out


def get_braceworks_trusses(p):
    """Straight and curved trusses: length, profile, distributed weight."""
    rows, unresolved, strategy = [], set(), 'criteria'
    for pio, keys, kind in ((PIO_TRUSS, _TRUSS_KEYS, 'straight'),
                            (PIO_TRUSS_CURVED, _CURVED_KEYS, 'curved')):
        hs, strat = _collect(pio)
        if hs:
            strategy = strat
        for h in hs:
            row, miss = _map(_fields(h), keys)
            unresolved |= miss
            row['kind'] = kind
            row['object_id'] = _c._safe(lambda: vs.GetObjectUuid(h))
            row['length_num'] = _num(row.get('length'))
            row['distributed_weight_num'] = _num(row.get('distributed_weight'))
            row['weight_per_length'] = _num(row.get('distributed_weight_str'))
            rows.append(row)
    rows = _sort_rows(rows, p.get('sort_by') or 'name')[: _limit(p)]
    out = {'count': len(rows), 'trusses': rows, 'strategy': strategy,
           'catalog': 'live', 'units': _cc._units(),
           'total_length': sum(r.get('length_num') or 0.0 for r in rows)}
    if unresolved:
        out['unresolved'] = sorted(unresolved)
    return out


def get_braceworks_loads(p):
    """Load summary per hoist origin: count, total load, total capacity.

    This is the number a rigger asks for first, and the one a hoist-by-hoist
    dump makes you add up by hand. Origins come from each hoist's RefOriginID;
    hoists with no origin are grouped under '' and reported as `unassigned`.
    """
    hs, strategy = _collect(PIO_HOIST)
    groups = {}
    for h in hs:
        row, _miss = _hoist_row(h)
        key = str(row.get('origin') or '').strip()
        g = groups.setdefault(key, {
            'origin': key, 'hoists': 0, 'load': 0.0, 'capacity': 0.0,
            'reaction_force': 0.0, 'overloaded': 0, 'unknown_capacity': 0,
            'numbers': [],
        })
        g['hoists'] += 1
        if row.get('load_kg') is not None:
            g['load'] += row['load_kg']
        if row.get('max_load_kg'):
            g['capacity'] += row['max_load_kg']
        else:
            g['unknown_capacity'] += 1
        if row.get('reaction_force_kg') is not None:
            g['reaction_force'] += row['reaction_force_kg']
        if row.get('overloaded'):
            g['overloaded'] += 1
        if row.get('number'):
            g['numbers'].append(str(row['number']))

    out_rows = []
    for key, g in groups.items():
        g['load'] = round(g['load'], 3)
        g['capacity'] = round(g['capacity'], 3)
        g['reaction_force'] = round(g['reaction_force'], 3)
        g['load_ratio'] = (round(g['load'] / g['capacity'], 4)
                           if g['capacity'] else None)
        g['numbers'].sort()
        out_rows.append(g)
    out_rows.sort(key=lambda g: (g['origin'] == '', g['origin']))
    res = {'origins': len(out_rows), 'groups': out_rows, 'strategy': strategy,
           'catalog': 'live', 'units': _cc._units(), 'mass_unit': 'kg',
           'total_load': round(sum(g['load'] for g in out_rows), 3),
           'total_capacity': round(sum(g['capacity'] for g in out_rows), 3),
           'overloaded': sum(g['overloaded'] for g in out_rows)}
    if any(g['origin'] == '' for g in out_rows):
        res['unassigned'] = [g for g in out_rows if g['origin'] == ''][0]['hoists']
    return res
