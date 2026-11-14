# English surface (and what stays German)

The upstream codebase was written against a German Vectorworks install, so the
wire format and many messages were German: `list_documents` answered

```json
{"status": "ok", "aktiv": "...", "anzahl": 1,
 "dokumente": [{"titel": "...", "datei": "...", "klasse": "...", "quelle": "mdi"}]}
```

and a failed dialog press said `"Knopf 'OK' nicht gefunden"`. An agent reading
that has to translate before it can act, so the client-visible surface is
English now. Verified live: `list_documents` returns `active / count /
documents / title / file / class / source / title_empty / diagnostics`, and
`use_document` on a missing document returns `{error, code: DOC_NOT_OPEN, open,
hint}`.

## What was translated

| Old (German) | New (English) | Where |
|---|---|---|
| `aktiv`, `anzahl`, `dokumente` | `active`, `count`, `documents` | `list_documents` |
| `titel`, `datei`, `klasse`, `quelle`, `titel_leer` | `title`, `file`, `class`, `source`, `title_empty` | document entries |
| `diagnose`, `oberste`, `kinder`, `aktiv_hwnd`, `unbenannt` | `diagnostics`, `top_level`, `children`, `active_hwnd`, `untitled` | diagnostics block |
| `offen`, `kandidaten`, `grund` | `open`, `candidates`, `reason` | `use_document` / `switch_document` errors |
| `ziel`, `ziel_hwnd`, `gewechselt`, `angestossen`, `vorher`, `geraten` | `target`, `target_hwnd`, `switched`, `requested`, `previous`, `guessed` | switch results |
| `dokument`, `gespeichert`, `aktiv_pfad` | `document`, `saved`, `active_path` | close/save results |
| `hinweis` | `hint` | every result |
| `mdi-rahmen-titel` | `mdi-frame-title` | `source` value |
| "Vectorworks zeigt einen modalen Dialog …" | "Vectorworks is showing a modal dialog …" | `VW_MODAL_DIALOG` |
| "Knopf 'X' nicht gefunden" / "kein passender Dialog offen" | "button 'X' not found" / "no matching dialog is open" | `vw_dialog_press` |
| terrain/hardscape messages | English | `create_grade`, `hardscape_*`, `erdbau_*` |

Docstrings were translated too, because `list_commands` returns their first
line and the MCP tool descriptions are read by agents.

## What stays German — on purpose

These are **data names in a German document**, not prose. Renaming them in a
string would break the lookup:

| Name | What it is |
|---|---|
| `Höhe`, `Botanischer Name`, `Eigene Höhen` | plant record fields |
| `LL-Erdbau`, `CGA_TG` | record and layer names |
| `Als Modifikator verwenden`, `Angepasst` | menu/parameter labels |
| `LL_03_Bäume` | a layer name in a criteria string |
| `2 Hoehe Stütze` | an OIP label of a Marionette node |

`tests/test_english_surface.py` enforces the split: it strips quoted segments
before scanning, so a German word inside quotes is treated as data, and it
fails on any German word in prose. It also asserts the allowlisted names are
still used, so the list cannot rot.

## What is not translated

**Inline comments.** ~99 lines in `commands.py` are still German. They never
reach a client, and translating them would add ~100 lines to a vendored file
whose diff against upstream is kept small on purpose (see AGENTS.md, "fork
rules"). If that changes, it is a separate, mechanical pass — the same mapping
table applies.

## Rebase note

The rename touched `commands.py` in one contiguous region (the window/document
layer, ~300-620) plus scattered message strings. When merging upstream, resolve
by keeping the English keys here and re-applying the mapping to any new German
key that appears — `tests/test_english_surface.py` fails on the first one, which
is exactly the reminder you want.
