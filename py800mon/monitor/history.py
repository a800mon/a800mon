import curses

from ..app import VisualRpcComponent
from ..atari.disasm import FLOW_MNEMONICS, DecodedInstruction, disasm_6502_one_decoded
from ..rpc import RpcException
from ..ui import Color, GridWidget
from .appstate import state


class HistoryViewer(VisualRpcComponent):
    def __init__(self, rpc, window, reverse_order=False):
        super().__init__(rpc, window)
        self.grid = GridWidget(window, col_gap=1)
        self.grid.add_column("address", width=5, attr=Color.ADDRESS.attr())
        self.grid.add_column("opcode1", width=2, attr=Color.TEXT.attr())
        self.grid.add_column("opcode2", width=2, attr=Color.TEXT.attr())
        self.grid.add_column("opcode3", width=2, attr=Color.TEXT.attr())
        self.grid.add_column("mnemonic", width=4, attr=Color.MNEMONIC.attr())
        self.grid.add_column(
            "argument",
            width=14,
            attr=Color.TEXT.attr(),
            attr_callback=self._argument_attr,
        )
        self.grid.add_column("comment", width=0, attr=Color.COMMENT.attr())
        self._reverse_order = reverse_order
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
        next_pc = state.cpu.pc & 0xFFFF
        next_bytes = self._next_opbytes if self._next_pc == next_pc else b""
        next_ins = self._format_disasm_cached(next_pc, next_bytes)

        rows = []
        selected = None
        if self._reverse_order:
            for entry in reversed(self._entries):
                ins = self._format_disasm_cached(entry.pc, entry.opbytes)
                op1, op2, op3 = self._opcode_cells(ins.raw)
                rows.append(
                    (
                        f"{entry.pc:04X}:",
                        op1,
                        op2,
                        op3,
                        ins.mnemonic,
                        ins.operand,
                        ins.comment,
                    )
                )
            selected = len(rows)
            op1, op2, op3 = self._opcode_cells(next_ins.raw)
            rows.append(
                (
                    f"{next_pc:04X}:",
                    op1,
                    op2,
                    op3,
                    next_ins.mnemonic,
                    next_ins.operand,
                    next_ins.comment,
                )
            )
        else:
            selected = 0
            op1, op2, op3 = self._opcode_cells(next_ins.raw)
            rows.append(
                (
                    f"{next_pc:04X}:",
                    op1,
                    op2,
                    op3,
                    next_ins.mnemonic,
                    next_ins.operand,
                    next_ins.comment,
                )
            )
            for entry in self._entries:
                ins = self._format_disasm_cached(entry.pc, entry.opbytes)
                op1, op2, op3 = self._opcode_cells(ins.raw)
                rows.append(
                    (
                        f"{entry.pc:04X}:",
                        op1,
                        op2,
                        op3,
                        ins.mnemonic,
                        ins.operand,
                        ins.comment,
                    )
                )

        self.grid.set_data(rows)
        if not rows:
            self.grid.set_selected_row(None)
        elif self._follow_live:
            self.grid.set_selected_row(selected)
        elif self.grid.selected_row is None:
            self.grid.set_selected_row(selected)
        self.grid.render()

    def handle_input(self, ch):
        consumed = self.grid.handle_input(ch)
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
                if ins:
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

    def _opcode_cells(self, raw: bytes):
        data = bytes(raw)
        return (
            f"{data[0]:02X}" if len(data) >= 1 else "",
            f"{data[1]:02X}" if len(data) >= 2 else "",
            f"{data[2]:02X}" if len(data) >= 3 else "",
        )

    def _argument_attr(self, _value, row):
        if len(row) <= 4:
            return Color.TEXT.attr()
        mnemonic = str(row[4]).strip().upper()
        if mnemonic in FLOW_MNEMONICS:
            return Color.ADDRESS.attr()
        return Color.TEXT.attr()
