"""Offline tests for the MVR layer (mvr_file.py + the GUI module's guards).

    uv run --with pytest --with fastmcp==4.0.10 --with pillow pytest tests/test_mvr.py -q

`mvr_file` needs no Vectorworks at all — an MVR is a ZIP with an XML inside, so
the parser is tested against synthetic files. The GUI half (`vwx_gui`) cannot be
tested without a live Vectorworks; what is tested here is that it refuses
honestly on the wrong platform instead of pretending.
"""
import json
import os
import sys
import zipfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'mcp-server'))

import mvr_file  # noqa: E402

SCENE = """<?xml version="1.0" encoding="UTF-8"?>
<GeneralSceneDescription provider="Vectorworks" providerVersion="32.1.1"
                        verMajor="1" verMinor="6">
  <Scene>
    <Layers>
      <Layer name="Schematic" uuid="AAA"/>
      <Layer name="3D Layout" uuid="BBB"/>
    </Layers>
    <AUXData>
      <Symdef name="S1"/>
    </AUXData>
    <ChildList>
      <SceneObject name="Device">
        <GDTFSpec>Generic@Device</GDTFSpec>
        <GDTFMode>Default</GDTFMode>
      </SceneObject>
      <SceneObject name="Circuit">
        <GDTFSpec>Generic@Device</GDTFSpec>
        <GDTFMode>Default</GDTFMode>
      </SceneObject>
      <Fixture name="Spot">
        <GDTFSpec>Robe@Robin</GDTFSpec>
        <GDTFMode>Standard</GDTFMode>
      </Fixture>
    </ChildList>
  </Scene>
</GeneralSceneDescription>
"""


def make_mvr(path, scene=SCENE, meshes=2, extra=None):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(mvr_file.SCENE_XML, scene)
        for i in range(meshes):
            z.writestr('mesh-%d.glb' % i, b'glTF' + bytes(64))
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def test_inspect_counts(tmp_path):
    p = make_mvr(str(tmp_path / 'show.mvr'))
    d = mvr_file.inspect(p)
    assert d['provider'] == 'Vectorworks'
    assert d['mvr_version'] == '1.6'
    assert d['layer_count'] == 2
    assert d['scene_objects'] == 2
    assert d['fixtures'] == 1
    assert d['meshes'] == 2
    assert d['entries'] == 3
    assert d['symbols'] == 1
    assert d['bytes'] == os.path.getsize(p)


def test_inspect_layers_and_gdtf(tmp_path):
    p = make_mvr(str(tmp_path / 'show.mvr'))
    d = mvr_file.inspect(p)
    assert [l['name'] for l in d['layers']] == ['Schematic', '3D Layout']
    assert d['gdtf_specs'] == {'Generic@Device': 2, 'Robe@Robin': 1}
    assert d['gdtf_modes'] == {'Default': 2, 'Standard': 1}
    assert d['named_objects'] == ['Circuit', 'Device', 'Spot']
    assert d['object_elements'] == ['Fixture', 'SceneObject']


def test_inspect_reports_element_names(tmp_path):
    """A schema change must show up as data, not as a silent zero."""
    scene = SCENE.replace('SceneObject', 'SomethingElse')
    p = make_mvr(str(tmp_path / 'odd.mvr'), scene=scene)
    d = mvr_file.inspect(p)
    assert d['scene_objects'] == 0
    assert d['object_elements'] == ['Fixture', 'SomethingElse']
    assert d['object_count'] == 3


def test_inspect_missing_file():
    with pytest.raises(mvr_file.MvrError):
        mvr_file.inspect('nope/not-there.mvr')


def test_inspect_not_a_zip(tmp_path):
    p = tmp_path / 'plain.mvr'
    p.write_bytes(b'not a zip')
    with pytest.raises(mvr_file.MvrError):
        mvr_file.inspect(str(p))


def test_inspect_zip_without_scene(tmp_path):
    p = tmp_path / 'empty.mvr'
    with zipfile.ZipFile(str(p), 'w') as z:
        z.writestr('readme.txt', 'hello')
    with pytest.raises(mvr_file.MvrError):
        mvr_file.inspect(str(p))


def test_inspect_broken_xml(tmp_path):
    p = make_mvr(str(tmp_path / 'broken.mvr'), scene='<not-closed>')
    with pytest.raises(mvr_file.MvrError):
        mvr_file.inspect(p)


def test_describe_is_one_line(tmp_path):
    p = make_mvr(str(tmp_path / 'show.mvr'))
    line = mvr_file.describe(p)
    assert '\n' not in line
    assert 'MVR 1.6' in line and '2 layer(s)' in line and '1 fixture(s)' in line


# ── the GUI half refuses honestly ─────────────────────────────────────────

def test_gui_refuses_on_other_platforms(monkeypatch):
    """No macOS driver exists yet; the error must say so, not fail obscurely."""
    import vwx_gui
    monkeypatch.setattr(vwx_gui, 'IS_WINDOWS', False)
    monkeypatch.setattr(vwx_gui, '_u', None)
    with pytest.raises(vwx_gui.GuiUnavailable) as exc:
        vwx_gui.export_mvr('x.mvr')
    assert 'macOS' in str(exc.value)


def test_export_refuses_missing_folder(tmp_path):
    """A bad path must fail before any dialog opens."""
    import vwx_gui
    if not vwx_gui.IS_WINDOWS:
        pytest.skip('windows only')
    out = vwx_gui.export_mvr(str(tmp_path / 'nope' / 'x.mvr'))
    assert out['ok'] is False
    assert 'folder does not exist' in out['error']


def test_import_refuses_missing_file():
    import vwx_gui
    if not vwx_gui.IS_WINDOWS:
        pytest.skip('windows only')
    out = vwx_gui.import_mvr('definitely-not-here.mvr')
    assert out['ok'] is False
    assert 'no such file' in out['error']
