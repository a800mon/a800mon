import dataclasses

from .datastructures import CpuState, DisplayList, ScreenBuffer


@dataclasses.dataclass
class AppState:
    dlist: DisplayList
    screen_buffer: ScreenBuffer
    cpu: CpuState
    monitor_frame_time_ms: int
    paused: bool
    emu_ms: int
    reset_ms: int
    crashed: bool
    dlist_selected_region: int | None


state = AppState(
    dlist=DisplayList(),
    screen_buffer=ScreenBuffer(),
    cpu=CpuState(),
    monitor_frame_time_ms=0,
    paused=False,
    emu_ms=0,
    reset_ms=0,
    crashed=False,
    dlist_selected_region=None,
)
