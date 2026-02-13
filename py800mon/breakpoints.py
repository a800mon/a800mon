import curses
import re

from .actions import Actions
from .app import VisualRpcComponent
from .appstate import state
from .datastructures import BreakpointClauseEntry, BreakpointConditionEntry
from .inputwidget import InputWidget
from .memory import parse_hex
from .rpc import RpcException
from .ui import Color, DialogInput, DialogWidget

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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_snapshot = None
        self._last_state_seq = None
        self._screen = None
        self._dispatcher = None
        self._selected = None
        self._input_snapshot = ""
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

    def bind_input(self, screen):
        self._screen = screen

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
        if (
            self._dispatcher is not None
            and (
                state.breakpoints_enabled != bp.enabled
                or state.breakpoints != list(bp.clauses)
            )
        ):
            self._dispatcher.update_breakpoints(bp.enabled, list(bp.clauses))
            return True
        return changed

    def attach_dispatcher(self, dispatcher):
        self._dispatcher = dispatcher

    def render(self, force_redraw=False):
        ih = self.window._ih
        if ih <= 0:
            return
        has_focus = self._screen is not None and self._screen.focused is self.window
        dialog_active = self._clear_dialog.active
        input_active = state.input_focus and state.input_target == "breakpoints"
        row_base = 1 if (input_active or dialog_active) else 0
        max_rows = max(0, ih - row_base)
        self.window.cursor = (0, row_base)
        self.window.set_tag_active("bp_enabled", state.breakpoints_enabled)

        if dialog_active:
            self._clear_dialog.render()
            self.window.cursor = (0, row_base)
        elif input_active:
            self.window.cursor = (0, 0)
            color = Color.INPUT_INVALID if self._input_invalid else Color.TEXT
            attr = color.attr() | curses.A_REVERSE
            self.window.print(state.input_buffer, attr=attr)
            self.window.fill_to_eol(attr=attr)
            self.window.cursor = (0, row_base)

        if not state.breakpoints:
            if max_rows > 0:
                self.window.cursor = (0, row_base)
                self.window.print("No breakpoint clauses.", attr=Color.COMMENT.attr())
                self.window.clear_to_eol()
                self.window.newline()
                self.window.clear_to_bottom()
            return

        for idx, clause in enumerate(state.breakpoints[:max_rows], start=1):
            rev_attr = 0
            if has_focus and self._selected is not None and self._selected == idx - 1:
                rev_attr = curses.A_REVERSE
            self.window.print(f"#{idx:02d} ", attr=Color.ADDRESS.attr() | rev_attr)
            self._print_clause(clause, rev_attr=rev_attr)
            self.window.clear_to_eol()
            self.window.newline()
        self.window.clear_to_bottom()

    def _print_clause(self, clause: BreakpointClauseEntry, rev_attr=0):
        for idx, cond in enumerate(clause.conditions):
            if idx:
                self.window.print(" AND ", attr=Color.TEXT.attr() | rev_attr)
            self._print_condition(cond, rev_attr=rev_attr)

    def _print_condition(self, cond: BreakpointConditionEntry, rev_attr=0):
        op = BP_OP_NAMES.get(cond.op, f"op{cond.op}")
        if cond.cond_type == 9:
            self.window.print("mem[", attr=Color.TEXT.attr() | rev_attr)
            self.window.print(f"{cond.addr:04X}", attr=Color.ADDRESS.attr() | rev_attr)
            self.window.print("]", attr=Color.TEXT.attr() | rev_attr)
        else:
            name = BP_TYPE_NAMES.get(cond.cond_type, f"type{cond.cond_type}")
            self.window.print(name, attr=Color.TEXT.attr() | rev_attr)
        self.window.print(f" {op} ", attr=Color.TEXT.attr() | rev_attr)
        if cond.cond_type in (2, 3, 4, 5):
            self.window.print(f"{cond.value:02X}", attr=Color.ADDRESS.attr() | rev_attr)
        else:
            self.window.print(f"{cond.value:04X}", attr=Color.ADDRESS.attr() | rev_attr)

    def handle_input(self, ch):
        if self._screen is None:
            return False
        if self._clear_dialog.active:
            result = self._clear_dialog.handle_input(ch)
            if result == DialogInput.CONFIRM:
                self._pending_clear = True
            return not result == DialogInput.NONE
        if state.input_focus:
            if state.input_target != "breakpoints":
                return False
            return self._handle_text_input(ch)
        if self._screen.focused is not self.window:
            return False
        if ch == ord("/"):
            self._open_input("")
            return True
        if ch in (curses.KEY_UP, curses.KEY_DOWN):
            if not state.breakpoints:
                return True
            cur = self._selected
            if cur is None:
                self._selected = len(state.breakpoints) - 1 if ch == curses.KEY_UP else 0
                return True
            if ch == curses.KEY_UP and cur > 0:
                self._selected = cur - 1
            elif ch == curses.KEY_DOWN and cur < len(state.breakpoints) - 1:
                self._selected = cur + 1
            return True
        if ch in (curses.KEY_DC, 330):
            self._queue_delete_selected()
            return True
        if ch in (ord("c"), ord("C")):
            self._clear_dialog.activate("Clear all breakpoints?", "YES")
            return True
        if ch in (ord("e"), ord("E")):
            self._pending_enabled = not state.breakpoints_enabled
            return True
        return False

    def _queue_delete_selected(self):
        idx = self._selected
        if idx is None or idx < 0 or idx >= len(state.breakpoints):
            return
        self._pending_delete = int(idx)
        if idx >= len(state.breakpoints) - 1:
            if len(state.breakpoints) <= 1:
                self._selected = None
            else:
                self._selected = len(state.breakpoints) - 2

    def _close_input(self):
        if self._dispatcher is None:
            return
        self._input_widget.set_invalid(False)
        self._input_invalid = False
        self._input_clauses = None
        self._input_widget.deactivate()
        self._dispatcher.dispatch(Actions.SET_INPUT_FOCUS, False)
        self._dispatcher.dispatch(Actions.SET_INPUT_TARGET, None)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _open_input(self, initial: str):
        if self._dispatcher is None:
            return
        self._input_snapshot = str(initial)
        self._input_widget.activate(self._input_snapshot)
        self._input_widget.set_invalid(False)
        self._input_invalid = False
        self._input_clauses = None
        self._dispatcher.dispatch(Actions.SET_INPUT_BUFFER, self._input_widget.buffer)
        self._dispatcher.dispatch(Actions.SET_INPUT_TARGET, "breakpoints")
        self._dispatcher.dispatch(Actions.SET_INPUT_FOCUS, True)
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
        if self._dispatcher is None:
            return False
        if ch == 27:
            self._input_widget.set_buffer(self._input_snapshot)
            self._dispatcher.dispatch(Actions.SET_INPUT_BUFFER, self._input_snapshot)
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
            if self._input_widget.backspace():
                self._dispatcher.dispatch(Actions.SET_INPUT_BUFFER, self._input_widget.buffer)
            return True
        if self._input_widget.append_char(ch):
            self._dispatcher.dispatch(Actions.SET_INPUT_BUFFER, self._input_widget.buffer)
            return True
        return True

    async def _apply_pending_ops(self):
        changed = False
        if self._pending_clear:
            self._pending_clear = False
            try:
                await self.rpc.breakpoint_clear()
                self._selected = None
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
            self._selected = None
            return
        if self._selected is None:
            return
        if self._selected < 0:
            self._selected = 0
        elif self._selected >= row_count:
            self._selected = row_count - 1
