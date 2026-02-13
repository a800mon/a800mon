from .app import VisualRpcComponent
from .appstate import state
from .datastructures import Breakpoint, BreakpointClauseEntry, BreakpointConditionEntry
from .memory import parse_hex
from .rpc import RpcException
from .ui import Color

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
    4: "!=",
    5: ">=",
    6: ">",
}

BP_OPS = {
    "<": 1,
    "<=": 2,
    "=": 3,
    "==": 3,
    "!=": 4,
    ">=": 5,
    ">": 6,
}


def split_bp_expression(expr: str) -> tuple[str, str, str]:
    text = expr.strip()
    for op in ("<=", ">=", "==", "!=", "=", "<", ">"):
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

    def bind_input(self, screen):
        self._screen = screen

    async def update(self):
        if not state.breakpoints_supported:
            return False
        cur_seq = state.state_seq
        if self._last_state_seq == cur_seq and self._last_snapshot is not None:
            return False
        self._last_state_seq = cur_seq
        try:
            bp = await self.rpc.breakpoint_list()
        except RpcException:
            return False
        snapshot = bp
        if snapshot == self._last_snapshot:
            return False
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

    def attach_dispatcher(self, dispatcher):
        self._dispatcher = dispatcher

    def render(self, force_redraw=False):
        ih = self.window._ih
        if ih <= 0:
            return
        self.window.cursor = (0, 0)
        self.window.set_tag_active("bp_enabled", state.breakpoints_enabled)

        max_rows = ih
        if not state.breakpoints:
            if max_rows > 0:
                self.window.print("No breakpoint clauses.", attr=Color.COMMENT.attr())
                self.window.clear_to_eol()
                self.window.newline()
                self.window.clear_to_bottom()
            return

        for idx, clause in enumerate(state.breakpoints[:max_rows], start=1):
            self.window.print(f"#{idx:02d} ", attr=Color.ADDRESS.attr())
            self._print_clause(clause)
            self.window.clear_to_eol()
            self.window.newline()
        self.window.clear_to_bottom()

    def _print_clause(self, clause: BreakpointClauseEntry):
        for idx, cond in enumerate(clause.conditions):
            if idx:
                self.window.print(" && ", attr=Color.TEXT.attr())
            self._print_condition(cond)

    def _print_condition(self, cond: BreakpointConditionEntry):
        op = BP_OP_NAMES.get(cond.op, f"op{cond.op}")
        if cond.cond_type == 9:
            self.window.print("mem[", attr=Color.TEXT.attr())
            self.window.print(f"{cond.addr:04X}", attr=Color.ADDRESS.attr())
            self.window.print("]", attr=Color.TEXT.attr())
        else:
            name = BP_TYPE_NAMES.get(cond.cond_type, f"type{cond.cond_type}")
            self.window.print(name, attr=Color.TEXT.attr())
        self.window.print(f" {op} ", attr=Color.TEXT.attr())
        if cond.cond_type in (2, 3, 4, 5):
            self.window.print(f"{cond.value:02X}", attr=Color.ADDRESS.attr())
        else:
            self.window.print(f"{cond.value:04X}", attr=Color.ADDRESS.attr())

    def handle_input(self, ch):
        if self._screen is None:
            return False
        if self._screen.focused is not self.window:
            return False
        return False
