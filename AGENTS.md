# AGENTS.md

This repository contains `a800mon`, a curses-based monitor UI and CLI for Atari800.

## Project Overview
- **UI/CLI split**: `a800mon/cli.py` exposes CLI commands; the monitor UI is launched from `a800mon/main.py`.
- **Curses UI**: windows are defined in `a800mon/ui.py` and composed in `a800mon/main.py`.
- **RPC**: all emulator interaction goes through `a800mon/rpc.py` and the socket transport in `a800mon/socket.py`.
- **State model**: runtime UI state lives in `a800mon/appstate.py`.

## Architecture Rules
- **Single source of truth**: UI state is stored only in `appstate.state` (read-only). Any mutation must go through `appstate.store` or the `ActionDispatcher`.
- **No state writes in render**: rendering must be side-effect free. Do not change state in `render()` methods.
- **Input handling**: visual components should not handle input. Input is handled by non-visual components (see `ShortcutInput`).
- **Dispatcher for actions**: UI actions are routed via `ActionDispatcher` (`a800mon/actions.py`). Callbacks may run immediate logic but must use the dispatcher to change state.
- **Focus**: focus is controlled by `Screen.focus(...)`. Do not use `window._screen`.
- **Active mode**: the active shortcut layer is determined by `state.active_mode` only. `ShortcutManager` is just a registry.

## Shortcuts and Layers
- Layers are defined in `ShortcutLayer` (`a800mon/shortcuts.py`).
- `ShortcutLayer` has a `color` (enum `ui.Color`) used by the `ShortcutBar`.
- Global shortcuts are registered in `ShortcutManager` and should not be rendered in the shortcut bar unless explicitly required.

## Code Style and Conventions
- Keep logic explicit. Avoid reflection, magic `getattr`/`setattr`, and implicit type coercion.
- Prefer deterministic actions (`SET_*`) over implicit toggles when practical.
- Avoid injecting large object graphs into helpers; prefer closures in `main.py` when wiring UI callbacks.
- Keep changes minimal and localized. Avoid refactors unless explicitly requested.
- Generate compact code, without necessary branches
- Do not generate sanity checks where not requried
- Avoid `isinstance()` checks in loops; prefer duck typing
- DO NOT REPEAT
- KEEP IT SIMPLE STUPID

## Testing / Sanity Checks
- Basic compile check: `python3 -m py_compile a800mon/*.py`
- Run UI: `./bin/a800mon` (requires a running emulator socket).

## Notes
- When adjusting display-list inspection, update `state.displaylist_inspect` and `state.dlist_selected_region` via the dispatcher/store only.
- Do not introduce new mutable state on visual components unless explicitly approved.
