import curses

from .app import VisualRpcComponent
from .appstate import state
from .disasm import DecodedInstruction, disasm_6502_decoded
from .memory import parse_hex_u16
from .rpc import RpcException
from .ui import Color

ASM_COMMENT_COL = 18
FOLLOW_TAG_ID = "follow"


class DisassemblyViewer(VisualRpcComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_addr = None
        self._lines = []
        self._follow = True
        self._current_addr = None
        self._last_state_addr = None
        self._screen = None
        self._input_row = 0
        self._set_address = None
        self._set_input_focus = None
        self._set_input_target = None
        self._set_input_buffer = None
        self._input_snapshot = ""
        self._replace_on_next_input = False
        self._pending_nav = None
        self._last_snapshot = None
        self._render_cache = []
        self._rendered_rows = 0

    def bind_input(
        self,
        screen,
        input_row=0,
        set_address=None,
        set_input_focus=None,
        set_input_target=None,
        set_input_buffer=None,
    ):
        self._screen = screen
        self._input_row = int(input_row)
        self._set_address = set_address
        self._set_input_focus = set_input_focus
        self._set_input_target = set_input_target
        self._set_input_buffer = set_input_buffer

    def on_address_changed(self, addr: int):
        v = int(addr) & 0xFFFF
        self._set_follow(False)
        self._current_addr = v
        self._last_state_addr = v
        self._last_addr = None

    def enable_follow(self):
        self._set_follow(True)

    async def update(self):
        if not state.disassembly_enabled:
            return False
        if self.window._ih <= 0:
            return False

        pc = state.cpu.pc & 0xFFFF

        await self._apply_pending_nav()

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
        lines = await self._fetch_lines(addr)
        if lines is None:
            return False

        if self._follow:
            new_addr = await self._follow_addr(addr, pc, lines)
            if new_addr != addr:
                addr = new_addr & 0xFFFF
                lines = await self._fetch_lines(addr)
                if lines is None:
                    return False
            self._current_addr = addr

        self._lines = lines
        self._last_addr = addr
        snapshot = (pc, addr, tuple(lines))
        if self._last_snapshot == snapshot:
            return False
        self._last_snapshot = snapshot
        return True

    async def _fetch_lines(self, addr: int):
        read_len = max(3, self.window._ih * 3)
        try:
            data = await self.rpc.read_memory(addr, read_len)
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

    async def _follow_addr(self, addr: int, pc: int, lines):
        if pc < addr:
            return pc
        if not lines:
            return pc
        for ins in lines:
            if ins.addr == pc:
                return addr
        last_addr = lines[-1].addr
        if pc > last_addr:
            return await self._find_start_with_pc_on_bottom(pc)
        return pc

    async def _find_start_with_pc_on_bottom(self, pc: int):
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
                data = await self.rpc.read_memory(low, length)
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

    async def _find_end_start(self):
        target_row = max(0, self.window._ih - 1)
        lookbacks = (64, 128, 256, 512, 1024, 2048,
                     4096, 8192, 16384, 32768, 65535)
        for back in lookbacks:
            low = 0xFFFF - back
            if low < 0:
                low = 0
            length = (0xFFFF - low) + 3
            try:
                data = await self.rpc.read_memory(low, length)
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

    async def _find_prev_start(self, addr: int):
        if addr <= 0:
            return 0
        lookbacks = (32, 64, 128, 256, 512, 1024,
                     2048, 4096, 8192, 16384, 32768)
        for back in lookbacks:
            low = addr - back
            if low < 0:
                low = 0
            length = (addr - low) + 3
            try:
                data = await self.rpc.read_memory(low, length)
            except RpcException:
                return addr
            decoded = disasm_6502_decoded(low, data)
            prev = [a for a in self._linear_addrs(decoded) if a < addr]
            if prev:
                return prev[-1]
            if low == 0:
                return 0
        return addr

    async def _find_prev_start_n(self, addr: int, steps: int):
        if addr <= 0:
            return 0
        if steps <= 0:
            return addr
        if steps == 1:
            return await self._find_prev_start(addr)

        lookbacks = (
            steps * 3 + 16,
            steps * 6 + 32,
            steps * 12 + 64,
            steps * 24 + 128,
            1024,
            2048,
            4096,
            8192,
            16384,
            32768,
            65535,
        )
        for back in lookbacks:
            low = addr - back
            if low < 0:
                low = 0
            length = (addr - low) + 3
            try:
                data = await self.rpc.read_memory(low, length)
            except RpcException:
                return addr
            decoded = disasm_6502_decoded(low, data)
            prev = [a for a in self._linear_addrs(decoded) if a < addr]
            if not prev:
                if low == 0:
                    return 0
                continue
            if len(prev) >= steps:
                return prev[-steps]
            if low == 0:
                return prev[0]
        return addr

    async def _clamp_to_end_page(self, addr: int):
        end_start = await self._find_end_start()
        if addr > end_start:
            return end_start
        return addr

    async def _move_down_steps(self, steps: int):
        if steps <= 0:
            return
        self._follow = False
        if self._current_addr is None:
            self._current_addr = state.cpu.pc & 0xFFFF
        self._current_addr = await self._clamp_to_end_page(self._current_addr)
        lines = self._lines if self._last_addr == self._current_addr else None
        if not lines:
            lines = await self._fetch_lines(self._current_addr)
        if not lines:
            return
        idx = min(steps, len(lines) - 1)
        if idx <= 0:
            self._manual_set_addr(self._current_addr)
            return
        self._manual_set_addr(await self._clamp_to_end_page(lines[idx].addr))

    async def _move_up_steps(self, steps: int):
        if steps <= 0:
            return
        if self._current_addr is None:
            self._current_addr = state.cpu.pc & 0xFFFF
        addr = self._current_addr
        addr = await self._find_prev_start_n(addr, steps)
        self._manual_set_addr(addr)

    def _queue_nav(self, action: str, steps: int = 0):
        self._pending_nav = (action, int(steps))

    async def _apply_pending_nav(self):
        if self._pending_nav is None:
            return
        action, steps = self._pending_nav
        self._pending_nav = None
        if action == "home":
            self._manual_set_addr(0x0000)
            return
        if action == "end":
            self._manual_set_addr(await self._find_end_start())
            return
        if action == "down":
            await self._move_down_steps(steps)
            return
        if action == "up":
            await self._move_up_steps(steps)
            return

    def render(self, force_redraw=False):
        pc = state.cpu.pc & 0xFFFF
        ih = self.window._ih
        if ih <= 0:
            return
        if len(self._render_cache) != ih:
            self._render_cache = [None] * ih
            force_redraw = True
        rows = self._lines[: self.window._ih]
        for row_idx, ins in enumerate(rows):
            same_row_as_input = row_idx == self._input_row
            suppress = state.input_focus and same_row_as_input
            rev_attr = curses.A_REVERSE if (
                ins.addr == pc and not suppress) else 0
            input_text = (
                state.input_buffer[-4:].upper().rjust(4, "0")
                if state.input_focus and same_row_as_input
                else ""
            )
            row_sig = (ins, rev_attr, input_text)
            if not force_redraw and self._render_cache[row_idx] == row_sig:
                continue
            self.window.cursor = (0, row_idx)
            self.window.print(f"{ins.addr:04X}:",
                              attr=Color.ADDRESS.attr() | rev_attr)
            self.window.print(" ", attr=rev_attr)
            self.window.print(f"{ins.raw_text:<8} ", attr=rev_attr)
            self._print_asm(ins, rev_attr)
            self.window.fill_to_eol(attr=rev_attr)
            if input_text:
                attr = Color.ADDRESS.attr() | curses.A_REVERSE
                self.window.cursor = (0, self._input_row)
                self.window.print(input_text, attr=attr)
                self.window.print("  ", attr=attr)
            self._render_cache[row_idx] = row_sig
        next_row = len(rows)
        if next_row < ih and (force_redraw or self._rendered_rows != next_row):
            self.window.cursor = (0, next_row)
            self.window.clear_to_bottom()
        for idx in range(next_row, ih):
            self._render_cache[idx] = None
        self._rendered_rows = next_row

    def handle_input(self, ch):
        if state.input_focus:
            if state.input_target != "disassembly":
                return False
            return self._handle_address_input(ch)
        if not self.window.visible:
            return False
        if self._screen is None or self._screen.focused is not self.window:
            return False

        lower_ch = ch
        if ord("A") <= ch <= ord("Z"):
            lower_ch = ch + 32
        if ch == ord(" ") or lower_ch == ord("f"):
            self._set_follow(not self._follow)
            return True

        if ch in (curses.KEY_HOME, 262):
            self._queue_nav("home")
            return True

        if ch in (curses.KEY_END, 360):
            self._queue_nav("end")
            return True

        if ch == curses.KEY_DOWN:
            self._queue_nav("down", 1)
            return True

        if ch == curses.KEY_UP:
            self._queue_nav("up", 1)
            return True

        if ch in (curses.KEY_NPAGE, 338):
            self._queue_nav("down", max(1, self.window._ih - 1))
            return True

        if ch in (curses.KEY_PPAGE, 339):
            self._queue_nav("up", max(1, self.window._ih - 1))
            return True

        if ch != ord("/"):
            return False

        if self._current_addr is None:
            addr = state.cpu.pc & 0xFFFF
        else:
            addr = self._current_addr & 0xFFFF

        self._input_snapshot = f"{addr:04X}"
        self._replace_on_next_input = True
        if self._set_input_buffer is not None:
            self._set_input_buffer(self._input_snapshot)
        if self._set_input_target is not None:
            self._set_input_target("disassembly")
        if self._set_input_focus is not None:
            self._set_input_focus(True)
        try:
            curses.curs_set(1)
        except curses.error:
            pass
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
            self.window.print(
                " " * (ASM_COMMENT_COL - core_len), attr=rev_attr)
        self.window.print(" ", attr=rev_attr)
        self.window.print(ins.comment, attr=Color.COMMENT.attr() | rev_attr)

    def _close_address_input(self):
        self._replace_on_next_input = False
        if self._set_input_focus is not None:
            self._set_input_focus(False)
        if self._set_input_target is not None:
            self._set_input_target(None)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _update_address_input(self, text: str):
        if self._set_input_buffer is not None:
            self._set_input_buffer(text)
        if text:
            self._manual_set_addr(parse_hex_u16(text))

    def _handle_address_input(self, ch):
        if ch == 27:
            self._update_address_input(self._input_snapshot)
            self._close_address_input()
            return True
        if ch in (10, 13, curses.KEY_ENTER):
            text = state.input_buffer[-4:].upper()
            if text:
                self._manual_set_addr(parse_hex_u16(text))
            self._close_address_input()
            return True
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self._replace_on_next_input = False
            text = state.input_buffer[:-1]
            self._update_address_input(text)
            return True
        if ch < 0 or ch > 255:
            return True
        char = chr(ch).upper()
        if not (("0" <= char <= "9") or ("A" <= char <= "F")):
            return True
        text = state.input_buffer
        if self._replace_on_next_input:
            text = ""
            self._replace_on_next_input = False
        if len(text) >= 4:
            return True
        self._update_address_input(text + char)
        return True
