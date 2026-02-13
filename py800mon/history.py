import curses

from .app import VisualRpcComponent
from .appstate import state
from .disasm import DecodedInstruction, disasm_6502_one_decoded
from .rpc import RpcException
from .ui import Color, GridCell

ASM_COMMENT_COL = 18


class HistoryViewer(VisualRpcComponent):
    def __init__(self, *args, **kwargs):
        self._reverse_order = bool(kwargs.pop("reverse_order", False))
        super().__init__(*args, **kwargs)
        self._entries = []
        self._can_disasm = True
        self._next_pc = None
        self._next_opbytes = b""
        self._last_snapshot = None
        self._decoded_cache = {}
        self._follow_live = True

    async def update(self):
        try:
            entries = await self.rpc.history()
            pc = state.cpu.pc & 0xFFFF
            next_opbytes = await self.rpc.read_memory(pc, 3)
            snapshot = (tuple(entries), pc, next_opbytes)
            if self._last_snapshot == snapshot:
                return False
            self._last_snapshot = snapshot
            self._entries = entries
            self._next_pc = pc
            self._next_opbytes = next_opbytes
            return True
        except RpcException:
            return False

    def render(self, force_redraw=False):
        self._render_grid()

    def _render_grid(self):
        next_pc = state.cpu.pc & 0xFFFF
        next_bytes = self._next_opbytes if self._next_pc == next_pc else b""
        next_ins = self._format_disasm_cached(next_pc, next_bytes)

        rows = []
        selected = None
        if self._reverse_order:
            for entry in reversed(self._entries):
                rows.append(self._row_cells(entry.pc, self._format_disasm_cached(entry.pc, entry.opbytes)))
            selected = len(rows)
            rows.append(self._row_cells(next_pc, next_ins))
        else:
            selected = 0
            rows.append(self._row_cells(next_pc, next_ins))
            for entry in self._entries:
                rows.append(self._row_cells(entry.pc, self._format_disasm_cached(entry.pc, entry.opbytes)))

        self.window.set_grid_column_widths(())
        self.window.set_grid_rows(rows)
        if not rows:
            self.window.set_grid_selected(None)
        elif self._follow_live:
            self.window.set_grid_selected(selected)
        elif self.window.grid_selected is None:
            self.window.set_grid_selected(selected)
        self.window.render_grid()

    def handle_input(self, ch):
        if state.input_focus:
            return False
        if self.window._screen is None or self.window._screen.focused is not self.window:
            return False
        consumed = self.window.handle_grid_navigation_input(ch)
        if not consumed:
            return False
        if self._reverse_order:
            self._follow_live = ch in (curses.KEY_END, 360)
        else:
            self._follow_live = ch in (curses.KEY_HOME, 262)
        return True

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

    def _format_disasm_cached(self, pc: int, opbytes: bytes) -> DecodedInstruction:
        key = (pc & 0xFFFF, bytes(opbytes))
        if key in self._decoded_cache:
            return self._decoded_cache[key]
        ins = self._format_disasm(pc, opbytes)
        self._decoded_cache[key] = ins
        if len(self._decoded_cache) > 2048:
            self._decoded_cache.clear()
        return ins

    def _row_cells(self, pc: int, ins: DecodedInstruction, prefix: str = ""):
        cells = []
        if prefix:
            cells.append(GridCell(prefix, Color.TEXT.attr()))
        cells.append(GridCell(f"{pc:04X}:", Color.ADDRESS.attr()))
        cells.append(GridCell(" ", Color.TEXT.attr()))
        cells.append(GridCell(f"{ins.raw_text:<8} ", Color.TEXT.attr()))
        cells.extend(self._asm_cells(ins))
        return tuple(cells)

    def _asm_cells(self, ins: DecodedInstruction):
        if not ins.mnemonic:
            return []
        cells = [GridCell(ins.mnemonic, Color.MNEMONIC.attr())]
        core_len = len(ins.mnemonic)
        if ins.operand:
            cells.append(GridCell(" ", Color.TEXT.attr()))
            core_len += 1 + len(ins.operand)
            if ins.flow_target is None or ins.operand_addr_span is None:
                cells.append(GridCell(ins.operand, Color.TEXT.attr()))
            else:
                start, end = ins.operand_addr_span
                if start > 0:
                    cells.append(GridCell(ins.operand[:start], Color.TEXT.attr()))
                cells.append(GridCell(ins.operand[start:end], Color.ADDRESS.attr()))
                if end < len(ins.operand):
                    cells.append(GridCell(ins.operand[end:], Color.TEXT.attr()))
        if not ins.comment:
            return cells
        if core_len < ASM_COMMENT_COL:
            cells.append(GridCell(" " * (ASM_COMMENT_COL - core_len), Color.TEXT.attr()))
        cells.append(GridCell(" ", Color.TEXT.attr()))
        cells.append(GridCell(ins.comment, Color.COMMENT.attr()))
        return cells
