import curses

from .app import VisualRpcComponent
from .appstate import state
from .datastructures import WatcherEntry
from .inputwidget import InputWidget
from .memorymap import find_symbol_or_addr, lookup_symbol
from .rpc import RpcException
from .actions import Actions
from .ui import Color, GridCell, GridWidget


class WatchersViewer(VisualRpcComponent):
    def __init__(self, rpc, window):
        super().__init__(rpc, window)
        self.grid = GridWidget(window, col_gap=0)
        self._screen = None
        self._dispatcher = None
        self._input_snapshot = ""
        self._input_mode = None
        self._pending_addr = None
        self._pending_row = None
        self._grid_selected_offset = 0
        self._last_snapshot = None
        self._search_input = InputWidget(
            self.window,
            max_length=8,
            on_change=self._on_search_change,
        )

    def bind_input(self, screen, dispatcher):
        self._screen = screen
        self._dispatcher = dispatcher
        self.window.on_focus = self.clear_selection

    def clear_selection(self):
        self.grid.set_grid_selected(None)

    async def update(self):
        ranges = [(row.addr & 0xFFFF, 2) for row in state.watchers]
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
        for idx, row in enumerate(state.watchers):
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
            state.input_focus,
            state.input_target,
            state.input_buffer,
            state.use_atascii,
            self._input_mode,
        )
        if snapshot == self._last_snapshot:
            return False
        self._last_snapshot = snapshot
        if watchers != state.watchers:
            self._dispatcher.update_watchers(watchers)
        return True

    def render(self, force_redraw=False):
        self._render_grid()

    def _render_grid(self):
        ih = self.window._ih
        if ih <= 0:
            return
        input_active = state.input_focus and state.input_target == "watchers"
        rows = []
        row_base = 0
        if input_active:
            row_base = 1
            rows.append((GridCell("", Color.TEXT.attr()),))

        pending_offset = 0
        if self._pending_row is not None:
            pending_offset = 1
            rows.append(self._row_cells(self._pending_row))
        for row in state.watchers:
            rows.append(self._row_cells(row))

        selected = self._selected_index()
        self._grid_selected_offset = row_base + pending_offset
        if selected is None:
            self.grid.set_grid_selected(None)
        else:
            self.grid.set_grid_selected(selected + self._grid_selected_offset)
        self.grid.set_grid_column_widths(())
        self.grid.set_grid_rows(rows)
        self.grid.render_grid()

        if input_active:
            self.window.cursor = (0, 0)
            text = state.input_buffer[:8]
            self.window.print(
                text.ljust(8), attr=Color.TEXT.attr() | curses.A_REVERSE
            )
            self.window.clear_to_eol()

    def handle_input(self, ch):
        if state.input_focus:
            if state.input_target != "watchers":
                return False
            return self._handle_search_input(ch)
        if self._screen is None or self._dispatcher is None:
            return False
        if self._screen.focused is not self.window:
            return False

        if ch == ord("/"):
            self._open_search_input("")
            return True

        if self.grid.handle_grid_navigation_input(ch):
            return True

        if ch in (curses.KEY_DC, 330):
            self._delete_selected()
            return True

        return False

    def _close_input(self):
        self._input_mode = None
        self._search_input.deactivate()
        self._dispatcher.dispatch(Actions.SET_INPUT_FOCUS, False)
        self._dispatcher.dispatch(Actions.SET_INPUT_TARGET, None)
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
        self._dispatcher.dispatch(Actions.SET_INPUT_BUFFER, self._search_input.buffer)
        self._dispatcher.dispatch(Actions.SET_INPUT_TARGET, "watchers")
        self._dispatcher.dispatch(Actions.SET_INPUT_FOCUS, True)
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def _update_search_buffer(self, text: str):
        self._search_input.set_buffer(text)
        self._dispatcher.dispatch(Actions.SET_INPUT_BUFFER, self._search_input.buffer)

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
            if self._search_input.backspace():
                self._dispatcher.dispatch(
                    Actions.SET_INPUT_BUFFER, self._search_input.buffer
                )
            return True

        if self._search_input.append_char(ch):
            self._dispatcher.dispatch(
                Actions.SET_INPUT_BUFFER, self._search_input.buffer
            )
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
        rows = list(state.watchers)
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
        self._dispatcher.update_watchers(rows)
        self._pending_addr = None
        self._pending_row = None

    def _delete_selected(self):
        idx = self._selected_index()
        rows = list(state.watchers)
        if idx is None or idx < 0 or idx >= len(rows):
            return
        rows.pop(idx)
        self._dispatcher.update_watchers(rows)
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
        idx = self.grid.grid_selected
        if idx is None:
            return None
        idx = int(idx) - self._grid_selected_offset
        if idx < 0:
            return None
        if idx >= len(state.watchers):
            return None
        return idx

    def _set_selected_index(self, idx: int | None):
        if idx is None or len(state.watchers) == 0:
            self.grid.set_grid_selected(None)
            return
        value = max(0, min(int(idx), len(state.watchers) - 1))
        self.grid.set_grid_selected(value + self._grid_selected_offset)

    def _row_cells(self, row: WatcherEntry):
        word = ((row.next_value & 0xFF) << 8) | (row.value & 0xFF)
        return (
            GridCell(f"{row.addr:04X}:", Color.ADDRESS.attr()),
            GridCell(f" {row.value:02X} ", Color.TEXT.attr()),
            GridCell(f"{word:04X}", Color.ADDRESS.attr()),
            GridCell(f" {row.value:3d} {row.value:08b} ", Color.TEXT.attr()),
            GridCell(";", Color.TEXT.attr()),
            GridCell(row.comment, Color.COMMENT.attr()),
        )
