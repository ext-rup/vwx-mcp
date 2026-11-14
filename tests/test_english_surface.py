"""The client-visible surface must be English.

The upstream codebase grew German keys and messages (`{"aktiv": ..., "datei":
...}`, "Knopf 'OK' nicht gefunden") because it was written against a German
install. An agent reading `list_documents` should not have to translate, so the
wire format and the messages are English now — and this test keeps them that
way.

What is deliberately NOT checked: German *data* names. A German document really
has a layer called `LL_03_Bäume`, a record field `Höhe` and a menu label
`Als Modifikator verwenden`; renaming those in a string would break the code
that looks them up. Quoted segments are stripped before the scan for that
reason. Inline comments are out of scope too (they never reach a client) — see
docs/ENGLISH.md.
"""
import ast
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files whose strings and docstrings reach an MCP client.
SHIPPED = [
    os.path.join(REPO, 'vwx-plugin', 'commands.py'),
    os.path.join(REPO, 'vwx-plugin', 'vwx_pump.py'),
    os.path.join(REPO, 'vwx-plugin', 'commands_spotlight.py'),
    os.path.join(REPO, 'vwx-plugin', 'commands_connectcad.py'),
    os.path.join(REPO, 'vwx-plugin', 'commands_braceworks.py'),
    os.path.join(REPO, 'mcp-server', 'vwx_mcp_server.py'),
    os.path.join(REPO, 'mcp-server', 'spotlight_tools.py'),
    os.path.join(REPO, 'mcp-server', 'connectcad_tools.py'),
    os.path.join(REPO, 'mcp-server', 'braceworks_tools.py'),
    os.path.join(REPO, 'mcp-server', 'mvr_tools.py'),
    os.path.join(REPO, 'mcp-server', 'vwx_gui.py'),
    os.path.join(REPO, 'mcp-server', 'mvr_file.py'),
]

GERMAN = re.compile(
    r'[äöüßÄÖÜ]|'
    r'\b(nicht|kein|keine|keinen|Knopf|Knöpfe|Fehler|Datei|Auswahl|Abbrechen|'
    r'Nein|aktiv|anzahl|dokumente|titel|datei|klasse|quelle|noch|offen|wird|'
    r'sind|und|oder|wenn|dann|bitte|muss|kann|werden|hat|haben|für|über|'
    r'öffnen|schließen|Speichern|Löschen|angestossen|grund|ziel|kandidaten|'
    r'gewechselt|unbenannt|oberste|kinder|diagnose|rahmen|hinweis|gefunden|'
    r'gesetzt|erwartet|vorher|Belag|Gefälle|Gelaende|Gelände|Datensatz|Ebene|'
    r'Werkzeug|ausführen|bestaetigen|Sichern|Fenster|Wechsel|Antwort|bereits|'
    r'vorn|schliesst|Vorlage|Stütze|heißen|Namensvergleich|zuverlaessiger|'
    r'faelschlich|koennten|Einfügepunkt|verbindet|Zubehör)\b')

# Strings that ARE data: real names in a German document, kept on purpose.
DATA_ALLOW = {
    'Höhe', 'Botanischer Name', 'Eigene Höhen', 'außen', '2 Hoehe Stütze',
    'LL-Erdbau', 'CGA_TG', 'Als Modifikator verwenden', 'Angepasst',
}

QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")


def _strings(path):
    """Every string literal and docstring in a file, as (lineno, text)."""
    with open(path, encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _offenders(path):
    """German words in prose — quoted data names are stripped first."""
    bad = []
    for lineno, text in _strings(path):
        if text.strip() in DATA_ALLOW:
            continue
        m = GERMAN.search(QUOTED.sub(' ', text))
        if m:
            bad.append((lineno, m.group(0), text.strip().split('\n')[0][:80]))
    return bad


def test_shipped_strings_are_english():
    problems = {}
    for path in SHIPPED:
        bad = _offenders(path)
        if bad:
            problems[os.path.relpath(path, REPO)] = bad[:5]
    assert not problems, (
        'German text in a client-visible string — translate it, or add the '
        'string to DATA_ALLOW if it is a real name in a German document:\n'
        + '\n'.join('%s: %r' % (f, b) for f, b in problems.items()))


def test_no_german_dict_keys():
    """The wire format is the part a client parses; a German key is a bug."""
    keys = set()
    for path in SHIPPED:
        for _lineno, text in _strings(path):
            if text.strip() in DATA_ALLOW or ' ' in text:
                continue
            if GERMAN.search(text):
                keys.add(text)
    assert not keys, 'German dict keys/values: %s' % sorted(keys)


def test_german_data_names_still_used():
    """The allowlist must stay honest: those names really are in the code."""
    with open(os.path.join(REPO, 'vwx-plugin', 'commands.py'),
              encoding='utf-8') as fh:
        src = fh.read()
    for name in ('Höhe', 'Botanischer Name', 'CGA_TG'):
        assert name in src, '%r is allowlisted but no longer used' % name
