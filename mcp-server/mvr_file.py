"""Read an MVR (My Virtual Rig) file without Vectorworks.

An MVR is a ZIP containing `GeneralSceneDescription.xml` plus one `.glb` mesh
per object. That makes the exchange file inspectable in plain Python — which is
the only way to answer "did the export actually contain the plot?" without
opening the file in a 3D app.

Verified against a VW2027 export (2026-11-14): MVR 1.6, provider
"Vectorworks", 20 entries — the XML plus 19 glb meshes.

Nothing here touches Vectorworks, so it also runs on a machine without VW.
"""
import os
import re
import zipfile
import xml.etree.ElementTree as ET

SCENE_XML = 'GeneralSceneDescription.xml'


class MvrError(RuntimeError):
    """The file is not a readable MVR."""


def _localname(tag):
    return tag.rsplit('}', 1)[-1]


def _find_all(node, name):
    return [e for e in node.iter() if _localname(e.tag) == name]


def _attr(node, name, default=None):
    for k, v in node.attrib.items():
        if _localname(k) == name:
            return v
    return default


def inspect(path):
    """Summarise an MVR file: provider, version, layers, objects, meshes.

    Returns a dict; raises MvrError when the file is not a ZIP or has no
    GeneralSceneDescription.xml. Every count is derived from the XML, and the
    raw element names are reported so a caller can see what the file really
    contains instead of trusting a fixed schema.
    """
    if not os.path.isfile(path):
        raise MvrError('no such file: %s' % path)
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise MvrError('%s is not a ZIP/MVR container' % path)

    names = zf.namelist()
    if SCENE_XML not in names:
        raise MvrError('%s has no %s — not an MVR' % (path, SCENE_XML))
    raw = zf.read(SCENE_XML)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise MvrError('%s is not valid XML: %s' % (SCENE_XML, exc))

    out = {
        'path': os.path.abspath(path),
        'bytes': os.path.getsize(path),
        'provider': _attr(root, 'provider'),
        'provider_version': _attr(root, 'providerVersion'),
        'mvr_version': '%s.%s' % (_attr(root, 'verMajor', '?'),
                                  _attr(root, 'verMinor', '?')),
        'entries': len(names),
        'meshes': len([n for n in names if n.lower().endswith('.glb')]),
        'xml_bytes': len(raw),
    }

    layers = [{'name': _attr(l, 'name'), 'uuid': _attr(l, 'uuid')}
              for l in _find_all(root, 'Layer')]
    out['layers'] = layers
    out['layer_count'] = len(layers)

    # MVR 1.5+ writes <SceneObject> with a <GDTFSpec>/<GDTFMode> pair; older
    # files used <Fixture>. Both are counted, and the element names actually
    # found under <ChildList> are reported, so a schema change shows up as data
    # instead of a silent zero.
    objs = _find_all(root, 'SceneObject')
    fixtures = _find_all(root, 'Fixture')
    children = []
    for cl in _find_all(root, 'ChildList'):
        children.extend(list(cl))
    out['scene_objects'] = len(objs)
    out['fixtures'] = len(fixtures)
    out['object_elements'] = sorted({_localname(e.tag) for e in children})
    out['object_count'] = len(children)

    specs, modes = {}, {}
    for o in objs + fixtures:
        for spec in _find_all(o, 'GDTFSpec'):
            if spec.text:
                specs[spec.text.strip()] = specs.get(spec.text.strip(), 0) + 1
        for mode in _find_all(o, 'GDTFMode'):
            if mode.text:
                modes[mode.text.strip()] = modes.get(mode.text.strip(), 0) + 1
    out['gdtf_specs'] = specs
    out['gdtf_modes'] = modes
    out['named_objects'] = sorted({_attr(o, 'name') for o in objs + fixtures
                                   if _attr(o, 'name')})
    out['symbols'] = len(_find_all(root, 'Symdef'))
    out['addresses'] = len(_find_all(root, 'Addresses'))
    return out


def describe(path):
    """One-line human summary of an MVR file."""
    d = inspect(path)
    return ('%s: MVR %s from %s %s — %d layer(s), %d scene object(s), '
            '%d fixture(s), %d mesh(es), %d bytes'
            % (os.path.basename(d['path']), d['mvr_version'],
               d['provider'] or 'unknown', d['provider_version'] or '',
               d['layer_count'], d['scene_objects'], d['fixtures'],
               d['meshes'], d['bytes']))
