import dataclasses

from .datastructures import CpuState, DisplayList, ScreenBuffer


@dataclasses.dataclass
class AppState:
    dlist: DisplayList
    screen_buffer: ScreenBuffer
    cpu: CpuState


state = AppState(dlist=DisplayList(), screen_buffer=ScreenBuffer(), cpu=CpuState())
