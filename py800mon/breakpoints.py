import re

from .datastructures import BreakpointConditionEntry
from .atari.memory import parse_hex

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
        right = text[pos + len(op) :].strip()
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
