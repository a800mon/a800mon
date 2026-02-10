import dataclasses
import time

from . import debug
from .app import VisualRpcComponent
from .appstate import state, store
from .atascii import atascii_to_curses, screen_to_atascii
from .datastructures import ScreenBuffer
from .displaylist import DMACTL_ADDR, DMACTL_HW_ADDR, DisplayListMemoryMapper
from .rpc import RpcException
from .ui import Color


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
        self._update_interval = kwargs.pop("update_inteval", 0.05)
        super().__init__(*args, **kwargs)
        self._inspect = False
        self._cx = 0
        self._cy = 0
        self._last_update = None
        self._dmactl = 0
        self._last_use_atascii = None

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

        self.window.cursor = 0, 0
        segs = state.dlist.screen_segments(self._dmactl)
        active_seg = None
        if state.dlist_selected_region is not None and segs:
            if 0 <= state.dlist_selected_region < len(segs):
                active_seg = segs[state.dlist_selected_region]
        printed_rows = 0
        for row_info in state.screen_buffer.row_slices:
            if printed_rows >= self.window._ih:
                break
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
            row = state.screen_buffer.get_range(start_addr, length)[
                : self.window._iw - 8
            ]
            self.window.print(f"{start_addr:04X}: ", attr=Color.ADDRESS.attr())
            for i, b in enumerate(row):
                ac, attr = _render_char(b, state.use_atascii)
                self.window.print_char(ac, attr=attr)
            self.window.clear_to_eol()
            self.window.newline()
            printed_rows += 1
        self.window.clear_to_bottom()

        if not self._inspect:
            return

        self.window.invert_char(self._cx, self._cy)

    def update(self):
        if (
            self._last_update
            and time.time() - self._last_update < self._update_interval
        ):
            return
        try:
            dmactl = self.rpc.read_byte(DMACTL_ADDR)
            if (dmactl & 0x03) == 0:
                dmactl = self.rpc.read_byte(DMACTL_HW_ADDR)
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
            buffer = b"".join(
                self.rpc.read_memory(s, e - s) for s, e in fetch_ranges
            )
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
            self._last_update = time.time()
        except RpcException:
            pass


def _render_char(value: int, use_atascii: bool):
    if value <= 0:
        return " ", 0
    if use_atascii:
        return atascii_to_curses(screen_to_atascii(value))
    v = value & 0x7F
    if 32 <= v <= 126:
        return chr(v), 0
    return ".", 0


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
