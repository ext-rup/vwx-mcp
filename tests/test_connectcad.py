"""Offline tests for the M6 modules (ConnectCAD + Braceworks), no Vectorworks.

    uv run --with pytest --with fastmcp==4.0.10 --with pillow pytest tests/test_connectcad.py -q

A fake `vs` stands in for Vectorworks: parametric records over plain Python
objects, a criteria engine that understands (PON='Device'), and a worksheet
model that actually evaluates =DATABASE(...) and ='Rec'.'Field'. That covers
the logic that breaks — record mapping, localized numbers, the read-back
comparison, the mass-unit scale — without a live document.

What it cannot cover: whether the real field names are the ones the key maps
expect. Those were taken from a live VW2027 document (see the module docstrings)
and every verb reports `unresolved` rather than blanking a field.
"""
import os
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, 'vwx-plugin')
sys.path.insert(0, PLUGIN)

TEXT, INTEGER, REAL, BOOLEAN, POPUP = 4, 1, 3, 2, 8


class Obj:
    def __init__(self, uuid, rec_name, fields, types=None, name=None):
        self.uuid = uuid
        self.rec_name = rec_name
        self.fields = dict(fields)
        self.types = types or {}
        self.name = name or rec_name + '-' + uuid[-3:]

    def value(self, field):
        return self.fields.get(field)


def make_vs(objs):
    vs = types.ModuleType('vs')
    by_uuid = {o.uuid: o for o in objs}

    def _o(h):
        if isinstance(h, tuple) and h and h[0] == 'rec':
            return by_uuid[h[1]]
        return h

    vs.GetTypeN = lambda h: 86
    vs.GetParametricRecord = lambda h: ('rec', _o(h).uuid)
    vs.GetName = lambda h: (_o(h).rec_name if isinstance(h, tuple) else _o(h).name)
    vs.NumFields = lambda rec: len(_o(rec).fields)
    vs.GetFldName = lambda rec, i: list(_o(rec).fields)[i - 1]
    vs.GetFldType = lambda rec, i: _o(rec).types.get(list(_o(rec).fields)[i - 1], TEXT)
    vs.GetRField = lambda h, rec, name: _o(h).value(name) or ''
    vs.SetRField = lambda h, rec, name, v: _o(h).fields.__setitem__(name, v)
    vs.ResetObject = lambda h: True
    vs.GetObjectUuid = lambda h: _o(h).uuid
    vs.GetUnits = lambda: (1, 0, 0, 25.4, 'mm', ' sq m')
    vs.GetVersion = lambda: (2027, 0, 0, 0)
    vs.GetFName = lambda: 'Test.vwx'

    def _norm(crit):
        # VW accepts both 'ALL' and '(ALL)'; the verbs use the parenthesised
        # form, so the fake must normalise before comparing.
        return (crit or '').strip().upper().strip('()')

    def ForEachObject(cb, crit):
        c = _norm(crit)
        if c in ('ALL', ''):
            for o in objs:
                cb(o)
            return
        for o in objs:
            if "PON='%s'" % o.rec_name.upper() in c:
                cb(o)
    vs.ForEachObject = ForEachObject

    # ── worksheets ────────────────────────────────────────────────────────
    class WS:
        def __init__(self, name, rows, cols):
            self.name, self.rows, self.cols = name, rows, cols
            self.cells, self.sub = {}, {}
            self.db_row, self.matches, self.subrows = None, [], 0

    sheets = {}

    def CreateWS(name, rows, cols):
        sheets[name] = WS(name, rows, cols)
        return sheets[name]

    def SetWSCellFormula(ws, r1, c1, r2, c2, formula):
        ws.cells[(r1, c1)] = formula
        if c1 == 0 and str(formula).startswith('=DATABASE('):
            ws.db_row = r1
            crit = str(formula)[len('=DATABASE('):].rstrip(')').upper()
            ws.matches = [o for o in objs if "PON='%s'" % o.rec_name.upper() in crit]
            ws.subrows = len(ws.matches)

    def RecalculateWS(ws):
        formulas = {c: str(ws.cells.get((ws.db_row, c), ''))
                    for c in range(1, ws.cols + 1)}
        ws.sub = {}
        for s, obj in enumerate(ws.matches, start=1):
            for c, f in formulas.items():
                if f.startswith("='") and "'.'" in f:
                    ws.sub[(s, c)] = obj.value(f.split("'.'")[1].rstrip("'"))

    vs.CreateWS = CreateWS
    vs.SetWSCellFormula = SetWSCellFormula
    vs.RecalculateWS = RecalculateWS
    vs.GetWSSubrowCount = lambda ws, row: ws.subrows
    vs.GetWSSubrowCellString = lambda ws, r, c, s: (
        '' if ws.sub.get((s, c)) is None else str(ws.sub[(s, c)]))
    vs.SetWSColumnWidth = lambda ws, a, b, w: None
    vs.CreateWSImage = lambda ws, loc: Obj('img-1', 'image', {})
    vs.GetObject = lambda name: sheets.get(name)
    vs._sheets = sheets
    return vs


DEVICE_FIELDS = {
    'tag': '01', 'name': 'VJF_01', 'type': 'VideoJack', 'make': 'Crestron',
    'model': 'DM-TX', 'loc_room': '1', 'loc_rack': 'R1', 'loc_rackU': '21',
    'loc_slot': '', 'power': '12,5', 'weight': '3,25', 'BTU': '42',
    'heightU': '2', 'width_R': 'full-rack', 'modular': 'False', 'nslots': '1',
    'symbol': 'VJX_label', 'HasEquipment': 'True',
}
DEVICE_TYPES = {'symbol': POPUP, 'type': POPUP, 'power': REAL, 'weight': REAL,
                'nslots': INTEGER, 'modular': BOOLEAN}

CIRCUIT_FIELDS = {
    'Number': '1111', 'Signal': 'HDMI', 'Cable': '', 'Circuits': '1',
    'Src_Dev_Name': 'Switcher 1', 'Src_Dev_Tag': 'Switcher 1',
    'Src_Skt_Name': 'HDMI_OUT 1', 'Src_Signal': 'HDMI', 'Src_Skt_Conn': 'HDMI',
    'Src_Room': '1', 'Src_Rack': 'R1', 'Src_RackU': '21', 'Src_Slot': '',
    'Dst_Dev_Name': 'Transmitter', 'Dst_Dev_Tag': 'Transmitter',
    'Dst_Skt_Name': 'HDMI', 'Dst_Signal': 'HDMI', 'Dst_Skt_Conn': 'HDMI',
    'Dst_Room': '1', 'Dst_Rack': 'C1', 'Dst_RackU': '5', 'Dst_Slot': '4',
    'CableCalculatedLength': '4.5', 'CableLength': 'Auto',
    'CircuitType': 'polyline',
}

HOIST_FIELDS = {
    'MotorNumber': '1', 'MotorLabel': 'H1', 'Location': 'FOH',
    'Type': '1/2 Ton', 'MaximumLoad': '50000', 'MaximumLoadStr': '50,00 kg',
    'Function': 'Not Specified', 'PointLoad': '60000',
    'ReactionForce': '1000', 'RefOriginID': 'Origin A', 'Notes': '',
}


@pytest.fixture()
def cc(monkeypatch):
    """commands_connectcad against a fake vs with one device + one circuit."""
    objs = [Obj('dev-1', 'Device', DEVICE_FIELDS, DEVICE_TYPES),
            Obj('cir-1', 'Circuit', CIRCUIT_FIELDS)]
    vs = make_vs(objs)
    monkeypatch.setitem(sys.modules, 'vs', vs)
    for mod in ('commands', 'commands_spotlight', 'commands_connectcad',
                'commands_braceworks'):
        sys.modules.pop(mod, None)
    import commands_connectcad
    return commands_connectcad, vs, objs


# ── numbers ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize('raw, want', [
    ('-1,2e01', -12.0),          # localized exponent, the ConnectCAD form
    ('4,826e02', 482.6),
    ('7,252844172117577e03', 7252.844172117577),
    ('0 sq m', 0.0),
    ('1 234,5', 1234.5),
    ('1,234.5', 1234.5),         # English thousands separator
    ('', None),
    (None, None),
    ('n/a', None),
    (12, 12.0),
])
def test_cnum_localized(cc, raw, want):
    mod, _vs, _objs = cc
    assert mod._cnum(raw) == want


# ── records ───────────────────────────────────────────────────────────────

def test_devices_map_fields(cc):
    mod, _vs, _objs = cc
    out = mod.get_connectcad_devices({})
    assert out['count'] == 1
    d = out['devices'][0]
    assert d['tag'] == '01' and d['rack'] == 'R1' and d['rack_u'] == '21'
    assert d['object_id'] == 'dev-1'
    assert 'unresolved' not in out
    assert out['units']['unit'] == 'mm'


def test_devices_report_unresolved_keys(cc):
    """A record field that is not there must be named, not silently blank."""
    mod, _vs, objs = cc
    del objs[0].fields['loc_rack']
    out = mod.get_connectcad_devices({})
    assert 'rack' in out['unresolved']
    assert out['devices'][0]['rack'] is None


def test_devices_filter(cc):
    mod, _vs, _objs = cc
    assert mod.get_connectcad_devices({'room': '1'})['count'] == 1
    assert mod.get_connectcad_devices({'room': '2'})['count'] == 0
    assert mod.get_connectcad_devices({'type': 'videojack'})['count'] == 1


def test_circuits_topology(cc):
    mod, _vs, _objs = cc
    c = mod.get_connectcad_circuits({})['circuits'][0]
    assert c['source_device'] == 'Switcher 1'
    assert c['dest_rack'] == 'C1' and c['dest_slot'] == '4'
    assert c['length_num'] == 4.5


def test_circuits_filter_by_either_end(cc):
    mod, _vs, _objs = cc
    assert mod.get_connectcad_circuits({'device': 'Switcher 1'})['count'] == 1
    assert mod.get_connectcad_circuits({'device': 'Transmitter'})['count'] == 1
    assert mod.get_connectcad_circuits({'device': 'nobody'})['count'] == 0
    assert mod.get_connectcad_circuits({'signal': 'SDI'})['count'] == 0


def test_collect_falls_back_to_scan(cc):
    """A criteria engine that knows nothing about the PIO must not read as
    'no objects in the document'."""
    mod, vs, objs = cc

    def only_all(cb, crit):
        # The criteria engine does not know this plug-in, but (ALL) still works.
        if (crit or '').strip().upper().strip('()') in ('ALL', ''):
            for o in objs:
                cb(o)
    vs.ForEachObject = only_all
    out = mod.get_connectcad_devices({})
    assert out['strategy'] == 'scan'
    assert out['count'] == 1


# ── schedules + worksheets ────────────────────────────────────────────────

def test_schedule_equipment(cc):
    mod, _vs, _objs = cc
    out = mod.get_connectcad_schedule({'kind': 'equipment'})
    assert out['count'] == 1
    assert [c['key'] for c in out['columns']][:3] == ['tag', 'name', 'type']


def test_schedule_unknown_kind(cc):
    mod, _vs, _objs = cc
    out = mod.get_connectcad_schedule({'kind': 'nope'})
    assert 'error' in out and 'equipment' in out['kinds']


def test_worksheet_verified(cc):
    mod, _vs, _objs = cc
    out = mod.connectcad_worksheet({'kind': 'equipment', 'name': 'CC Test'})
    assert out['subrows'] == 1
    assert out['verified'] is True
    assert all(d['ok'] for d in out['detail'])


def test_worksheet_detects_empty_column(cc):
    """The failure mode this exists for: a sheet that silently shows nothing."""
    mod, vs, _objs = cc
    real = vs.GetWSSubrowCellString
    vs.GetWSSubrowCellString = lambda ws, r, c, s: '' if c == 1 else real(ws, r, c, s)
    out = mod.connectcad_worksheet({'kind': 'equipment', 'name': 'CC Test'})
    assert out['verified'] is False
    bad = [d for d in out['detail'] if not d['ok']]
    assert bad and bad[0]['column'] == 'Tag'


def test_worksheet_popup_column_compares_presence(cc):
    """A popup cell renders its choice label ('Video Jackfield'), not the
    stored value ('VideoJack') — that must not read as a wrong sheet."""
    mod, vs, _objs = cc
    real = vs.GetWSSubrowCellString

    def label(ws, r, c, s):
        v = real(ws, r, c, s)
        return 'Video Jackfield' if v == 'VideoJack' else v
    vs.GetWSSubrowCellString = label
    out = mod.connectcad_worksheet({'kind': 'equipment', 'name': 'CC Test'})
    type_col = [d for d in out['detail'] if d['key'] == 'type'][0]
    assert type_col['rendered'] is True
    assert out['verified'] is True


def test_worksheet_refuses_duplicate_name(cc):
    mod, _vs, _objs = cc
    mod.connectcad_worksheet({'kind': 'equipment', 'name': 'CC Test'})
    again = mod.connectcad_worksheet({'kind': 'equipment', 'name': 'CC Test'})
    assert 'already exists' in again['error']


# ── braceworks ────────────────────────────────────────────────────────────

@pytest.fixture()
def bw(monkeypatch):
    objs = [Obj('hoi-1', 'HoistVW', HOIST_FIELDS),
            Obj('hoi-2', 'HoistVW', dict(HOIST_FIELDS, MotorNumber='2',
                                         RefOriginID='', PointLoad='0')),
            Obj('tru-1', 'Straight Truss',
                {'Name': 'T1', 'LineLength': '1,5e03', 'Profile': 'Box',
                 'DistrWeightStr': '12,5 kg/m', 'DistributedWeight': '12.5'})]
    vs = make_vs(objs)
    monkeypatch.setitem(sys.modules, 'vs', vs)
    for mod in ('commands', 'commands_spotlight', 'commands_connectcad',
                'commands_braceworks'):
        sys.modules.pop(mod, None)
    import commands_braceworks
    return commands_braceworks, vs, objs


def test_hoist_mass_scale(bw):
    """MaximumLoad is in grams (50000) next to '50,00 kg' — reporting the raw
    number as kilograms would understate every load by 1000x."""
    mod, _vs, _objs = bw
    h = mod.get_braceworks_hoists({})['hoists'][0]
    assert h['max_load_kg'] == 50.0
    assert h['mass_scale'] == 1000.0
    assert h['load_kg'] == 60.0


def test_hoist_overload_flag(bw):
    mod, _vs, _objs = bw
    rows = mod.get_braceworks_hoists({})['hoists']
    over = [r for r in rows if r['overloaded']]
    assert len(over) == 1 and over[0]['number'] == '1'
    assert over[0]['load_ratio'] == 1.2


def test_hoist_overloaded_only(bw):
    mod, _vs, _objs = bw
    out = mod.get_braceworks_hoists({'overloaded_only': True})
    assert out['count'] == 1


def test_hoist_unknown_capacity_is_not_ok(bw):
    mod, _vs, objs = bw
    del objs[0].fields['MaximumLoad']
    del objs[0].fields['MaximumLoadStr']
    h = mod.get_braceworks_hoists({})['hoists'][0]
    assert h['capacity_known'] is False
    assert h['overloaded'] is None


def test_loads_group_by_origin(bw):
    mod, _vs, _objs = bw
    out = mod.get_braceworks_loads({})
    assert out['origins'] == 2
    named = [g for g in out['groups'] if g['origin'] == 'Origin A'][0]
    assert named['hoists'] == 1 and named['capacity'] == 50.0
    assert out['unassigned'] == 1
    assert out['overloaded'] == 1


def test_trusses(bw):
    mod, _vs, _objs = bw
    out = mod.get_braceworks_trusses({})
    assert out['count'] == 1
    t = out['trusses'][0]
    assert t['kind'] == 'straight' and t['length_num'] == 1500.0
    assert t['weight_per_length'] == 12.5
