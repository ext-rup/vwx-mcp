"""Every @vtool must carry a tag, and every preset must keep the escape hatch.

The Visibility API filters at registration time, so an untagged tool vanishes
from every preset except `full` — and a preset without `escape` strands an agent
with no way to call `set_toolset` and undo the filter. Both are silent failures,
which is why they are asserted statically instead of discovered in the field.
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'mcp-server'))

import tool_tags  # noqa: E402


def _registered_tools():
    """Names of every function decorated with @vtool.

    Every module the server registers tools from: the vendored server plus each
    fork tool module (fork_tools.py imports them so the vendored file stays a
    one-line diff). A new fork module must be added here AND to fork_tools.py —
    the stale-tag test below catches the second half of that mistake.
    """
    names = []
    for fname in ('vwx_mcp_server.py', 'spotlight_tools.py',
                  'connectcad_tools.py', 'braceworks_tools.py',
                  'mvr_tools.py'):
        path = os.path.join(REPO, 'mcp-server', fname)
        tree = ast.parse(open(path, encoding='utf-8').read())
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if getattr(target, 'id', None) == 'vtool':
                    names.append(node.name)
                    break
    return names


def test_every_tool_is_tagged():
    tools = _registered_tools()
    assert len(tools) > 200, len(tools)
    missing = [n for n in tools if n not in tool_tags.TOOL_TAGS]
    assert not missing, 'untagged tools: %s' % missing


def test_no_stale_tag_entries():
    """A tag for a tool that no longer exists hides a rename."""
    tools = set(_registered_tools())
    stale = sorted(set(tool_tags.TOOL_TAGS) - tools)
    assert not stale, 'tagged but not registered: %s' % stale


def test_every_preset_keeps_the_escape_hatch():
    for name, tags in tool_tags.PRESETS.items():
        if tags is None:
            continue
        assert 'escape' in tags, name


def test_spotlight_preset_carries_the_spotlight_verbs():
    tags = tool_tags.PRESETS['spotlight']
    verbs = [n for n, t in tool_tags.TOOL_TAGS.items()
             if t == 'spotlight' and n.startswith(('get_spotlight', 'set_spotlight',
                                                   'renumber_spotlight',
                                                   'dump_spotlight', 'revert_last',
                                                   'find_objects'))]
    # 8 reads + 3 writes; find_objects is tagged 'query' (it serves every domain)
    assert len(verbs) >= 11, verbs
    assert 'spotlight' in tags
