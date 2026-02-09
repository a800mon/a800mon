import dataclasses
import time

from .app import RpcComponent
from .appstate import state
from .atascii import atascii_to_curses, screen_to_atascii
from .datastructures import ScreenBuffer
from .displaylist import DMACTL_ADDR, DisplayListMemoryMapper
from .rpc import RpcException
from .ui import Color
from . import debug


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


class ScreenBufferInspector(RpcComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._inspect = False
        self._cx = 0
        self._cy = 0
        self._last_update = None

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
        for rownum, slice_ in enumerate(state.screen_buffer.row_slices):
            if not slice_:
                continue
            if rownum > self.window._ih - 1:
                break
            row = state.screen_buffer.buffer[slice_][: self.window._iw - 8]
            start_addr = state.screen_buffer.start_address + slice_.start
            self.window.print(f"{start_addr:04X}: ", attr=Color.ADDRESS.attr())
            for i, b in enumerate(row):
                ac, attr = (
                    atascii_to_curses(screen_to_atascii(b)) if b > 0 else (" ", 0)
                )
                self.window.print_char(ac, attr=attr)
            self.window.newline()
        self.window.clear_to_bottom()

        if not self._inspect:
            return

        self.window.invert_char(self._cx, self._cy)

    def update(self):
        if self._last_update and time.time() - self._last_update < 0.5:
            return
        try:
            dmactl = self.rpc.read_vector(DMACTL_ADDR)
            fetch_ranges, row_slices = DisplayListMemoryMapper(
                state.dlist, dmactl
            ).plan()
            buffer = b"".join(self.rpc.read_memory(s, e - s) for s, e in fetch_ranges)
            start_address = fetch_ranges[0][0] if fetch_ranges else 0
            debug.log(f"{self} fetch_ranges={len(fetch_ranges)}")
            for i, rng in enumerate(fetch_ranges):
                debug.log(f"{self} range {i}: {rng} len={rng[1]-rng[0]}")
            state.screen_buffer = ScreenBuffer(
                row_slices=row_slices, buffer=buffer, start_address=start_address
            )
            self._last_update = time.time()
        except RpcException:
            pass
