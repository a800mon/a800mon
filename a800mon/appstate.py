import dataclasses
import enum

from .datastructures import CpuState, DisplayList, ScreenBuffer
from .shortcuts import ShortcutManager


class AppMode(enum.Enum):
    NORMAL = 1
    DEBUG = 2
    SHUTDOWN = 3


@dataclasses.dataclass
class AppStateData:
    dlist: DisplayList
    screen_buffer: ScreenBuffer
    cpu: CpuState
    monitor_frame_time_ms: int
    paused: bool
    emu_ms: int
    reset_ms: int
    crashed: bool
    dlist_selected_region: int | None
    active_mode: AppMode
    displaylist_inspect: bool
    use_atascii: bool
    dmactl: int


_state = AppStateData(
    dlist=DisplayList(),
    screen_buffer=ScreenBuffer(),
    cpu=CpuState(),
    monitor_frame_time_ms=0,
    paused=False,
    emu_ms=0,
    reset_ms=0,
    crashed=False,
    dlist_selected_region=None,
    active_mode=AppMode.NORMAL,
    displaylist_inspect=False,
    use_atascii=True,
    dmactl=0,
)

class StateStore:
    def __init__(self, backing: AppStateData):
        self._s = backing

    def set_active_mode(self, mode: AppMode):
        self._s.active_mode = mode

    def set_displaylist_inspect(self, enabled: bool):
        self._s.displaylist_inspect = enabled

    def set_use_atascii(self, enabled: bool):
        self._s.use_atascii = enabled

    def set_dlist_selected_region(self, idx: int | None):
        self._s.dlist_selected_region = idx

    def set_status(self, paused: bool, emu_ms: int, reset_ms: int, crashed: bool):
        self._s.paused = paused
        self._s.emu_ms = emu_ms
        self._s.reset_ms = reset_ms
        self._s.crashed = crashed

    def set_cpu(self, cpu: CpuState):
        self._s.cpu = cpu

    def set_dlist(self, dlist: DisplayList, dmactl: int):
        self._s.dlist = dlist
        self._s.dmactl = dmactl

    def set_screen_buffer(self, screen_buffer: ScreenBuffer):
        self._s.screen_buffer = screen_buffer

    def set_frame_time_ms(self, ms: int):
        self._s.monitor_frame_time_ms = ms


_store = StateStore(_state)
store = _store


class StateProxy:
    def __init__(self, backing):
        object.__setattr__(self, "_backing", backing)

    def __getattr__(self, name):
        return getattr(self._backing, name)

    def __setattr__(self, name, value):
        raise AttributeError(
            "State is read-only. Use ActionDispatcher to update state."
        )


state = StateProxy(_state)

shortcuts = ShortcutManager()
