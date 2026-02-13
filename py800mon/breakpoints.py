import curses
import re

from .actions import Actions
from .app import VisualRpcComponent
from .appstate import state
from .datastructures import BreakpointClauseEntry, BreakpointConditionEntry
from .inputwidget import InputWidget
from .memory import parse_hex
from .rpc import RpcException
from .ui import Color, DialogInput, DialogWidget, GridWidget

BP_CONDITION_TYPES = {
    "pc": 1,
    "a": 2,
    "x": 3,
    "y": 4,
    "s": 5,
    "read": 6,
    "write": 7,
    "access": 8,
}

BP_TYPE_NAMES = {
    1: "pc",
    2: "a",
    3: "x",
    4: "y",
    5: "s",
    6: "read",
    7: "write",
    8: "access",
}

BP_OP_NAMES = {
    1: "<",
    2: "<=",
    3: "==",
    4: "<>",
    5: ">=",
    6: ">",
}

BP_OPS = {
    "<": 1,
    "<=": 2,
    "=": 3,
    "==": 3,
    "<>": 4,
    "!=": 4,
    ">=": 5,
    ">": 6,
}

_BP_AND_WORD_RE = re.compile(r"\bAND\b", re.IGNORECASE)
_BP_OR_WORD_RE = re.compile(r"\bOR\b", re.IGNORECASE)


def split_bp_expression(expr: str) -> tuple[str, str, str]:
    text = expr.strip()
    for op in ("<=", ">=", "==", "<>", "!=", "=", "<", ">"):
        pos = text.find(op)
        if pos <= 0:
            continue
        left = text[:pos].strip()
        right = text[pos + len(op):].strip()
        if right:
            return left, op, right
    raise ValueError(f"Invalid breakpoint condition: {expr}")


def parse_bp_condition(expr: str) -> BreakpointConditionEntry:
    left, op, value_text = split_bp_expression(expr)
    op_id = BP_OPS.get(op)
    if op_id is None:
        raise ValueError(f"Invalid breakpoint operator in condition: {expr}")
    left_key = left.strip().lower()
    addr = 0
    cond_type = BP_CONDITION_TYPES.get(left_key)
    if cond_type is None:
        if left_key.startswith("mem[") and left_key.endswith("]"):
            cond_type = 9
            try:
                addr = parse_hex(left_key[4:-1])
            except ValueError as ex:
                raise ValueError(f"Invalid memory address in condition: {expr}") from ex
        elif left_key.startswith("mem:"):
            cond_type = 9
            try:
                addr = parse_hex(left_key[4:])
            except ValueError as ex:
                raise ValueError(f"Invalid memory address in condition: {expr}") from ex
        else:
            raise ValueError(f"Invalid breakpoint source in condition: {expr}")
    try:
        value = parse_hex(value_text)
    except ValueError as ex:
        raise ValueError(f"Invalid breakpoint value in condition: {expr}") from ex
    if value < 0 or value > 0xFFFF:
        raise ValueError(f"Breakpoint value out of range (0..FFFF): {value_text}")
    if addr < 0 or addr > 0xFFFF:
        raise ValueError(f"Breakpoint address out of range (0..FFFF): {left}")
    return BreakpointConditionEntry(
        cond_type=cond_type & 0xFF,
        op=op_id & 0xFF,
        addr=addr & 0xFFFF,
        value=value & 0xFFFF,
    )


def parse_bp_clause(expr: str) -> tuple[BreakpointConditionEntry, ...]:
    clauses = parse_bp_clauses(expr)
    if len(clauses) != 1:
        raise ValueError("Use a single OR clause in this context.")
    return clauses[0]


def _normalize_bp_logic(expr: str) -> str:
    text = _BP_AND_WORD_RE.sub("&&", str(expr))
    return _BP_OR_WORD_RE.sub("||", text)


def parse_bp_clauses(expr: str) -> tuple[tuple[BreakpointConditionEntry, ...], ...]:
    text = _normalize_bp_logic(expr).strip()
    if not text:
        raise ValueError("Breakpoint clause is empty.")
    raw_clauses = [part.strip() for part in text.split("||")]
    if not raw_clauses or any(not part for part in raw_clauses):
        raise ValueError("Invalid breakpoint clause.")
    out = []
    for raw_clause in raw_clauses:
        parts = [part.strip() for part in raw_clause.split("&&")]
        if not parts or any(not part for part in parts):
            raise ValueError("Invalid breakpoint clause.")
        out.append(tuple(parse_bp_condition(part) for part in parts))
    return tuple(out)


def format_bp_value(cond_type: int, value: int) -> str:
    if cond_type in (2, 3, 4, 5):
        return f"${value:02X}"
    return f"${value:04X}"


def format_bp_condition(cond: BreakpointConditionEntry) -> str:
    cond_type = cond.cond_type
    op = cond.op
    addr = cond.addr
    value = cond.value
    op_text = BP_OP_NAMES.get(op, f"op{op}")
    if cond_type == 9:
        return f"mem[{addr:04X}] {op_text} {format_bp_value(cond_type, value)}"
    name = BP_TYPE_NAMES.get(cond_type, f"type{cond_type}")
    return f"{name} {op_text} {format_bp_value(cond_type, value)}"


class BreakpointsViewer(VisualRpcComponent):
    def __init__(self, rpc, window):
        super().__init__(rpc, window)
        self.grid = GridWidget(window, col_gap=0)
        self.grid.add_column("index", width=0, attr=Color.ADDRESS.attr())
        self.grid.add_column("expr", width=0, attr=Color.TEXT.attr())
        self._last_snapshot = None
        self._last_state_seq = None
        self._enabled = False
        self._rows = []
        self._selected_row_offset = 0
        self._input_snapshot = ""
        self._input_active = False
        self._input_invalid = False
        self._pending_add_clauses = None
        self._pending_delete = None
        self._pending_clear = False
        self._pending_enabled = None
        self._refresh_requested = False
        self._input_clauses = None
        self._clear_dialog = DialogWidget(self.window)
        self._input_widget = InputWidget(
            self.window,
            max_length=None,
            on_change=self._on_input_change,
        )

    async def update(self):
        if not state.breakpoints_supported:
            return False
        changed = await self._apply_pending_ops()
        cur_seq = state.state_seq
        if (
            not self._refresh_requested
            and self._last_state_seq == cur_seq
            and self._last_snapshot is not None
        ):
            return changed
        self._last_state_seq = cur_seq
        try:
            bp = await self.rpc.breakpoint_list()
        except RpcException:
            return changed
        self._refresh_requested = False
        self._clamp_selected(len(bp.clauses))
        snapshot = bp
        if snapshot == self._last_snapshot:
            return changed
        self._last_snapshot = snapshot
        self._enabled = bool(bp.enabled)
        self._rows = list(bp.clauses)
        return True

    def render(self, force_redraw=False):
        self._render_grid()

    def _render_grid(self):
        ih = self.window._ih
        if ih <= 0:
            return
        dialog_active = self._clear_dialog.active
        input_active = self._input_active
        row_base = 1 if (input_active or dialog_active) else 0
        self.window.set_tag_active("bp_enabled", self._enabled)
        self._selected_row_offset = row_base

        rows = []
        if row_base:
            rows.append(("", ""))

        if not self._rows:
            rows.append(("", "No breakpoint clauses."))
            self.grid.set_selected_row(None)
        else:
            for idx, clause in enumerate(self._rows, start=1):
                rows.append((f"#{idx:02d} ", self._format_clause_text(clause)))
            selected = self._selected_index()
            if selected is None:
                self.grid.set_selected_row(None)
            else:
                self.grid.set_selected_row(selected + self._selected_row_offset)
        self.grid.set_data(rows)
        self.grid.render()

        if dialog_active:
            self._clear_dialog.render()
        elif input_active:
            self.window.cursor = (0, 0)
            color = Color.INPUT_INVALID if self._input_invalid else Color.TEXT
            attr = color.attr() | curses.A_REVERSE
            self.window.print(self._input_widget.buffer, attr=attr)
            self.window.fill_to_eol(attr=attr)

    def _format_clause_text(self, clause):
        if not isinstance(clause, BreakpointClauseEntry):
            return str(clause)
        parts = []
        for cond in clause.conditions:
            parts.append(format_bp_condition(cond))
        return " AND ".join(parts)

    def handle_input(self, ch):
        if self._clear_dialog.active:
            result = self._clear_dialog.handle_input(ch)
            if result == DialogInput.CONFIRM:
                self._pending_clear = True
            return not result == DialogInput.NONE
        if self.app.screen.focused is not self.window:
            return False
        if ch == ord("/"):
            self._open_input("")
            return True
        if self.grid.handle_input(ch):
            return True
        if ch in (curses.KEY_DC, 330):
            self._queue_delete_selected()
            return True
        if ch in (ord("c"), ord("C")):
            self._clear_dialog.activate("Clear all breakpoints?", "YES")
            return True
        if ch == ord(" ") or ch in (ord("e"), ord("E")):
            self._pending_enabled = not self._enabled
            return True
        return False

    def _queue_delete_selected(self):
        idx = self._selected_index()
        if idx is None or idx < 0 or idx >= len(self._rows):
            return
        self._pending_delete = int(idx)
        if idx >= len(self._rows) - 1:
            if len(self._rows) <= 1:
                self._set_selected_index(None)
            else:
                self._set_selected_index(len(self._rows) - 2)

    def _close_input(self):
        self._input_active = False
        self._input_widget.set_invalid(False)
        self._input_invalid = False
        self._input_clauses = None
        self._input_widget.deactivate()
        self.app.dispatch_action(Actions.SET_INPUT_FOCUS, None)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _open_input(self, initial: str):
        self._input_active = True
        self._input_snapshot = str(initial)
        self._input_widget.activate(self._input_snapshot)
        self._input_widget.set_invalid(False)
        self._input_invalid = False
        self._input_clauses = None
        self.app.dispatch_action(Actions.SET_INPUT_FOCUS, self._handle_text_input)
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def _on_input_change(self, query):
        text = str(query).strip()
        if not text:
            self._input_clauses = None
            self._input_invalid = False
            self._input_widget.set_invalid(False)
            return
        try:
            self._input_clauses = parse_bp_clauses(text)
            self._input_invalid = False
            self._input_widget.set_invalid(False)
        except ValueError:
            self._input_clauses = None
            self._input_invalid = True
            self._input_widget.set_invalid(True)

    def _handle_text_input(self, ch):
        if ch == 27:
            self._input_widget.set_buffer(self._input_snapshot)
            self._close_input()
            return True
        if ch in (10, 13, curses.KEY_ENTER):
            if self._input_invalid:
                return True
            if self._input_clauses is not None:
                self._pending_add_clauses = self._input_clauses
            self._close_input()
            return True
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self._input_widget.backspace()
            return True
        if self._input_widget.append_char(ch):
            return True
        return True

    async def _apply_pending_ops(self):
        changed = False
        if self._pending_clear:
            self._pending_clear = False
            try:
                await self.rpc.breakpoint_clear()
                self._set_selected_index(None)
                self._refresh_requested = True
                changed = True
            except RpcException:
                pass
        if self._pending_delete is not None:
            idx = int(self._pending_delete)
            self._pending_delete = None
            try:
                await self.rpc.breakpoint_delete_clause(idx)
                self._refresh_requested = True
                changed = True
            except RpcException:
                pass
        if self._pending_enabled is not None:
            enabled = bool(self._pending_enabled)
            self._pending_enabled = None
            try:
                await self.rpc.breakpoint_set_enabled(enabled)
                self._refresh_requested = True
                changed = True
            except RpcException:
                pass
        if self._pending_add_clauses is not None:
            clauses = list(self._pending_add_clauses)
            self._pending_add_clauses = None
            for clause in clauses:
                try:
                    await self.rpc.breakpoint_add_clause(list(clause))
                    self._refresh_requested = True
                    changed = True
                except RpcException:
                    break
        return changed

    def _clamp_selected(self, row_count: int):
        if row_count <= 0:
            self._set_selected_index(None)
            return
        cur = self._selected_index()
        if cur is None:
            return
        if cur < 0:
            self._set_selected_index(0)
        elif cur >= row_count:
            self._set_selected_index(row_count - 1)

    def _selected_index(self):
        idx = self.grid.selected_row
        if idx is None:
            return None
        idx = int(idx) - self._selected_row_offset
        if idx < 0:
            return None
        if idx >= len(self._rows):
            return None
        return idx

    def _set_selected_index(self, idx: int | None):
        if idx is None or len(self._rows) == 0:
            self.grid.set_selected_row(None)
            return
        value = max(0, min(int(idx), len(self._rows) - 1))
        self.grid.set_selected_row(value + self._selected_row_offset)
