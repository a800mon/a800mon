import dataclasses

from . import debug
from .app import VisualRpcComponent
from .appstate import state, store
from .atascii import atascii_to_curses, screen_to_atascii
from .datastructures import ScreenBuffer
from .displaylist import DMACTL_ADDR, DMACTL_HW_ADDR, DisplayListMemoryMapper
from .rpc import RpcException
from .ui import Color, GridCell, GridWidget


@dataclasses.dataclass(frozen=True, slots=True)
class ScreenBufferCell:
    addr: int  # adres w Twoim buforze (np. 0x3800 + offset)
    value: int  # bajt 0..255 (wartość "ekranowa" / ATASCII / to co trzymasz)
    x: int
    y: int

    def as_int(self) -> int:
        return self.value

    def as_ascii(self) -> str:
        # Minimalnie: klasyczne 7-bit ASCII (kontrola -> '.')
        v = self.value & 0x7F
        if 32 <= v <= 126:
            return chr(v)
        return "."

    def as_atascii(self) -> int:
        # Zwraca "surową" wartość ATASCII (jak trzymasz w buforze)
        return self.value & 0xFF

    def as_atascii_char(self) -> str:
        # Jeśli masz własne mapowanie ATASCII->Unicode, podepnij je tutaj.
        # Domyślnie: ASCII z maską 0x7F.
        return self.as_ascii()


class ScreenBufferInspector(VisualRpcComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grid = GridWidget(self.window, col_gap=0)
        self.grid.set_grid_selection_enabled(False)
        self._inspect = False
        self._cx = 0
        self._cy = 0
        self._dmactl = 0
        self._last_use_atascii = None
        self._screen = None

    def bind_input(self, screen):
        self._screen = screen

    @property
    def cols(self):
        return self.window.w

    @property
    def rows(self):
        return self.window.h

    def toggle_inspect(self) -> bool:
        self._inspect = not self._inspect
        return self._inspect

    def set_cursor(self, x: int, y: int) -> None:
        x = int(x)
        y = int(y)

        if self.cols <= 0 or self.rows <= 0:
            return

        # clamp
        if x < 0:
            x = 0
        elif x >= self.cols:
            x = self.cols - 1

        if y < 0:
            y = 0
        elif y >= self.rows:
            y = self.rows - 1

        self._cx = x
        self._cy = y

    def cursor_left(self, n: int = 1) -> None:
        self.set_cursor(self._cx - int(n), self._cy)

    def cursor_right(self, n: int = 1) -> None:
        self.set_cursor(self._cx + int(n), self._cy)

    def cursor_up(self, n: int = 1) -> None:
        self.set_cursor(self._cx, self._cy - int(n))

    def cursor_down(self, n: int = 1) -> None:
        self.set_cursor(self._cx, self._cy + int(n))

    def is_inspecting(self) -> bool:
        return self._inspect

    def handle_input(self, ch):
        if state.input_focus:
            return False
        if self._screen is None or not self._screen.focused == self.window:
            return False
        if ch in (ord(" "), ord("a"), ord("A")):
            store.set_use_atascii(not state.use_atascii)
            return True
        return self.grid.handle_grid_navigation_input(ch)

    @property
    def cursor(self) -> tuple[int, int]:
        return self._cx, self._cy

    @property
    def cell(self) -> ScreenBufferCell:
        val = self.window.get_char(self._cx, self._cy) & 0xFF
        return ScreenBufferCell(addr=0, value=val, x=self._cx, y=self._cy)

    def put_value(self, value: int) -> None:
        raise NotImplementedError

    def render(self, force_redraw=False) -> None:
        if self._last_use_atascii != state.use_atascii:
            self._last_use_atascii = state.use_atascii
            self.window.set_tag_active("atascii", state.use_atascii)
            self.window.set_tag_active("ascii", not state.use_atascii)

        segs = state.dlist.screen_segments(self._dmactl)
        active_seg = None
        if state.dlist_selected_region is not None and segs:
            if 0 <= state.dlist_selected_region < len(segs):
                active_seg = segs[state.dlist_selected_region]
        content_width = self.window._iw - 8
        if content_width < 0:
            content_width = 0
        rows_to_draw = []
        for row_info in state.screen_buffer.row_slices:
            parsed = _parse_row_info(row_info, state.screen_buffer.start_address)
            if not parsed:
                continue
            start_addr, length = parsed
            if active_seg is not None:
                start, end, _mode = active_seg
                if not (start <= start_addr < end):
                    continue
            if length <= 0:
                continue
            row = state.screen_buffer.get_range(start_addr, length)[:content_width]
            rows_to_draw.append((start_addr, row))
        draw_width = 0
        for _addr, row in rows_to_draw:
            if len(row) > draw_width:
                draw_width = len(row)
        if draw_width > content_width:
            draw_width = content_width

        rows = []
        for start_addr, row in rows_to_draw:
            row = row[:draw_width]
            left_pad = 0
            right_pad = 0
            if draw_width > len(row):
                left_pad = (draw_width - len(row)) // 2
                right_pad = draw_width - len(row) - left_pad
            cells = [GridCell(f"{start_addr:04X}: ", Color.ADDRESS.attr())]
            if left_pad > 0:
                cells.append(GridCell("·" * left_pad, Color.UNUSED.attr()))
            for text, attr in _render_runs(row, state.use_atascii):
                if text:
                    cells.append(GridCell(text, attr))
            if right_pad > 0:
                cells.append(GridCell("·" * right_pad, Color.UNUSED.attr()))
            rows.append(tuple(cells))

        self.grid.set_grid_column_widths(())
        self.grid.set_grid_rows(rows)
        self.grid.set_grid_selected(None)
        self.grid.render_grid()

    async def update(self):
        try:
            dmactl = await self.rpc.read_byte(DMACTL_ADDR)
            if (dmactl & 0x03) == 0:
                dmactl = await self.rpc.read_byte(DMACTL_HW_ADDR)
            mapper = DisplayListMemoryMapper(state.dlist, dmactl)
            fetch_ranges, row_slices = mapper.plan()
            segs = state.dlist.screen_segments(dmactl)
            if (
                state.dlist_selected_region is not None
                and 0 <= state.dlist_selected_region < len(segs)
            ):
                seg_start, seg_end, _mode = segs[state.dlist_selected_region]
                fetch_ranges = [(seg_start, seg_end)]
                row_slices = [
                    (addr, length)
                    for addr, length in mapper.row_ranges()
                    if addr is not None and seg_start <= addr < seg_end
                ]
            chunks = []
            for s, e in fetch_ranges:
                chunks.append(await self.rpc.read_memory(s, e - s))
            buffer = b"".join(chunks)
            start_address = fetch_ranges[0][0] if fetch_ranges else 0
            range_index = []
            offset = 0
            for s, e in fetch_ranges:
                range_index.append((s, e, offset))
                offset += e - s
            store.set_screen_buffer(
                ScreenBuffer(
                    row_slices=row_slices,
                    buffer=buffer,
                    start_address=start_address,
                    range_index=range_index,
                )
            )
            self._dmactl = dmactl
            return True
        except RpcException:
            return False


def _render_char(value: int, use_atascii: bool):
    if value <= 0:
        return " ", 0
    if use_atascii:
        return atascii_to_curses(screen_to_atascii(value))
    v = value & 0x7F
    if 32 <= v <= 126:
        return chr(v), 0
    return ".", 0


def _render_runs(row: bytes, use_atascii: bool):
    if not row:
        return []
    if not use_atascii:
        text = []
        for b in row:
            if b <= 0:
                text.append(" ")
                continue
            v = b & 0x7F
            if 32 <= v <= 126:
                text.append(chr(v))
            else:
                text.append(".")
        return [("".join(text), 0)]

    runs = []
    cur_attr = None
    buf = []
    for b in row:
        ch, attr = _render_char(b, use_atascii=True)
        if cur_attr is None:
            cur_attr = attr
        if attr != cur_attr:
            runs.append(("".join(buf), cur_attr))
            buf = [ch]
            cur_attr = attr
            continue
        buf.append(ch)
    if buf:
        runs.append(("".join(buf), cur_attr))
    return runs


def _parse_row_info(row_info, base_addr: int):
    if row_info is None:
        return None
    if isinstance(row_info, tuple):
        if len(row_info) < 2:
            return None
        first, second = row_info[0], row_info[1]
        if isinstance(first, slice):
            if first.start is None or first.stop is None or second is None:
                return None
            return int(second), int(first.stop - first.start)
        if first is None or second is None:
            return None
        return int(first), int(second)
    if isinstance(row_info, slice):
        if row_info.start is None or row_info.stop is None:
            return None
        return int(base_addr + row_info.start), int(row_info.stop - row_info.start)
    return None
