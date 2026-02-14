import curses

from ..actions import Actions
from ..app import VisualRpcComponent
from ..datastructures import WatcherEntry
from ..atari.memorymap import find_symbol_or_addr, lookup_symbol
from ..rpc import RpcException
from ..ui import Color, GridWidget
from ..ui import InputWidget


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
        self._input_active = False
        self._pending_addr = None
        self._pending_row = None
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
                values = [(data[i * 2], data[i * 2 + 1]) for i in range(len(ranges))]
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

        snapshot = (
            tuple(watchers),
            pending,
            self.grid.selected_row,
            self._search_input.buffer,
            self._input_active,
        )
        if snapshot == self._last_snapshot:
            return False
        self._last_snapshot = snapshot
        if not watchers == self._rows:
            self._rows = watchers
        return True

    def render(self, force_redraw=False):
        ih = self.window._ih
        if ih <= 0:
            return
        overlay_rows = 0
        if self._input_active:
            overlay_rows += 1
        if self._pending_row:
            overlay_rows += 1

        self.grid.set_viewport(y=overlay_rows, height=max(0, ih - overlay_rows))
        rows = [self._row_cells(row) for row in self._rows]

        selected = self.grid.selected_row
        if selected is None:
            self.grid.set_selected_row(None)
        else:
            self.grid.set_selected_row(selected)
        self.grid.set_data(rows)
        self.grid.render()

        y = 0
        if self._input_active:
            self.window.cursor = (0, y)
            text = self._search_input.buffer[:8]
            self.window.print(text.ljust(8), attr=Color.TEXT.attr() | curses.A_REVERSE)
            self.window.clear_to_eol()
            y += 1
        if self._pending_row and y < ih:
            self._draw_pending_row(y)

    def handle_input(self, ch):
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
        self._clear_pending()
        self._input_active = False
        self._search_input.deactivate()
        self.app.dispatch_action(Actions.SET_INPUT_FOCUS, None)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _open_search_input(self, initial: str):
        self._input_active = True
        self._clear_pending()
        self._search_input.activate(str(initial))
        self.app.dispatch_action(Actions.SET_INPUT_FOCUS, self._handle_search_input)
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def _handle_search_input(self, ch):
        if ch == 27:
            self._close_input()
            return True

        if ch in (10, 13, curses.KEY_ENTER):
            if self._pending_addr is not None:
                self._commit_pending()
            self._close_input()
            return True

        if self._search_input.handle_key(ch):
            return True
        return True

    def _on_search_change(self, query):
        addr = find_symbol_or_addr(query)
        if addr is None:
            self._clear_pending()
            return
        self._pending_addr = addr & 0xFFFF

    def _commit_pending(self):
        if self._pending_addr is None:
            return
        addr = self._pending_addr & 0xFFFF
        rows = list(self._rows)
        for idx, row in enumerate(rows):
            if row.addr == addr:
                self.grid.set_selected_row(idx)
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
        self.grid.set_selected_row(None)
        self._rows = rows

    def _delete_selected(self):
        idx = self.grid.selected_row
        if idx is None:
            return
        self._rows.pop(idx)
        self.grid.set_selected_row(idx)

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

    def _draw_pending_row(self, y: int):
        cells = self._row_cells(self._pending_row)
        attrs = (
            Color.ADDRESS.attr(),
            Color.TEXT.attr(),
            Color.ADDRESS.attr(),
            Color.TEXT.attr(),
            Color.TEXT.attr(),
            Color.COMMENT.attr(),
        )
        self.window.cursor = (0, y)
        for idx, text in enumerate(cells):
            self.window.print(str(text), attr=attrs[idx])
        self.window.clear_to_eol()

    def _clear_pending(self):
        self._pending_addr = None
        self._pending_row = None
