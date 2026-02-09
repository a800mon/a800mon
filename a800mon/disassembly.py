import curses
import time

from .app import VisualRpcComponent
from .appstate import state
from .disasm import DecodedInstruction, disasm_6502_decoded
from .rpc import RpcException
from .ui import Color

ASM_COMMENT_COL = 18
FOLLOW_TAG_ID = "follow"


class DisassemblyViewer(VisualRpcComponent):
    def __init__(self, *args, **kwargs):
        self._update_interval = kwargs.pop("update_interval", 0.05)
        super().__init__(*args, **kwargs)
        self._last_update = 0.0
        self._last_addr = None
        self._lines = []
        self._follow = True
        self._current_addr = None
        self._last_state_addr = None
        self._screen = None
        self._input_manager = None
        self._address_widget = None
        self._input_row = 0
        self._set_address = None

    def bind_input(
        self,
        screen,
        input_manager,
        address_widget,
        input_row=0,
        set_address=None,
    ):
        self._screen = screen
        self._input_manager = input_manager
        self._address_widget = address_widget
        self._input_row = int(input_row)
        self._set_address = set_address

    def on_address_changed(self, addr: int):
        v = int(addr) & 0xFFFF
        self._set_follow(False)
        self._current_addr = v
        self._last_state_addr = v
        self._last_addr = None

    def update(self):
        if not state.disassembly_enabled:
            return
        if self.window._ih <= 0:
            return

        if self._current_addr is None:
            if state.disassembly_addr is None:
                self._current_addr = state.cpu.pc & 0xFFFF
            else:
                self._current_addr = state.disassembly_addr & 0xFFFF
                self._last_state_addr = self._current_addr
        elif (
            state.disassembly_addr is not None
            and (state.disassembly_addr & 0xFFFF) != self._last_state_addr
        ):
            self._current_addr = state.disassembly_addr & 0xFFFF
            self._last_state_addr = self._current_addr

        addr = self._current_addr & 0xFFFF
        lines = self._fetch_lines(addr)
        if lines is None:
            return

        pc = state.cpu.pc & 0xFFFF
        if self._follow:
            new_addr = self._follow_addr(addr, pc, lines)
            if new_addr != addr:
                addr = new_addr & 0xFFFF
                lines = self._fetch_lines(addr)
                if lines is None:
                    return
            self._current_addr = addr

        now = time.time()
        if (
            self._last_addr == addr
            and self._last_update
            and now - self._last_update < self._update_interval
        ):
            return

        self._lines = lines
        self._last_addr = addr
        self._last_update = now

    def _fetch_lines(self, addr: int):
        read_len = max(3, self.window._ih * 3)
        try:
            data = self.rpc.read_memory(addr, read_len)
        except RpcException:
            return None
        decoded = disasm_6502_decoded(addr, data)
        return self._linear_instructions(decoded)[: self.window._ih]

    def _linear_instructions(self, decoded):
        lines = []
        prev = None
        for ins in decoded:
            addr = ins.addr
            if prev is not None and addr < prev:
                break
            lines.append(ins)
            prev = addr
        return lines

    def _follow_addr(self, addr: int, pc: int, lines):
        if pc < addr:
            return pc
        if not lines:
            return pc
        for ins in lines:
            if ins.addr == pc:
                return addr
        last_addr = lines[-1].addr
        if pc > last_addr:
            return self._find_start_with_pc_on_bottom(pc)
        return pc

    def _find_start_with_pc_on_bottom(self, pc: int):
        target_row = max(0, self.window._ih - 1)
        if target_row == 0:
            return pc

        lookbacks = (
            target_row * 3 + 16,
            target_row * 6 + 32,
            target_row * 12 + 64,
            target_row * 24 + 128,
        )
        for back in lookbacks:
            low = pc - back
            if low < 0:
                low = 0
            length = (pc - low) + 3
            try:
                data = self.rpc.read_memory(low, length)
            except RpcException:
                return pc

            decoded = disasm_6502_decoded(low, data)
            addrs = [a for a in self._linear_addrs(decoded) if a <= pc]
            if not addrs:
                if low == 0:
                    return pc
                continue

            if addrs[-1] != pc:
                if low == 0:
                    return pc
                continue

            if len(addrs) > target_row:
                return addrs[-(target_row + 1)]
            if low == 0:
                return addrs[0]

        return pc

    def _linear_addrs(self, decoded):
        return [ins.addr for ins in self._linear_instructions(decoded)]

    def _find_end_start(self):
        target_row = max(0, self.window._ih - 1)
        lookbacks = (64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65535)
        for back in lookbacks:
            low = 0xFFFF - back
            if low < 0:
                low = 0
            length = (0xFFFF - low) + 3
            try:
                data = self.rpc.read_memory(low, length)
            except RpcException:
                return 0xFFFF
            decoded = disasm_6502_decoded(low, data)
            addrs = self._linear_addrs(decoded)
            if not addrs:
                if low == 0:
                    return 0
                continue
            if len(addrs) > target_row:
                return addrs[-(target_row + 1)]
            if low == 0:
                return addrs[0]
        return 0xFFFF

    def _manual_set_addr(self, addr: int):
        v = int(addr) & 0xFFFF
        self._set_follow(False)
        self._current_addr = v
        self._last_state_addr = v
        self._last_addr = None
        if self._set_address is not None:
            self._set_address(v)

    def _find_prev_start(self, addr: int):
        if addr <= 0:
            return 0
        lookbacks = (32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768)
        for back in lookbacks:
            low = addr - back
            if low < 0:
                low = 0
            length = (addr - low) + 3
            try:
                data = self.rpc.read_memory(low, length)
            except RpcException:
                return addr
            decoded = disasm_6502_decoded(low, data)
            prev = [a for a in self._linear_addrs(decoded) if a < addr]
            if prev:
                return prev[-1]
            if low == 0:
                return 0
        return addr

    def _clamp_to_end_page(self, addr: int):
        end_start = self._find_end_start()
        if addr > end_start:
            return end_start
        return addr

    def _move_down_steps(self, steps: int):
        if steps <= 0:
            return
        self._follow = False
        if self._current_addr is None:
            self._current_addr = state.cpu.pc & 0xFFFF
        self._current_addr = self._clamp_to_end_page(self._current_addr)
        lines = self._lines if self._last_addr == self._current_addr else None
        if not lines:
            lines = self._fetch_lines(self._current_addr)
        if not lines:
            return
        idx = min(steps, len(lines) - 1)
        if idx <= 0:
            self._manual_set_addr(self._current_addr)
            return
        self._manual_set_addr(self._clamp_to_end_page(lines[idx].addr))

    def _move_up_steps(self, steps: int):
        if steps <= 0:
            return
        if self._current_addr is None:
            self._current_addr = state.cpu.pc & 0xFFFF
        addr = self._current_addr
        for _ in range(steps):
            prev = self._find_prev_start(addr)
            if prev == addr:
                break
            addr = prev
            if addr == 0:
                break
        self._manual_set_addr(addr)

    def render(self, force_redraw=False):
        self.window.cursor = 0, 0
        pc = state.cpu.pc & 0xFFFF
        rows = self._lines[: self.window._ih]
        for row_idx, ins in enumerate(rows):
            self.window.cursor = (0, row_idx)
            same_row_as_input = row_idx == self._input_row
            suppress = state.input_focus and same_row_as_input
            rev_attr = curses.A_REVERSE if (ins.addr == pc and not suppress) else 0
            self.window.print(f"{ins.addr:04X}:", attr=Color.ADDRESS.attr() | rev_attr)
            self.window.print(" ", attr=rev_attr)
            self.window.print(f"{ins.raw_text:<8} ", attr=rev_attr)
            self._print_asm(ins, rev_attr)
            self.window.fill_to_eol(attr=rev_attr)
        next_row = len(rows)
        if next_row < self.window._ih:
            self.window.cursor = (0, next_row)
            self.window.clear_to_bottom()

    def handle_input(self, ch):
        if state.input_focus:
            return False
        if not self.window.visible:
            return False
        if self._screen is None or self._screen.focused is not self.window:
            return False

        if ch in (ord("f"), ord("F")):
            self._set_follow(not self._follow)
            return True

        if ch in (curses.KEY_HOME, 262):
            self._manual_set_addr(0x0000)
            return True

        if ch in (curses.KEY_END, 360):
            self._manual_set_addr(self._find_end_start())
            return True

        if ch == curses.KEY_DOWN:
            self._move_down_steps(1)
            return True

        if ch == curses.KEY_UP:
            self._move_up_steps(1)
            return True

        if ch in (curses.KEY_NPAGE, 338):
            self._move_down_steps(max(1, self.window._ih - 1))
            return True

        if ch in (curses.KEY_PPAGE, 339):
            self._move_up_steps(max(1, self.window._ih - 1))
            return True

        if ch != ord("/"):
            return False
        if self._input_manager is None or self._address_widget is None:
            return False

        if self._current_addr is None:
            addr = state.cpu.pc & 0xFFFF
        else:
            addr = self._current_addr & 0xFFFF

        self._input_manager.open(self._address_widget, f"{addr:04X}")
        return True

    def _set_follow(self, enabled: bool):
        self._follow = bool(enabled)
        self.window.set_tag_active(FOLLOW_TAG_ID, self._follow)

    def _print_asm(self, ins: DecodedInstruction, rev_attr: int = 0):
        if not ins.mnemonic:
            return
        core_len = len(ins.mnemonic)
        self.window.print(ins.mnemonic, attr=Color.MNEMONIC.attr() | rev_attr)
        if ins.operand:
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
