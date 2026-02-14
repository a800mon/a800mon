# AGENTS.md

This repository contains `a800mon`, a curses-based monitor UI and CLI for Atari800.

## Project Overview
- **UI/CLI split**: `py800mon/cli.py` exposes CLI commands; the monitor UI is launched from `py800mon/main.py`.
- **Curses UI**: windows are defined in `py800mon/ui.py` and composed in `py800mon/main.py`.
- **RPC**: all emulator interaction goes through `py800mon/rpc.py` and the socket transport in `py800mon/socket.py`.
- **State model**: runtime UI state lives in `py800mon/appstate.py`.

## Go Port Notes
- **Go version**: use Go `1.21.x` (module declares `go 1.21` in `go800mon/go.mod`).
- **Port layout**: Go implementation mirrors Python package structure in `go800mon/a800mon/*.go`.
- **Go entrypoint**: CLI binary entry is `go800mon/cmd/go800mon/main.go`, which calls `a800mon.Main(...)`.
- **Go CLI parser**: use `kong` for command parsing/help in `go800mon/a800mon/cli.go`; keep command/flag behavior aligned with Python `argparse`.
- **UI backend**: Go monitor UI uses `ncurses` via CGO (`go800mon/a800mon/ui.go`), not ANSI terminal redraw hacks.
- **Parallel development rule**: prototype behavior in Python first, then port the same behavior to matching Go module names where practical.
- **Behavior parity**: when changing UI logic, shortcuts, dispatcher flow, or rendering semantics, keep Python and Go behavior aligned unless explicitly marked experimental.
- **Go CLI default command parity**: when no subcommand is provided, default to `monitor` mode even if global flags are present, matching Python CLI behavior.
- **UI refresh correctness (Go)**: redraw skipping is allowed only when rendered output would be identical; if backend data can change visible rows, the view must refresh.
- **UI refresh implementation freedom (Go)**: implementation details of refresh optimization are intentionally not mandated here.
- **Default request scope**: unless user says otherwise, treat feature/behavior changes as potentially applying to both Python (`py800mon/*`) and Go (`go800mon/a800mon/*`).
- **Ambiguity rule**: if it is unclear whether a request targets Python, Go, or both, ask a short clarification question before implementing.
- **Go modules in VCS**: commit both `go.mod` and `go.sum` when dependencies change.

## Architecture Rules
- **Single source of truth**: UI state is stored only in `appstate.state` (read-only). Any mutation must go through `appstate.store` or the `ActionDispatcher`.
- **No state writes in render**: rendering must be side-effect free. Do not change state in `render()` methods.
- **Input handling**: visual components should not handle input. Input is handled by non-visual components (see `ShortcutInput`).
- **Dispatcher for actions**: UI actions are routed via `ActionDispatcher` (`py800mon/actions.py`). Callbacks may run immediate logic but must use the dispatcher to change state.
- **Focus**: focus is controlled by `Screen.focus(...)`. Do not use `window._screen`.
- **Active mode**: the active shortcut layer is determined by `state.active_mode` only. `ShortcutManager` is just a registry.
- **RPC unpacking location**: binary protocol unpacking/validation MUST happen in RPC modules (`py800mon/rpc.py`, `go800mon/internal/rpc/*`), never in CLI/UI command handlers.
- **Typed command results**: when a command returns a structured payload, define/extend data structures first (`py800mon/datastructures.py`, `go800mon/a800mon/datastructures.go`) and make RPC return those types.
- **CLI/UI responsibility**: CLI/UI handlers should orchestrate input/output only. They must call dedicated logic/RPC methods and avoid embedding protocol parsing or domain logic.
- **Logic vs usage split**: keep reusable logic/state machines in dedicated modules/classes; keep prompt/dispatch glue in CLI entry modules.
- **Breakpoints architecture**: breakpoint business logic must be separated from CLI wiring and transport calls; CLI should only parse args, call dedicated APIs, and print results.
- **Breakpoint expression parser**: parse/format of breakpoint expressions (CLI/UI syntax) must live in breakpoint modules, not in CLI command files.

## Shortcuts and Layers
- Layers are defined in `ShortcutLayer` (`py800mon/shortcuts.py`).
- `ShortcutLayer` has a `color` (enum `ui.Color`) used by the `ShortcutBar`.
- Global shortcuts are registered in `ShortcutManager` and should not be rendered in the shortcut bar unless explicitly required.

## Code Style and Conventions
- **Coding standards compliance**: follow `CODING_STANDARDS.md` for every change.
- **Strict approval gate**: do not change any file unless the operator explicitly confirms the exact change scope first.
- **No unapproved edits**: if confirmation is missing or ambiguous, stop and ask; do not proceed with assumptions.
- **Mandatory rigor**: apply this approval rule rigorously on every task, without exceptions.
- **Decision rule**: if request scope/intent is ambiguous or there is more than one valid design path, ask the operator for a decision before implementing.
- **No autonomy drift**: do not take autonomous architectural/product decisions without explicit operator direction (unwanted autonomy is treated as a failure).
- **Execution honesty**: do not claim a change was done unless it is actually present in code.
- **Execution rigor**: execute requested changes scrupulously and verify affected code paths before reporting completion.
- **No fake cleanup**: if asked to remove a pattern (e.g. `bool(...)`, `int(...)`, `is None`), do a repository-wide grep pass, apply fixes, then run grep again and report leftovers explicitly.
- **No redundant wrappers**: do not keep/add redundant coercions (`bool/int/str`) when type is already guaranteed.
- UI/UX quality is important even for a developer tool: preserve readability, visual stability, and interaction ergonomics.
- Prefer clean code and maintainable design choices (clear naming, small focused functions, explicit dependencies, and minimal coupling) that reduce long-term maintenance cost.
- Keep logic explicit. Avoid reflection, magic `getattr`/`setattr`, and implicit type coercion.
- **DRY is mandatory**: do not copy parsing/validation logic across commands.
- **Central parsing utils**: hex parsing, numeric range checks, and payload decoding must be implemented once in shared util modules and reused by CLI/UI/RPC code.
- **No local parser clones**: command handlers must not define ad-hoc `_parse_*`/`parse*` duplicates when a shared helper exists.
- Prefer deterministic actions (`SET_*`) over implicit toggles when practical.
- Avoid injecting large object graphs into helpers; prefer closures in `main.py` when wiring UI callbacks.
- Keep changes minimal and localized. Avoid refactors unless explicitly requested.
- Do not remove existing code blocks/handlers unless explicitly requested by the user.
- Generate compact code, without necessary branches
- Do not generate sanity checks where not requried
- Avoid `isinstance()` checks in loops; prefer duck typing
- DO NOT REPEAT
- KEEP IT SIMPLE STUPID
- DO NOT GENERATE BLOAT!

## Testing / Sanity Checks
- Basic compile check: `python3 -m py_compile py800mon/*.py`
- Run UI: `./bin/py800mon` (requires a running emulator socket).
- Go build check: `GOCACHE=/tmp/go-build-cache go build -o /tmp/go800mon ./go800mon/cmd/go800mon`
- Run Go UI: `./bin/go800mon` (requires a running emulator socket).
- Go regression coverage: CLI default command resolution with global flags and no explicit subcommand.
- Go regression coverage: view refresh when payload changes without obvious shape/range changes.

## Notes
- When adjusting display-list inspection, update `state.displaylist_inspect` and `state.dlist_selected_region` via the dispatcher/store only.
- Do not introduce new mutable state on visual components unless explicitly approved.
- RPC transport must always read response payload bytes indicated by frame length, even when `status != 0`, and pass payload to error objects (do not drop server error text).
- CLI errors should be user-facing one-liners (no traceback/panic dump for expected RPC failures).
- Keep Python/Go error semantics aligned, but do not force byte-identical wording for stdlib/system-originated errors.
- Reviewer note (human or agent): review against these rules rigorously and be strict about violations/risk.
- Reviewer note (human or agent): do not apply corrective changes autonomously; report findings and consult the operator or maintainer before any fix.
