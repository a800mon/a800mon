import curses

from .app import VisualRpcComponent
from .appstate import state
from .datastructures import WatcherEntry
from .inputwidget import InputWidget
from .memorymap import find_symbol_or_addr, lookup_symbol
from .rpc import RpcException
from .actions import Actions
from .ui import Color, GridWidget


class WatchersViewer(VisualRpcComponent):
    def __init__(self, rpc, window):
        super().__init__(rpc, window)
        self.grid = GridWidget(window, col_gap=0)
        self.grid.add_column("addr", width=0, attr=Color.ADDRESS.attr())
        self.grid.add_column("value", width=0, attr=Color.TEXT.attr())
        self.grid.add_column("next_addr", width=0, attr=Color.ADDRESS.attr())
        self.grid.add_column("next_value", width=0, attr=Color.TEXT.attr())
        self.grid.add_column("ascii", width=0, attr=Color.TEXT.attr())
        self.grid.add_column("comment", width=0, attr=Color.COMMENT.attr())
        self._rows = []
        self._input_snapshot = ""
        self._input_mode = None
        self._pending_addr = None
        self._pending_row = None
        self._selected_row_offset = 0
        self._last_snapshot = None
        self._search_input = InputWidget(
            self.window,
            max_length=8,
            on_change=self._on_search_change,
        )
        self.window.on_focus = self.clear_selection

    def clear_selection(self):
        self.grid.set_selected_row(None)

    async def update(self):
        ranges = [(row.addr & 0xFFFF, 2) for row in self._rows]
        if self._pending_addr is not None:
            ranges.append((self._pending_addr, 2))

        values = []
        if ranges:
            try:
                data = await self.rpc.read_memory_multiple(ranges)
                need = len(ranges) * 2
                if len(data) < need:
                    raise RpcException("READ_MEMV payload too short")
                values = [
                    (data[i * 2], data[i * 2 + 1]) for i in range(len(ranges))
                ]
            except RpcException:
                values = []
                try:
                    for addr, _ln in ranges:
                        b = await self.rpc.read_memory(addr, 2)
                        v0 = b[0] if len(b) >= 1 else 0
                        v1 = b[1] if len(b) >= 2 else 0
                        values.append((v0, v1))
                except RpcException:
                    return False

        watchers = []
        for idx, row in enumerate(self._rows):
            addr = row.addr & 0xFFFF
            if idx < len(values):
                value, next_value = values[idx]
            else:
                value, next_value = row.value, row.next_value
            comment = lookup_symbol(addr) or ""
            watchers.append(
                WatcherEntry(
                    addr=addr,
                    value=value,
                    next_value=next_value,
                    comment=comment,
                )
            )

        pending = None
        if self._pending_addr is not None:
            value_idx = len(watchers)
            if value_idx < len(values):
                value, next_value = values[value_idx]
            else:
                value, next_value = 0, 0
            pending = WatcherEntry(
                addr=self._pending_addr,
                value=value,
                next_value=next_value,
                comment=lookup_symbol(self._pending_addr) or "",
            )
        self._pending_row = pending
        self._clamp_selected(len(watchers))

        snapshot = (
            tuple(watchers),
            pending,
            self._selected_index(),
            self._search_input.buffer,
            state.use_atascii,
            self._input_mode,
        )
        if snapshot == self._last_snapshot:
            return False
        self._last_snapshot = snapshot
        if not watchers == self._rows:
            self._rows = watchers
        return True

    def render(self, force_redraw=False):
        self._render_grid()

    def _render_grid(self):
        ih = self.window._ih
        if ih <= 0:
            return
        input_active = self._input_mode == "search"
        rows = []
        row_base = 0
        if input_active:
            row_base = 1
            rows.append(("",))

        pending_offset = 0
        if self._pending_row is not None:
            pending_offset = 1
            rows.append(self._row_cells(self._pending_row))
        for row in self._rows:
            rows.append(self._row_cells(row))

        selected = self._selected_index()
        self._selected_row_offset = row_base + pending_offset
        if selected is None:
            self.grid.set_selected_row(None)
        else:
            self.grid.set_selected_row(selected + self._selected_row_offset)
        self.grid.set_data(rows)
        self.grid.render()

        if input_active:
            self.window.cursor = (0, 0)
            text = self._search_input.buffer[:8]
            self.window.print(
                text.ljust(8), attr=Color.TEXT.attr() | curses.A_REVERSE
            )
            self.window.clear_to_eol()

    def handle_input(self, ch):
        if self.app.screen.focused is not self.window:
            return False

        if ch == ord("/"):
            self._open_search_input("")
            return True

        if self.grid.handle_input(ch):
            return True

        if ch in (curses.KEY_DC, 330):
            self._delete_selected()
            return True

        return False

    def _close_input(self):
        self._input_mode = None
        self._search_input.deactivate()
        self.app.dispatch_action(Actions.SET_INPUT_FOCUS, None)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _open_search_input(self, initial: str):
        self._input_mode = "search"
        self._input_snapshot = str(initial)
        self._pending_addr = None
        self._pending_row = None
        self._search_input.activate(self._input_snapshot)
        self.app.dispatch_action(Actions.SET_INPUT_FOCUS, self._handle_search_input)
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def _update_search_buffer(self, text: str):
        self._search_input.set_buffer(text)

    def _handle_search_input(self, ch):
        if ch == 27:
            self._update_search_buffer(self._input_snapshot)
            self._pending_addr = None
            self._pending_row = None
            self._close_input()
            return True

        if ch in (10, 13, curses.KEY_ENTER):
            if self._pending_addr is not None:
                self._commit_pending()
            else:
                self._pending_addr = None
                self._pending_row = None
            self._close_input()
            return True

        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self._search_input.backspace()
            return True

        if self._search_input.append_char(ch):
            return True
        return True

    def _on_search_change(self, query):
        addr = find_symbol_or_addr(query)
        if addr is None:
            self._pending_addr = None
            self._pending_row = None
            return
        self._pending_addr = addr & 0xFFFF

    def _commit_pending(self):
        if self._pending_addr is None:
            return
        addr = self._pending_addr & 0xFFFF
        rows = list(self._rows)
        for idx, row in enumerate(rows):
            if row.addr == addr:
                self._set_selected_index(idx)
                self._pending_addr = None
                self._pending_row = None
                return
        rows.insert(
            0,
            WatcherEntry(
                addr=addr,
                value=0,
                next_value=0,
                comment=lookup_symbol(addr) or "",
            ),
        )
        self._set_selected_index(None)
        self._rows = rows
        self._pending_addr = None
        self._pending_row = None

    def _delete_selected(self):
        idx = self._selected_index()
        rows = list(self._rows)
        if idx is None or idx < 0 or idx >= len(rows):
            return
        rows.pop(idx)
        self._rows = rows
        if not rows:
            self._set_selected_index(None)
        elif idx >= len(rows):
            self._set_selected_index(len(rows) - 1)
        else:
            self._set_selected_index(idx)

    def _clamp_selected(self, row_count: int):
        if row_count <= 0:
            self._set_selected_index(None)
            return
        cur = self._selected_index()
        if cur is None:
            return
        if cur < 0:
            self._set_selected_index(0)
            return
        if cur >= row_count:
            self._set_selected_index(row_count - 1)

    def _selected_index(self):
        idx = self.grid.selected_row
        if idx is None:
            return None
        idx = int(idx) - self._selected_row_offset
        if idx < 0:
            return None
        if idx >= len(self._rows):
            return None
        return idx

    def _set_selected_index(self, idx: int | None):
        if idx is None or len(self._rows) == 0:
            self.grid.set_selected_row(None)
            return
        value = max(0, min(int(idx), len(self._rows) - 1))
        self.grid.set_selected_row(value + self._selected_row_offset)

    def _row_cells(self, row: WatcherEntry):
        word = ((row.next_value & 0xFF) << 8) | (row.value & 0xFF)
        return (
            f"{row.addr:04X}:",
            f" {row.value:02X} ",
            f"{word:04X}",
            f" {row.value:3d} {row.value:08b} ",
            ";",
            row.comment,
        )
