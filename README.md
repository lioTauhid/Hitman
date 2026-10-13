# Hitman

A lightweight desktop API client written in Python with PySide6. No account, no cloud sync, and nothing you
don't need. Everything is stored locally in a single SQLite file.

## Features

- **Requests:** all common methods, query params kept in sync with the URL, `:path` variables, headers,
  and body modes `none`, `form-data`, `x-www-form-urlencoded` and `raw` (JSON, Text, JavaScript, HTML or
  XML, with syntax highlighting and Beautify).
- **Authorization:** Bearer token, Basic auth or API key (header or query), set per request or inherited
  from the collection.
- **Collections:** folders, inline rename, duplicate, delete and filtering. Requests open in tabs with
  unsaved-change tracking.
- **Environments:** `{{variables}}` in URLs, headers and bodies, resolved from collection variables, then
  globals, then the active environment. Secret values are masked and kept out of exports. Dynamic values
  are also available: `{{$guid}}`, `{{$timestamp}}`, `{{$isoTimestamp}}` and `{{$randomInt}}`.
- **Responses:** status, time and size, a pretty or raw body with search, a headers table, and save or copy.
- **History:** every sent request, grouped by day, one click to reopen.
- **Import:** Hitman JSON, Postman v2.0/v2.1, OpenAPI 3 (JSON or YAML) and cURL. You can also paste a cURL
  command straight into the URL bar.
- **Export:** Hitman JSON (native) or Postman v2.1, with a live preview.
- **Generate code:** cURL, Python (requests), JavaScript (fetch), Go (net/http) and Dart (http).
- **Settings:** dark, light or system theme, editor font size, timeout, redirects, SSL verification and
  proxy. Open tabs are restored on launch.

## Requirements

- Python 3.10 or newer (developed on 3.14)
- macOS, Windows or Linux

## Setup

With [uv](https://docs.astral.sh/uv/):

```bash
uv venv
uv pip install -e ".[dev]"
```

Or with plain pip:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Run

```bash
.venv/bin/hitman
```

or `python -m hitman` with the virtual environment activated.

Data lives in `~/.hitman/hitman.db`. Set `HITMAN_HOME` to use a different folder (handy for testing).

## Test

```bash
.venv/bin/python -m pytest
```

## Keyboard shortcuts

On macOS, `Ctrl` is `⌘` (tab cycling uses the Control key, like browsers).

| Action | Shortcut |
| --- | --- |
| Send request | Ctrl+Enter (or Enter in the URL bar) |
| New request | Ctrl+N |
| Save request | Ctrl+S |
| Close tab | Ctrl+W |
| Search requests | Ctrl+K |
| Import | Ctrl+O |
| Toggle sidebar | Ctrl+B |
| Generate code | Ctrl+Alt+C |
| Settings | Ctrl+, |
| Next / previous tab | Ctrl+Tab / Ctrl+Shift+Tab |
| Focus URL bar | Ctrl+L |

## Project layout

```
hitman/
  core/        Pure Python domain logic: models, URL and variable handling, HTTP (requests),
               cURL parsing, code generation, import and export. No Qt imports.
  storage/     SQLite schema migrations and repositories (the only code that writes SQL).
  services/    Workspace state, open-tab session and the background request runner.
  ui/          PySide6 interface
    widgets/   Reusable widgets: code editor, key/value table, tabs, popovers, toast…
    sidebar/   Collections, environments and history panels
    request/   Tab strip, URL bar, request sections
    response/  Response viewer
    dialogs/   Save, collection, import, export, environments, code and settings dialogs
    theme.py   Design tokens and the application style sheet (dark and light)
  assets/fonts Geist and Geist Mono (SIL Open Font License 1.1)
tests/         Unit and offscreen widget tests
```

## License

The application code is licensed under the LGPL-2.1 (see `LICENSE`). The bundled Geist fonts have their
own license; see `hitman/assets/fonts/README.md`.
