import curses
import time

from .app import VisualRpcComponent
from .appstate import state
from .disasm import disasm_6502_one_parts
from .rpc import RpcException
from .ui import Color

FLOW_MNEMONICS = {
    "JMP",
    "JSR",
    "BCC",
    "BCS",
    "BEQ",
    "BMI",
    "BNE",
    "BPL",
    "BVC",
    "BVS",
    "BRA",
}


class HistoryViewer(VisualRpcComponent):
    def __init__(self, *args, **kwargs):
        self._update_interval = kwargs.pop("update_interval", 0.05)
        self._reverse_order = bool(kwargs.pop("reverse_order", False))
        super().__init__(*args, **kwargs)
        self._last_update = 0.0
        self._entries = []
        self._can_disasm = True
        self._last_title_pc = None
        self._next_pc = None
        self._next_opbytes = b""

    def update(self):
        now = time.time()
        if self._last_update and now - self._last_update < self._update_interval:
            return
        try:
            self._entries = self.rpc.history()
            pc = state.cpu.pc & 0xFFFF
            self._next_pc = pc
            self._next_opbytes = self.rpc.read_memory(pc, 3)
            self._last_update = now
        except RpcException:
            pass

    def render(self, force_redraw=False):
        title_pc = state.cpu.pc
        if title_pc != self._last_title_pc:
            self._last_title_pc = title_pc
            self.window.set_title(f"History [PC: {title_pc:04X}]")

        self.window.cursor = 0, 0
        if self.window._ih <= 0:
            return
        self.window.clear_to_bottom()
        self.window.cursor = 0, 0

        next_pc = state.cpu.pc & 0xFFFF
        next_bytes = self._next_opbytes if self._next_pc == next_pc else b""
        raw_text, asm_text = self._format_disasm(next_pc, next_bytes)

        if self._reverse_order:
            rows = list(reversed(self._entries[: max(0, self.window._ih - 1)]))
            for entry in rows:
                raw_row, asm_row = self._format_disasm(entry.pc, entry.opbytes)
                self._print_row(entry.pc, raw_row, asm_row, 0)
                self._finish_row(inverse=False)
            self.window.cursor = (0, self.window._ih - 1)
            self._print_row(next_pc, raw_text, asm_text, curses.A_REVERSE)
            self.window.fill_to_eol(attr=curses.A_REVERSE)
        else:
            # Synthetic first line: next instruction at current PC.
            self._print_row(next_pc, raw_text, asm_text, curses.A_REVERSE)
            self._finish_row(inverse=True)

            if self.window._ih > 1:
                rows = self._entries[: self.window._ih - 1]
                for entry in rows:
                    raw_row, asm_row = self._format_disasm(entry.pc, entry.opbytes)
                    self._print_row(entry.pc, raw_row, asm_row, 0)
                    self._finish_row(inverse=False)

    def _format_disasm(self, pc: int, opbytes: bytes) -> tuple[str, str]:
        if self._can_disasm:
            try:
                return disasm_6502_one_parts(pc, opbytes)
            except RuntimeError:
                self._can_disasm = False
        return " ".join(f"{b:02X}" for b in opbytes), ""

    def _print_asm(self, asm_text: str, rev_attr: int = 0):
        if not asm_text:
            return
        parts = asm_text.split(None, 1)
        mnemonic = parts[0].upper()
        operand = parts[1] if len(parts) > 1 else ""
        self.window.print(mnemonic, attr=Color.MNEMONIC.attr() | rev_attr)
        if not operand:
            return
        self.window.print(" ", attr=rev_attr)
        if mnemonic not in FLOW_MNEMONICS:
            self.window.print(operand, attr=rev_attr)
            return
        span = _find_hex_addr_span(operand)
        if span is None:
            self.window.print(operand, attr=rev_attr)
            return
        start, end = span
        self.window.print(operand[:start], attr=rev_attr)
        self.window.print(operand[start:end], attr=Color.ADDRESS.attr() | rev_attr)
        self.window.print(operand[end:], attr=rev_attr)

    def _print_row(self, pc: int, raw_text: str, asm_text: str, rev_attr: int, prefix: str = ""):
        if prefix:
            self.window.print(prefix, attr=rev_attr)
        self.window.print(f"{pc:04X}:", attr=Color.ADDRESS.attr() | rev_attr)
        self.window.print(" ", attr=rev_attr)
        self.window.print(f"{raw_text:<8} ", attr=rev_attr)
        self._print_asm(asm_text, rev_attr)

    def _finish_row(self, inverse: bool):
        _, y_before = self.window.cursor
        if inverse:
            self.window.fill_to_eol(attr=curses.A_REVERSE)
        else:
            self.window.clear_to_eol()
        _, y_after = self.window.cursor
        if y_after == y_before:
            self.window.newline()


def _find_hex_addr_span(text: str):
    start = text.find("$")
    if start < 0:
        return None
    end = start + 1
    while end < len(text):
        ch = text[end]
        if ("0" <= ch <= "9") or ("A" <= ch <= "F") or ("a" <= ch <= "f"):
            end += 1
            continue
        break
    if end == start + 1:
        return None
    return start, end
