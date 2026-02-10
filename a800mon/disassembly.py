import time

from .app import InputComponent, VisualRpcComponent
from .appstate import state
from .disasm import disasm_6502
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


class DisassemblyViewer(VisualRpcComponent):
    def __init__(self, *args, **kwargs):
        self._update_interval = kwargs.pop("update_interval", 0.05)
        super().__init__(*args, **kwargs)
        self._last_update = 0.0
        self._last_addr = None
        self._lines = []

    def update(self):
        if not state.disassembly_enabled:
            return
        if self.window._ih <= 0:
            return
        addr = state.disassembly_addr & 0xFFFF
        now = time.time()
        if (
            self._last_addr == addr
            and self._last_update
            and now - self._last_update < self._update_interval
        ):
            return
        read_len = max(3, self.window._ih * 3)
        try:
            data = self.rpc.read_memory(addr, read_len)
        except RpcException:
            return
        self._lines = disasm_6502(addr, data)[: self.window._ih]
        self._last_addr = addr
        self._last_update = now

    def render(self, force_redraw=False):
        self.window.cursor = 0, 0
        for line in self._lines[: self.window._ih]:
            if ":" in line:
                addr, rest = line.split(":", 1)
                self.window.print(f"{addr}:", attr=Color.ADDRESS.attr())
                formatted = rest.lstrip()
                raw_text = formatted[:8]
                asm_text = formatted[8:].lstrip() if len(formatted) > 8 else ""
                self.window.print(" ")
                self.window.print(f"{raw_text:<8} ")
                self._print_asm(asm_text)
            else:
                self.window.print(line)
            self.window.clear_to_eol()
            self.window.newline()
        self.window.clear_to_bottom()

    def _print_asm(self, asm_text: str):
        if not asm_text:
            return
        parts = asm_text.split(None, 1)
        mnemonic = parts[0].upper()
        operand = parts[1] if len(parts) > 1 else ""
        self.window.print(mnemonic, attr=Color.MNEMONIC.attr())
        if not operand:
            return
        self.window.print(" ")
        if mnemonic not in FLOW_MNEMONICS:
            self.window.print(operand)
            return
        span = _find_hex_addr_span(operand)
        if span is None:
            self.window.print(operand)
            return
        start, end = span
        self.window.print(operand[:start])
        self.window.print(operand[start:end], attr=Color.ADDRESS.attr())
        self.window.print(operand[end:])


class DisassemblyInputHandler(InputComponent):
    def __init__(self, screen, disasm_window, input_manager, address_widget):
        self._screen = screen
        self._disasm_window = disasm_window
        self._input_manager = input_manager
        self._address_widget = address_widget

    def handle_input(self, ch):
        if state.input_focus:
            return False
        if ch != ord("/"):
            return False
        if not self._disasm_window.visible:
            return False
        if self._screen.focused is not self._disasm_window:
            return False
        self._input_manager.open(
            self._address_widget,
            f"{state.disassembly_addr & 0xFFFF:04X}",
        )
        return True


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
