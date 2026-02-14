import curses

from ..actions import Actions
from ..app import VisualRpcComponent
from ..atari.disasm import FLOW_MNEMONICS, assemble_6502_one, disasm_6502_decoded
from ..atari.memory import parse_hex_u16
from ..rpc import RpcException
from ..ui import Color, GridWidget
from .appstate import state

FOLLOW_TAG_ID = "follow"


class DisassemblyViewer(VisualRpcComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grid = GridWidget(self.window, col_gap=1)
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
        self.grid.set_editable_columns_range(4, 6)
        self.grid.on_cell_input_change = self._on_grid_edit_change
        self._last_addr = None
        self._lines = []
        self._follow = True
        self._current_addr = None
        self._last_state_addr = None
        self._input_row = 0
        self._input_snapshot = ""
        self._input_buffer = ""
        self._input_mode = None
        self._replace_on_next_input = False
        self._pending_nav = None
        self._pending_write = None
        self._last_snapshot = None
        self._selected_addr = None
        self._selected_row_hint = None
        self._edit_addr = None
        self._edit_snapshot = ""
        self._edit_bytes = None

    def enable_follow(self):
        self._set_follow(True)

    def _dispatch(self, action: Actions, value=None):
        self.app.dispatch_action(action, value)

    async def update(self):
        if not state.disassembly_enabled:
            return False
        if self.window._ih <= 0:
            return False

        pc = state.cpu.pc & 0xFFFF

        await self._apply_pending_write()
        await self._apply_pending_nav()

        if self._current_addr is None:
            if state.disassembly_addr is None:
                self._current_addr = state.cpu.pc & 0xFFFF
            else:
                self._current_addr = state.disassembly_addr & 0xFFFF
                self._last_state_addr = self._current_addr
            self._selected_addr = self._current_addr
            self._selected_row_hint = 0
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
            self._selected_addr = None
            self._selected_row_hint = None

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
        return self._linear_instructions(decoded)

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
        ih = max(1, self.window._ih)
        for idx, ins in enumerate(lines):
            if ins.addr == pc:
                if idx < ih:
                    return addr
                start_idx = idx - (ih - 1)
                if start_idx < 0:
                    start_idx = 0
                return int(lines[start_idx].addr) & 0xFFFF
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
        lookbacks = (64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65535)
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

    def _manual_set_addr(self, addr: int, reset_selection: bool = True):
        v = addr & 0xFFFF
        self._set_follow(False)
        self._current_addr = v
        if reset_selection:
            self._selected_addr = v
            self._selected_row_hint = 0
        self._last_state_addr = v
        self._last_addr = None
        self._dispatch(Actions.SET_DISASSEMBLY_ADDR, v)

    async def _find_prev_start(self, addr: int):
        if addr <= 0:
            return 0
        lookbacks = (32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768)
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
            self._manual_set_addr(self._current_addr, reset_selection=False)
            return
        self._manual_set_addr(
            await self._clamp_to_end_page(lines[idx].addr),
            reset_selection=False,
        )

    async def _move_up_steps(self, steps: int):
        if steps <= 0:
            return
        if self._current_addr is None:
            self._current_addr = state.cpu.pc & 0xFFFF
        addr = self._current_addr
        addr = await self._find_prev_start_n(addr, steps)
        self._manual_set_addr(addr, reset_selection=False)

    def _queue_nav(self, action: str, steps: int = 0):
        self._pending_nav = (action, int(steps))

    async def _apply_pending_nav(self):
        if self._pending_nav is None:
            return
        action, steps = self._pending_nav
        self._pending_nav = None
        if action == "home":
            self._manual_set_addr(0x0000, reset_selection=False)
            return
        if action == "end":
            self._manual_set_addr(await self._find_end_start(), reset_selection=False)
            return
        if action == "down":
            await self._move_down_steps(steps)
            return
        if action == "up":
            await self._move_up_steps(steps)
            return

    async def _apply_pending_write(self):
        if self._pending_write is None:
            return
        addr, payload = self._pending_write
        self._pending_write = None
        try:
            await self.rpc.write_memory(addr & 0xFFFF, bytes(payload))
        except RpcException:
            return
        self._last_addr = None
        self._last_snapshot = None

    def render(self, force_redraw=False):
        pc = state.cpu.pc & 0xFFFF
        ih = self.window._ih
        if ih <= 0:
            return
        rows = []
        active_row = None
        for row_idx, ins in enumerate(self._lines):
            same_row_as_input = row_idx == self._input_row
            suppress = self._input_mode == "addr" and same_row_as_input
            if active_row is None and ins.addr == pc and not suppress:
                active_row = row_idx
            op1, op2, op3 = self._opcode_cells(ins.raw)
            rows.append(
                (
                    f"{int(ins.addr) & 0xFFFF:04X}:",
                    op1,
                    op2,
                    op3,
                    ins.mnemonic,
                    ins.operand,
                    ins.comment,
                )
            )
        self.grid.set_data(rows)
        selected_row = None
        if self._follow:
            if active_row is not None:
                selected_row = active_row
            elif rows:
                selected_row = 0
        else:
            if self._selected_addr is not None:
                selected_row = self._find_row_by_addr(self._selected_addr)
            if selected_row is None and self._selected_row_hint is not None and rows:
                vis_count = min(len(rows), ih)
                selected_row = max(0, min(int(self._selected_row_hint), vis_count - 1))
            if selected_row is None and rows:
                selected_row = 0
        if selected_row is not None and rows:
            vis_count = min(len(rows), ih)
            selected_row = max(0, min(int(selected_row), vis_count - 1))
            self._selected_row_hint = selected_row
            self._selected_addr = int(self._lines[selected_row].addr) & 0xFFFF
        else:
            self._selected_row_hint = None
            self._selected_addr = None
        self.grid.set_selected_row(selected_row)
        self.grid.set_highlighted_row(active_row)
        if self._lines:
            start_addr = int(self._lines[0].addr) & 0xFFFF
            anchor_addr = start_addr
            if active_row is not None and 0 <= active_row < len(self._lines):
                anchor_addr = int(self._lines[active_row].addr) & 0xFFFF
            end_addr = start_addr + 1
            for ins in self._lines[:ih]:
                size = int(ins.size)
                if size < 1:
                    size = 1
                cand = int(ins.addr) + size
                if cand > end_addr:
                    end_addr = cand
            if end_addr > 0x10000:
                end_addr = 0x10000
            page = max(1, end_addr - start_addr)
            self.grid.set_virtual_scroll(0x10000, anchor_addr, page)
        else:
            offset = (
                int(self._current_addr) & 0xFFFF
                if self._current_addr is not None
                else 0
            )
            self.grid.set_virtual_scroll(0x10000, offset, 1)
        self.grid.set_offset(0)
        if self._input_mode == "edit":
            row = self._find_row_by_addr(self._edit_addr)
            if row is not None and self.grid.editing_value != self._input_buffer:
                self.grid.begin_edit(row, self._input_buffer)
        self.grid.render()
        if self._input_mode is None:
            return
        if self._input_mode == "addr" and self._input_row < ih:
            input_text = self._input_buffer[-4:].upper().rjust(4, "0")
            attr = Color.ADDRESS.attr() | curses.A_REVERSE
            self.window.cursor = (0, self._input_row)
            self.window.print(input_text, attr=attr)
            self.window.print("  ", attr=attr)

    def _find_row_by_addr(self, addr: int | None) -> int | None:
        if addr is None:
            return None
        target = addr & 0xFFFF
        for idx, ins in enumerate(self._lines):
            if (int(ins.addr) & 0xFFFF) == target:
                return idx
        return None

    def _current_selected_row(self) -> int | None:
        vis_count = min(len(self._lines), self.window._ih)
        if vis_count <= 0:
            return None
        row = self._find_row_by_addr(self._selected_addr)
        if row is not None:
            return max(0, min(int(row), vis_count - 1))
        if self._selected_row_hint is not None:
            return max(0, min(int(self._selected_row_hint), vis_count - 1))
        cur = self.grid.selected_row
        if cur is None:
            return 0
        return max(0, min(int(cur), vis_count - 1))

    def _move_selected_rows(self, delta: int) -> bool:
        vis_count = min(len(self._lines), self.window._ih)
        if vis_count <= 0:
            self._selected_addr = None
            self._selected_row_hint = None
            return False
        cur = self._current_selected_row()
        if cur is None:
            cur = 0
        cur = max(0, min(int(cur), vis_count - 1))
        nxt = max(0, min(cur + int(delta), vis_count - 1))
        if nxt != cur:
            self._selected_row_hint = nxt
            self._selected_addr = int(self._lines[nxt].addr) & 0xFFFF
            self.grid.set_selected_row(nxt)
            return True
        self._selected_row_hint = cur
        self._selected_addr = None
        return False

    def _assemble_edit_buffer(self, text: str):
        if self._edit_addr is None:
            return None
        stmt = str(text).strip()
        if not stmt:
            return None
        try:
            return assemble_6502_one(self._edit_addr, stmt.upper())
        except Exception:
            return None

    def _update_edit_buffer(self, text: str):
        self._input_buffer = str(text)
        self._edit_bytes = self._assemble_edit_buffer(self._input_buffer)

    def _on_grid_edit_change(self, _x: int, y: int, value):
        if self._input_mode != "edit":
            return
        row = self._find_row_by_addr(self._edit_addr)
        if row is None:
            row = self._current_selected_row()
        if row is None or int(y) != int(row):
            return
        self._update_edit_buffer(str(value))

    def _open_edit_input(self) -> bool:
        row = self._current_selected_row()
        if row is None or row < 0 or row >= len(self._lines):
            return False
        ins = self._lines[row]
        text = ins.mnemonic if not ins.operand else f"{ins.mnemonic} {ins.operand}"
        self._set_follow(False)
        self._selected_row_hint = row
        self._selected_addr = int(ins.addr) & 0xFFFF
        self._edit_addr = int(ins.addr) & 0xFFFF
        self._edit_snapshot = text
        self._input_mode = "edit"
        self._replace_on_next_input = False
        self._update_edit_buffer(text)
        self.grid.begin_edit(row, text)
        self._dispatch(Actions.SET_INPUT_FOCUS, self._handle_focused_input)
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        return True

    def handle_input(self, ch):
        if not self.window.visible:
            return False

        lower_ch = ch
        if ord("A") <= ch <= ord("Z"):
            lower_ch = ch + 32
        if ch == ord(" ") or lower_ch == ord("f"):
            self._set_follow(not self._follow)
            return True

        if ch in (curses.KEY_HOME, 262):
            self._selected_row_hint = 0
            self._selected_addr = None
            self._queue_nav("home")
            return True

        if ch in (curses.KEY_END, 360):
            self._selected_row_hint = max(0, self.window._ih - 1)
            self._selected_addr = None
            self._queue_nav("end")
            return True

        if ch == curses.KEY_DOWN:
            self._set_follow(False)
            if not self._move_selected_rows(1):
                self._queue_nav("down", 1)
            return True

        if ch == curses.KEY_UP:
            self._set_follow(False)
            if not self._move_selected_rows(-1):
                self._queue_nav("up", 1)
            return True

        if ch in (curses.KEY_NPAGE, 338):
            self._set_follow(False)
            step = max(1, self.window._ih - 1)
            if not self._move_selected_rows(step):
                self._queue_nav("down", step)
            return True

        if ch in (curses.KEY_PPAGE, 339):
            self._set_follow(False)
            step = max(1, self.window._ih - 1)
            if not self._move_selected_rows(-step):
                self._queue_nav("up", step)
            return True

        if ch in (10, 13, curses.KEY_ENTER):
            return self._open_edit_input()

        if ch != ord("/"):
            return False

        if self._current_addr is None:
            addr = state.cpu.pc & 0xFFFF
        else:
            addr = self._current_addr & 0xFFFF

        self._input_snapshot = f"{addr:04X}"
        self._input_buffer = self._input_snapshot
        self._replace_on_next_input = True
        self._input_mode = "addr"
        self._dispatch(Actions.SET_INPUT_FOCUS, self._handle_focused_input)
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        return True

    def _set_follow(self, enabled: bool):
        self._follow = enabled
        self.window.set_tag_active(FOLLOW_TAG_ID, self._follow)

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

    def _close_disassembly_input(self):
        self._replace_on_next_input = False
        self._input_mode = None
        self._edit_addr = None
        self._edit_snapshot = ""
        self._edit_bytes = None
        self.grid.end_edit()
        self._dispatch(Actions.SET_INPUT_FOCUS, None)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _update_address_input(self, text: str):
        self._input_buffer = str(text)[-4:].upper()
        if self._input_buffer:
            self._manual_set_addr(parse_hex_u16(self._input_buffer))

    def _handle_focused_input(self, ch):
        if self._input_mode == "edit":
            return self._handle_edit_input(ch)
        if self._input_mode == "addr":
            return self._handle_address_input(ch)
        return False

    def _handle_address_input(self, ch):
        if ch == 27:
            self._update_address_input(self._input_snapshot)
            self._close_disassembly_input()
            return True
        if ch in (10, 13, curses.KEY_ENTER):
            text = self._input_buffer[-4:].upper()
            if text:
                self._manual_set_addr(parse_hex_u16(text))
            self._close_disassembly_input()
            return True
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self._replace_on_next_input = False
            text = self._input_buffer[:-1]
            self._update_address_input(text)
            return True
        if ch < 0 or ch > 255:
            return True
        char = chr(ch).upper()
        if not (("0" <= char <= "9") or ("A" <= char <= "F")):
            return True
        text = self._input_buffer
        if self._replace_on_next_input:
            text = ""
            self._replace_on_next_input = False
        if len(text) >= 4:
            return True
        self._update_address_input(text + char)
        return True

    def _handle_edit_input(self, ch):
        if ch == 27:
            self._input_buffer = self._edit_snapshot
            self._close_disassembly_input()
            return True
        if ch in (10, 13, curses.KEY_ENTER):
            if self._edit_addr is None or self._edit_bytes is None:
                return True
            self._pending_write = (self._edit_addr, bytes(self._edit_bytes))
            self._selected_addr = int(self._edit_addr) & 0xFFFF
            self._selected_row_hint = None
            self._close_disassembly_input()
            return True
        self.grid.handle_input(ch)
        return True
