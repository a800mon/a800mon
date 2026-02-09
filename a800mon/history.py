import curses
import time

from .app import VisualRpcComponent
from .appstate import state
from .disasm import DecodedInstruction, disasm_6502_one_decoded
from .rpc import RpcException
from .ui import Color

ASM_COMMENT_COL = 18


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
        next_ins = self._format_disasm(next_pc, next_bytes)

        if self._reverse_order:
            rows = list(reversed(self._entries[: max(0, self.window._ih - 1)]))
            for entry in rows:
                row_ins = self._format_disasm(entry.pc, entry.opbytes)
                self._print_row(entry.pc, row_ins, 0)
                self._finish_row(inverse=False)
            self.window.cursor = (0, self.window._ih - 1)
            self._print_row(next_pc, next_ins, curses.A_REVERSE)
            self.window.fill_to_eol(attr=curses.A_REVERSE)
        else:
            # Synthetic first line: next instruction at current PC.
            self._print_row(next_pc, next_ins, curses.A_REVERSE)
            self._finish_row(inverse=True)

            if self.window._ih > 1:
                rows = self._entries[: self.window._ih - 1]
                for entry in rows:
                    row_ins = self._format_disasm(entry.pc, entry.opbytes)
                    self._print_row(entry.pc, row_ins, 0)
                    self._finish_row(inverse=False)

    def _format_disasm(self, pc: int, opbytes: bytes) -> DecodedInstruction:
        if self._can_disasm:
            try:
                ins = disasm_6502_one_decoded(pc, opbytes)
                if ins is not None:
                    return ins
            except RuntimeError:
                self._can_disasm = False
        raw_text = " ".join(f"{b:02X}" for b in opbytes)
        return DecodedInstruction(
            addr=pc & 0xFFFF,
            size=len(opbytes),
            raw=opbytes,
            raw_text=raw_text,
            mnemonic="",
            operand="",
            comment="",
            asm_text="",
            addressing="",
            flow_target=None,
            operand_addr_span=None,
        )

    def _print_asm(self, ins: DecodedInstruction, rev_attr: int = 0):
        if not ins.mnemonic:
            return
        core_len = len(ins.mnemonic)
        self.window.print(ins.mnemonic, attr=Color.MNEMONIC.attr() | rev_attr)
        if not ins.operand:
            pass
        else:
            self.window.print(" ", attr=rev_attr)
            core_len += 1 + len(ins.operand)
            if ins.flow_target is None or ins.operand_addr_span is None:
                self.window.print(ins.operand, attr=rev_attr)
            else:
                start, end = ins.operand_addr_span
                self.window.print(ins.operand[:start], attr=rev_attr)
                self.window.print(
                    ins.operand[start:end], attr=Color.ADDRESS.attr() | rev_attr
                )
                self.window.print(ins.operand[end:], attr=rev_attr)
        if not ins.comment:
            return
        if core_len < ASM_COMMENT_COL:
            self.window.print(" " * (ASM_COMMENT_COL - core_len), attr=rev_attr)
        self.window.print(" ", attr=rev_attr)
        self.window.print(ins.comment, attr=Color.COMMENT.attr() | rev_attr)

    def _print_row(self, pc: int, ins: DecodedInstruction, rev_attr: int, prefix: str = ""):
        if prefix:
            self.window.print(prefix, attr=rev_attr)
        self.window.print(f"{pc:04X}:", attr=Color.ADDRESS.attr() | rev_attr)
        self.window.print(" ", attr=rev_attr)
        self.window.print(f"{ins.raw_text:<8} ", attr=rev_attr)
        self._print_asm(ins, rev_attr)

    def _finish_row(self, inverse: bool):
        _, y_before = self.window.cursor
        if inverse:
            self.window.fill_to_eol(attr=curses.A_REVERSE)
        else:
            self.window.clear_to_eol()
        _, y_after = self.window.cursor
        if y_after == y_before:
            self.window.newline()
