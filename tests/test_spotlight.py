"""Offline tests for vwx-plugin/commands_spotlight.py (no Vectorworks).

    uv run --with pytest --with fastmcp==4.0.10 --with pillow pytest tests/test_spotlight.py -q

A fake `vs` module stands in for Vectorworks: it implements exactly the calls
the Spotlight verbs make (parametric record enumeration, LDevice_GetParam*,
ForEachObject, UUIDs, bounding boxes) over plain Python objects. That covers
the logic that actually breaks — universal-name resolution, patch conflicts,
address parsing — without a live plot.

What this CANNOT cover: whether the real universal names are the ones the
synonym table expects. That is what dump_spotlight_params is for, and why every
verb reports `catalog: fallback` instead of pretending.
"""
import json
import os
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, 'vwx-plugin')
sys.path.insert(0, PLUGIN)

# vs.GetFldType codes as verified against a live VW2027 Lighting Device
# ("Symbol Name"=4, "UseGDTFGeometry"=2, "Zoom Percentage"=3,
#  "Num Channels"=1) — NOT the 0..3 the SDK docs suggest.
TEXT, INTEGER, REAL, BOOLEAN = 4, 1, 3, 2


class Obj:
    """A fake Lighting Device: parametric record fields + cells + accessories."""

    def __init__(self, uuid, fields, name=None, cells=1, accs=None,
                 bbox=((0, 0), (1, 1)), obj_class='None', layer='Design 1',
                 rec_name='Lighting Device'):
        self.uuid = uuid
        self.name = name or 'Device-' + uuid[-3:]
        self.fields = list(fields)          # [(universal name, type, value)]
        self.cells = cells
        self.accs = accs or [[] for _ in range(cells)]
        self.bbox = bbox
        self.obj_class = obj_class
        self.layer = layer
        self.rec_name = rec_name

    def value(self, name):
        for n, _t, v in self.fields:
            if n == name:
                return v
        return None


def make_vs(objs, plugin_name='Lighting Device'):
    """A `vs` module good enough for commands.py + commands_spotlight.py."""
    vs = types.ModuleType('vs')
    by_uuid = {o.uuid: o for o in objs}

    def _obj(h):
        if isinstance(h, tuple) and h and h[0] == 'rec':
            return by_uuid[h[1]]
        return h

    vs.GetTypeN = lambda h: 86
    vs.GetParametricRecord = lambda h: ('rec', _obj(h).uuid)
    vs.GetName = lambda h: (_obj(h).rec_name if isinstance(h, tuple)
                            else _obj(h).name)
    vs.NumFields = lambda rec: len(_obj(rec).fields)
    vs.GetFldName = lambda rec, i: _obj(rec).fields[i][0]
    vs.GetFldType = lambda rec, i: _obj(rec).fields[i][1]
    vs.GetFldFlag = lambda rec, i: 0

    vs.LDevice_GetCellCount = lambda h: _obj(h).cells
    vs.LDevice_GetAccCount = lambda h, cell: len(_obj(h).accs[cell])
    vs.LDevice_GetAccPos2D = lambda h, cell, acc: (1.0, 2.0, 90.0)
    vs.LDevice_GetAccPos3D = lambda h, cell, acc: (1.0, 2.0, 3.0, 0.0, 0.0, 90.0)

    def _param(h, cell, acc, name, cast):
        v = _obj(h).value(name)
        if v is None:
            return cast()
        try:
            return cast(v)
        except Exception:
            return cast()

    vs.LDevice_GetParamStr = lambda h, c, a, n: _param(h, c, a, n, str)
    vs.LDevice_GetParamLong = lambda h, c, a, n: _param(h, c, a, n, int)
    vs.LDevice_GetParamReal = lambda h, c, a, n: _param(h, c, a, n, float)
    vs.LDevice_GetParamBool = lambda h, c, a, n: _param(h, c, a, n, bool)

    # The record read is the fallback for popup/control-point fields, which
    # have no LDevice reader (returns '' there) but a display value here.
    vs.GetRField = lambda h, rec, name: _obj(h).value(name) or ''

    def SetRField(h, rec, name, value):
        o = _obj(h)
        cast = {INTEGER: int, REAL: float, BOOLEAN: bool}.get(
            next((t for n, t, _v in o.fields if n == name), TEXT), str)
        for i, (n, t, _v) in enumerate(o.fields):
            if n == name:
                try:
                    o.fields[i] = (n, t, cast(value))
                except Exception:
                    o.fields[i] = (n, t, value)
                return True
        o.fields.append((name, TEXT, value))
        return True
    vs.SetRField = SetRField
    vs.ResetObject = lambda h: True
    vs.GetObjectUuid = lambda h: _obj(h).uuid
    vs.GetObjectByUuid = lambda u: by_uuid.get(str(u))
    vs.GetClass = lambda h: _obj(h).obj_class
    vs.GetLayer = lambda h: _obj(h).layer
    vs.GetLName = lambda h: h if isinstance(h, str) else _obj(h).layer
    vs.GetBBox = lambda h: _obj(h).bbox
    vs.GetFName = lambda: 'Test.vwx'
    vs.GetVersion = lambda: (2027, 0, 0, 0)

    def ForEachObject(cb, crit):
        crit = (crit or '').upper()
        for o in objs:
            if crit in ('ALL', '') or 'LIGHTING DEVICE' in crit:
                cb(o)
            elif 'NONE' in crit:
                continue
    vs.ForEachObject = ForEachObject

    # ── worksheets ────────────────────────────────────────────────────────
    # A tiny model that actually evaluates the two formula shapes the paperwork
    # verbs write: =DATABASE(criteria) on column 0 and ='Rec'.'Field' in a
    # column. That is what makes the read-back verification testable — a fake
    # that returns canned strings would not catch an empty column.
    class WS:
        def __init__(self, name, rows, cols):
            self.name, self.rows, self.cols = name, rows, cols
            self.cells = {}          # (row, col) -> formula / header text
            self.sub = {}            # (subrow, col) -> evaluated value
            self.db_row = None
            self.matches = []
            self.subrows = 0

    sheets = {}

    def CreateWS(name, rows, cols):
        sheets[name] = WS(name, rows, cols)
        return sheets[name]

    def SetWSCellFormula(ws, r1, c1, r2, c2, formula):
        ws.cells[(r1, c1)] = formula
        if c1 == 0 and str(formula).startswith('=DATABASE('):
            ws.db_row = r1
            crit = str(formula)[len('=DATABASE('):].rstrip(')')
            ws.matches = [o for o in objs
                          if 'LIGHTING DEVICE' in crit.upper() or crit.upper() == 'ALL']
            ws.subrows = len(ws.matches)

    def RecalculateWS(ws):
        # Snapshot the formulas first: writing results into the same dict would
        # make subrow 2 overwrite the formula subrow 3 still has to evaluate.
        formulas = {c: str(ws.cells.get((ws.db_row, c), ''))
                    for c in range(1, ws.cols + 1)}
        ws.sub = {}
        for s, obj in enumerate(ws.matches, start=1):
            for c, f in formulas.items():
                if f.startswith("='") and "'.'" in f:
                    field = f.split("'.'")[1].rstrip("'")
                    ws.sub[(s, c)] = obj.value(field)

    def GetWSSubrowCount(ws, row):
        return ws.subrows

    def GetWSSubrowCellString(ws, row, col, subrow):
        v = ws.sub.get((subrow, col))
        return '' if v is None else str(v)

    class Img:
        def __init__(self, i):
            self.uuid = 'img-%d' % i
            self.name = 'wsimage-%d' % i
    images = []

    def CreateWSImage(ws, loc):
        img = Img(len(images))
        images.append(img)
        by_uuid[img.uuid] = img
        return img

    vs.CreateWS = CreateWS
    vs.SetWSCellFormula = SetWSCellFormula
    vs.RecalculateWS = RecalculateWS
    vs.GetWSSubrowCount = GetWSSubrowCount
    vs.GetWSSubrowCellString = GetWSSubrowCellString
    vs.CreateWSImage = CreateWSImage
    vs.SetWSColumnWidth = lambda ws, a, b, w: None
    vs.GetObject = lambda name: sheets.get(name)
    vs._sheets = sheets
    return vs


@pytest.fixture
def spot(monkeypatch, tmp_path):
    """Import commands_spotlight against a fake vs; yields a factory.

    PARAMS_PATH is always redirected into tmp_path, never the repo: a test that
    dumps a catalog must not leave a fake spotlight_params.json behind for the
    next run to read as if it were real (that happened once).
    """
    def build(objs, catalog_path=None):
        fake = make_vs(objs)
        monkeypatch.setitem(sys.modules, 'vs', fake)
        for mod in ('commands', 'commands_spotlight'):
            monkeypatch.delitem(sys.modules, mod, raising=False)
        import commands_spotlight as S
        monkeypatch.setattr(S, 'PARAMS_PATH',
                            str(catalog_path or (tmp_path / 'spotlight_params.json')))
        monkeypatch.setattr(S, 'JOURNAL_PATH',
                            str(tmp_path / 'spotlight_journal.json'))
        S._catalog_cache.update({'mtime': None, 'data': None})
        return S
    return build


DEVICE_FIELDS = [
    ('channel', TEXT, '1'),
    ('dimmer', TEXT, '7'),
    ('universe', INTEGER, 1),
    ('address', TEXT, '001'),
    ('universe_address', TEXT, '1/1'),
    ('position', TEXT, 'FOH'),
    ('unit_number', TEXT, '3'),
    ('device_type', TEXT, 'Source Four 750'),
    ('symbol_name', TEXT, 'S4-750'),
    ('purpose', TEXT, 'Front light'),
    ('color', TEXT, 'R132'),
    ('gobo', TEXT, ''),
    ('focus', TEXT, 'Stage centre'),
    ('dmx_footprint', INTEGER, 2),
]


def two_devices(**over):
    a = Obj('aaaa-1', DEVICE_FIELDS)
    b_fields = [(n, t, (v + '0' if n in ('channel', 'address') else v))
                for n, t, v in DEVICE_FIELDS]
    b = Obj('bbbb-2', b_fields)
    for k, v in over.items():
        setattr(b, k, v)
    return [a, b]


def test_catalog_key_resolution(spot):
    S = spot(two_devices())
    keys, unresolved = S._resolve_keys([n for n, _t, _v in DEVICE_FIELDS])
    assert keys['channel'] == 'channel'
    assert keys['device_type'] == 'device_type'
    assert keys['dmx_footprint'] == 'dmx_footprint'
    # pan/tilt/weight/power/console_id are absent from this record
    assert 'pan' in unresolved and 'weight' in unresolved


def test_universe_address_forms(spot):
    S = spot([])
    assert S._universe_address({'universe': '2', 'address': '045'}) == (2, 45)
    assert S._universe_address({'address': 'U3/017'}) == (3, 17)
    assert S._universe_address({'universe': 1, 'address': ''}) == (1, None)


def test_devices_read_mapped_fields(spot):
    S = spot(two_devices())
    res = S.get_spotlight_devices({'limit': 10})
    assert res['count'] == 2, res
    d = res['devices'][0]
    assert d['object_id'] == 'aaaa-1'
    assert d['channel'] == '1' and d['position'] == 'FOH'
    assert d['focus'] == 'Stage centre'
    assert d['x'] == 0.5 and d['y'] == 0.5
    # Keys resolve from the object's own parametric record, not the file.
    assert res['catalog'] == 'live'
    assert 'pan' in res['unresolved']


def test_raw_returns_every_field(spot):
    S = spot(two_devices())
    res = S.get_spotlight_devices({'limit': 1, 'raw': True})
    raw = res['devices'][0]['raw']
    assert set(raw) >= {'channel', 'gobo', 'dmx_footprint', 'purpose'}


def test_position_filter(spot):
    S = spot(two_devices())
    assert S.get_spotlight_devices({'position': 'foh'})['count'] == 2
    assert S.get_spotlight_devices({'position': 'towers'})['count'] == 0


def test_positions_grouping(spot):
    S = spot(two_devices())
    res = S.get_spotlight_positions({})
    assert res['count'] == 1
    assert res['positions'][0]['position'] == 'FOH'
    assert res['positions'][0]['count'] == 2


def test_patch_conflicts(spot):
    # Same channel, same universe/address, overlapping footprint.
    a = Obj('aaaa-1', DEVICE_FIELDS)
    b = Obj('bbbb-2', DEVICE_FIELDS)
    S = spot([a, b])
    res = S.get_spotlight_patch({})
    conf = res['conflicts']
    assert [c['channel'] for c in conf['duplicate_channel']] == [1]
    assert conf['duplicate_address'][0]['address'] == 1
    assert conf['address_overlap'], 'footprint 2 at the same address must overlap'
    assert conf['unpatchable'] == 0


def test_patch_missing_and_overlap_across_devices(spot):
    a = Obj('aaaa-1', [('channel', TEXT, '1'), ('address', TEXT, '1'),
                       ('dmx_footprint', INTEGER, 4), ('universe', INTEGER, 1)])
    b = Obj('bbbb-2', [('channel', TEXT, ''), ('address', TEXT, '3'),
                       ('dmx_footprint', INTEGER, 1), ('universe', INTEGER, 1)])
    S = spot([a, b])
    conf = S.get_spotlight_patch({})['conflicts']
    assert conf['unpatchable'] == 1
    assert len(conf['address_overlap']) == 1          # address 3 (a) vs 3 (b)
    assert conf['address_overlap'][0]['address'] == 3


def test_find_objects_reports_plugin(spot):
    S = spot(two_devices())
    res = S.find_objects({'criteria': "(PON='Lighting Device')"})
    assert res['count'] == 2
    assert res['objects'][0]['plugin'] == 'Lighting Device'


def test_single_device_includes_accessories(spot):
    accs = [['gobo-rotator'], []]
    a = Obj('aaaa-1', DEVICE_FIELDS, cells=2, accs=accs)
    S = spot([a])
    res = S.get_spotlight_device({'object_id': 'aaaa-1'})
    assert res['cells'] == 2
    assert res['accessories'][0]['count'] == 1
    assert res['accessories'][1]['count'] == 0
    assert res['accessories'][0]['accessories'][0]['pos2d'] == [1.0, 2.0, 90.0]


def test_accessory_inventory(spot):
    a = Obj('aaaa-1', DEVICE_FIELDS, cells=1, accs=[['a', 'b']])
    S = spot([a])
    res = S.get_spotlight_accessories({})
    assert res['accessories'] == 2
    assert res['devices'] == 1


def test_dump_writes_catalog_and_keys(spot, tmp_path):
    path = tmp_path / 'spotlight_params.json'
    S = spot(two_devices(), catalog_path=path)
    res = S.dump_spotlight_params({'limit': 5})
    assert res['field_count'] == len(DEVICE_FIELDS)
    assert res['keys']['channel'] == 'channel'
    assert 'pan' in res['unresolved_keys']
    assert res['devices_sampled'] == 2
    on_disk = json.loads(path.read_text(encoding='utf-8'))
    assert on_disk['verified'] is True
    assert on_disk['record_name'] == 'Lighting Device'
    # Reads keep resolving live; the file is the reference/human artifact.
    S._catalog_cache.update({'mtime': None, 'data': None})
    again = S.get_spotlight_devices({'limit': 1})
    assert again['catalog'] == 'live'
    assert again['devices'][0]['channel'] == '1'
    assert S.get_spotlight_params({})['verified'] is True


def test_fallback_when_no_record_is_readable(spot, monkeypatch):
    """A non-parametric object (or a broken record) must degrade honestly."""
    S = spot([Obj('aaaa-1', DEVICE_FIELDS)])
    monkeypatch.setattr(sys.modules['vs'], 'GetParametricRecord', lambda h: None)
    res = S.get_spotlight_devices({'limit': 1})
    assert res['catalog'] == 'fallback'
    assert 'warning' in res
    assert res['count'] == 1


def test_dump_without_devices_is_an_error(spot):
    S = spot([])
    res = S.dump_spotlight_params({})
    assert 'error' in res and 'hint' in res


def test_catalog_from_document_scan_when_criteria_miss(spot):
    """A localized install names the plug-in differently; the scan must find it."""
    S = spot([Obj('aaaa-1', DEVICE_FIELDS)])
    res = S.dump_spotlight_params({'criteria': "(PON='Nope')"})
    # explicit criteria that match nothing -> honest empty, no silent scan
    assert 'error' in res


# ── regressions from the first live run on VW2027 (2026-11-14) ──────────────

def test_junk_field_name_is_skipped(spot, monkeypatch):
    """VW2027's Lighting Device record starts with a junk field.

    Its name is private-use code points and GetFldType returns -23248. Passing
    that name to LDevice_GetParamStr does not raise — it kills Vectorworks. The
    guard must drop the field before any reader sees it.
    """
    junk = '\ua210\ue0a3\u0286'
    fields = [(junk, -23248, 'x')] + list(DEVICE_FIELDS)
    S = spot([Obj('aaaa-1', fields)])
    calls = []
    real = sys.modules['vs'].LDevice_GetParamStr
    monkeypatch.setattr(sys.modules['vs'], 'LDevice_GetParamStr',
                        lambda h, c, a, n: (calls.append(n), real(h, c, a, n))[1])
    res = S.dump_spotlight_params({})
    assert res['field_count'] == len(DEVICE_FIELDS)
    assert junk not in calls
    assert all(n in {f[0] for f in DEVICE_FIELDS} for n in calls)


def test_popup_field_falls_back_to_the_record(spot, monkeypatch):
    """Popup/control-point fields have no LDevice reader ('' there).

    The record itself holds the display value ("Light", "A", "17°"), so the
    reader must fall back to GetRField instead of reporting an empty field.
    """
    fields = [('Device Type', 8, 'Light')] + list(DEVICE_FIELDS)
    S = spot([Obj('aaaa-1', fields)])
    monkeypatch.setattr(sys.modules['vs'], 'LDevice_GetParamStr',
                        lambda h, c, a, n: '')
    res = S.get_spotlight_devices({'limit': 1})
    assert res['devices'][0]['device_type'] == 'Light'


def test_field_type_codes_are_the_verified_ones(spot):
    """1/2/3/4 — not the 0..3 the SDK stub implies."""
    S = spot([Obj('aaaa-1', DEVICE_FIELDS)])
    assert S._TYPE_READER == {1: 'Long', 2: 'Bool', 3: 'Real', 4: 'Str'}


def test_universe_address_field_is_the_source_of_truth(spot):
    """VW2027 keeps the patch in UniverseAddress ("U/A"); 0/0 means unpatched.

    Verified live: SetRField into UniverseAddress sticks, the separate Universe /
    DMX Address fields are not derived from it, and LDevice_GetParamStr lags a
    reset behind — so the record field has to win.
    """
    fields = [('Channel', TEXT, '101'), ('UniverseAddress', TEXT, '2/201')]
    S = spot([Obj('aaaa-1', fields)])
    row = S.get_spotlight_patch({})['devices'][0]
    assert (row['universe_num'], row['address_num']) == (2, 201)
    assert row['address_range'] == [201, 201]

    unpatched = spot([Obj('bbbb-1', [('Channel', TEXT, '102'),
                                     ('UniverseAddress', TEXT, '0/0')])])
    res = unpatched.get_spotlight_patch({})
    assert res['devices'][0]['address_num'] is None
    assert res['conflicts']['missing_address'] == ['bbbb-1']


def test_separate_patch_fields_still_parse(spot):
    """Older/hand-typed plots: 'U1/001' in the address field, universe empty."""
    fields = [('Channel', TEXT, '5'), ('Universe', TEXT, 'U1'),
              ('DMX Address', TEXT, '001')]
    S = spot([Obj('cccc-1', fields)])
    row = S.get_spotlight_patch({})['devices'][0]
    assert (row['universe_num'], row['address_num']) == (1, 1)


# ── writes (M2) ────────────────────────────────────────────────────────────
#
# The write layer's whole point is that a write either takes or says so. These
# tests cover the three ways it can lie: a SetRField that no-ops (read-back
# catches it), a logical key that has no universal name (reported in `skipped`),
# and a journal that cannot restore what it claims (document mismatch).


def _journal(S):
    with open(S.JOURNAL_PATH, encoding='utf-8') as f:
        return json.load(f)


def test_set_patch_writes_and_journals(spot):
    S = spot(two_devices())
    res = S.set_spotlight_patch({'fields': {'channel': '101',
                                            'universe_address': '1/101'}})
    assert res['ok'] and res['count'] == 2, res
    assert res['written'] == 4
    dev = res['devices'][0]
    assert dev['fields']['channel']['before'] == '1'
    assert dev['fields']['channel']['readback'] == '101'

    # the write is visible through the read path, not just in the result dict
    again = S.get_spotlight_devices({'limit': 10})
    assert {d['channel'] for d in again['devices']} == {'101'}

    batches = _journal(S)['batches']
    assert len(batches) == 1
    assert batches[0]['batch_id'] == res['batch_id']
    assert batches[0]['verb'] == 'set_spotlight_patch'
    assert {e['field'] for e in batches[0]['entries']} == {'channel',
                                                          'universe_address'}


def test_set_patch_dry_run_writes_nothing(spot):
    S = spot(two_devices())
    res = S.set_spotlight_patch({'fields': {'channel': '999'}, 'dry_run': True})
    assert res['dry_run'] and res['ok']
    assert res['devices'][0]['fields']['channel']['before'] == '1'
    assert S.get_spotlight_devices({'limit': 10})['devices'][0]['channel'] == '1'
    assert not os.path.exists(S.JOURNAL_PATH)


def test_set_patch_reports_a_write_that_does_not_take(spot):
    """The failure this layer exists for: SetRField returns None and does nothing."""
    S = spot(two_devices())
    S.vs.SetRField = lambda h, rec, name, value: None
    res = S.set_spotlight_patch({'fields': {'channel': '101'}})
    assert res['ok'] is False
    field = res['devices'][0]['fields']['channel']
    assert field['ok'] is False
    assert 'read-back' in field.get('error', '') or field['readback'] != '101'


def test_set_patch_skips_unknown_keys_instead_of_guessing(spot):
    S = spot(two_devices())
    res = S.set_spotlight_patch({'fields': {'flibbertigibbet': 'x'}})
    assert res['skipped'] == [{'field': 'flibbertigibbet',
                               'reason': 'no universal name'}]
    assert res['error'] == 'nothing written'
    assert not os.path.exists(S.JOURNAL_PATH)


def test_set_patch_assignments_target_one_device(spot):
    S = spot(two_devices())
    res = S.set_spotlight_patch({'assignments': [
        {'object_id': 'bbbb-2', 'fields': {'position': 'Ladder'}}]})
    assert res['count'] == 1 and res['ok']
    devs = {d['object_id']: d for d in S.get_spotlight_devices({'limit': 10})['devices']}
    assert devs['bbbb-2']['position'] == 'Ladder'
    assert devs['aaaa-1']['position'] == 'FOH'


def test_renumber_steps_by_footprint_and_rolls_the_universe(spot):
    """Footprint 2 starting at 510: 510-511 fits, the next fixture needs U2."""
    S = spot(two_devices())
    res = S.renumber_spotlight({'start_address': 510, 'universe_size': 512})
    assert res['ok'], res
    assert [(r['universe_address'], r['footprint']) for r in res['rows']] == [
        ('1/510', 2), ('2/1', 2)]
    assert [r['channel'] for r in res['rows']] == [1, 2]


def test_revert_last_restores_before_values(spot):
    S = spot(two_devices())
    before = [d['channel'] for d in S.get_spotlight_devices({'limit': 10})['devices']]
    written = S.set_spotlight_patch({'fields': {'channel': '101'}})
    assert S.get_spotlight_devices({'limit': 10})['devices'][0]['channel'] == '101'

    res = S.revert_last({})
    assert res['ok'] and res['restored'] == 2, res
    assert res['batch_id'] == written['batch_id']
    assert [d['channel'] for d in S.get_spotlight_devices({'limit': 10})['devices']] == before
    assert _journal(S)['batches'][-1]['reverted'] is True

    # a reverted batch is not offered again, and naming it says why
    assert S.revert_last({})['error'] == 'No batch to revert'
    assert S.revert_last({'batch_id': written['batch_id']})['error'] == \
        'Batch already reverted'


def test_revert_last_refuses_another_document(spot):
    S = spot(two_devices())
    S.set_spotlight_patch({'fields': {'channel': '101'}})
    data = _journal(S)
    data['batches'][-1]['document'] = 'SomeOtherPlot.vwx'
    with open(S.JOURNAL_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    res = S.revert_last({})
    assert res['error'] == 'Batch belongs to another document'
    assert res['batch_document'] == 'SomeOtherPlot.vwx'
    # and nothing was touched
    assert S.get_spotlight_devices({'limit': 10})['devices'][0]['channel'] == '101'


def test_revert_last_skips_fields_already_restored_by_hand(spot):
    S = spot(two_devices())
    S.set_spotlight_patch({'fields': {'channel': '101'}})
    # the designer undid one device by hand
    S.vs.SetRField(S.vs.GetObjectByUuid('aaaa-1'), 'Lighting Device',
                   'channel', '1')
    res = S.revert_last({})
    assert res['ok']
    assert [c['object_id'] for c in res['changes']] == ['bbbb-2']
    assert res['already_before'][0]['object_id'] == 'aaaa-1'


def test_write_verbs_do_not_shadow_upstream_commands():
    """commands.py wins in the pump's dispatch, so a name clash would silently
    replace our verb with upstream's (or vice versa)."""
    import ast
    src = open(os.path.join(PLUGIN, 'commands.py'), encoding='utf-8').read()
    names = {n.name for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.FunctionDef)}
    for verb in ('set_spotlight_patch', 'renumber_spotlight', 'revert_last'):
        assert verb not in names, verb


def test_none_is_never_written_into_a_record(spot):
    """`str(None)` would store the literal text "None" in the record."""
    S = spot(two_devices())
    res = S.set_spotlight_patch({'fields': {'channel': None}})
    assert res['devices'][0]['fields']['channel']['ok'] is False
    assert S.get_spotlight_devices({'limit': 10})['devices'][0]['channel'] == '1'


# ── paperwork (M5) ─────────────────────────────────────────────────────────
#
# A worksheet that silently shows empty columns is this project's whole failure
# mode, so the tests care less about "a sheet was created" than about the
# read-back: does the sheet on screen hold the same values as the plot?


def plot():
    """Three devices across two positions, with weights and a footprint."""
    def dev(uuid, channel, ua, pos, unit, typ, weight, power, foot=1):
        return Obj(uuid, [
            ('channel', TEXT, channel), ('universe_address', TEXT, ua),
            ('position', TEXT, pos), ('unit_number', TEXT, unit),
            ('device_type', TEXT, typ), ('weight', TEXT, weight),
            ('power', TEXT, power), ('dmx_footprint', INTEGER, foot),
            ('focus', TEXT, 'Stage'), ('purpose', TEXT, 'Front light'),
            ('color', TEXT, 'R132'), ('gobo', TEXT, ''),
        ])
    return [dev('aaaa-1', '1', '1/1', 'FOH', '1', 'S4 750', '7,5 kg', '750 W', 2),
            dev('bbbb-2', '2', '1/3', 'FOH', '2', 'S4 750', '7,5 kg', '750 W', 2),
            dev('cccc-3', '3', '2/1', 'Ladder', '1', 'PAR 64', '2,25 kg', '1000 W')]


def test_report_channel_hookup(spot):
    S = spot(plot())
    res = S.get_spotlight_report({'kind': 'channel_hookup'})
    assert res['count'] == 3 and res['catalog'] == 'live'
    first = res['devices'][0]
    assert first['channel'] == '1' and first['universe_address'] == '1/1'
    assert res['columns'] == ['Ch', 'Dim', 'U/A', 'Pos', 'Unit', 'Type',
                              'Purpose', 'Color', 'Gobo', 'Focus']


def test_report_weight_totals_per_position(spot):
    S = spot(plot())
    res = S.get_spotlight_report({'kind': 'weight_report'})
    assert [d['weight_kg'] for d in res['devices']] == [7.5, 7.5, 2.25]
    by_pos = {g['position']: g for g in res['by_position']}
    assert by_pos['FOH']['weight_kg'] == 15.0
    assert by_pos['FOH']['power_w'] == 1500.0
    assert by_pos['Ladder']['count'] == 1
    assert by_pos['FOH']['weighted'] == 2


def test_measure_survives_localized_units(spot):
    S = spot([])
    assert S._measure('7,5 kg') == 7.5
    assert S._measure('750 W') == 750.0
    assert S._measure('12.25kg') == 12.25
    assert S._measure('') is None
    assert S._measure(None) is None
    assert S._measure('n/a') is None


def test_worksheet_is_built_and_verified(spot):
    S = spot(plot())
    res = S.spotlight_worksheet({'kind': 'channel_hookup', 'name': 'Hookup'})
    assert res['verified'] is True, res
    assert res['subrows'] == 3
    assert res['columns'] == 10
    assert all(col['ok'] for col in res['detail'])
    assert res['detail'][0]['filled'] == 3


def test_worksheet_uses_the_live_universal_names(spot):
    """The formula must come from the record, not from a hardcoded name."""
    S = spot(plot())
    S.spotlight_worksheet({'kind': 'patch_sheet', 'name': 'Patch'})
    ws = S.vs._sheets['Patch']
    formulas = [f for (r, c), f in ws.cells.items() if r == 2 and c > 0]
    assert "='Lighting Device'.'channel'" in formulas
    assert "='Lighting Device'.'universe_address'" in formulas


def test_worksheet_reports_an_empty_column_instead_of_pretending(spot):
    """A column that does not fill must fail verification, not pass silently."""
    S = spot(plot())
    real = S.vs.GetWSSubrowCellString
    S.vs.GetWSSubrowCellString = lambda ws, r, c, s: (
        '' if c == 1 else real(ws, r, c, s))
    res = S.spotlight_worksheet({'kind': 'channel_hookup', 'name': 'Broken'})
    assert res['verified'] is False
    bad = [d for d in res['detail'] if not d['ok']]
    assert len(bad) == 1 and bad[0]['key'] == 'channel'
    assert 'warning' in res


def test_worksheet_refuses_to_overwrite_an_existing_name(spot):
    S = spot(plot())
    S.spotlight_worksheet({'kind': 'channel_hookup', 'name': 'Hookup'})
    res = S.spotlight_worksheet({'kind': 'channel_hookup', 'name': 'Hookup'})
    assert 'already exists' in res['error']


def test_worksheet_places_on_the_drawing(spot):
    S = spot(plot())
    res = S.spotlight_worksheet({'kind': 'focus_chart', 'name': 'Focus',
                                 'place': True, 'x': 100, 'y': 200})
    assert res['verified'] is True
    assert res['image_id'] == 'img-0'


def test_unknown_report_kind_lists_the_valid_ones(spot):
    S = spot(plot())
    res = S.get_spotlight_report({'kind': 'nonsense'})
    assert res['error'] == 'unknown kind'
    assert 'weight_report' in res['kinds']
