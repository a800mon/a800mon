import dataclasses
import enum

from ..datastructures import CpuState, DisplayList


class AppMode(enum.Enum):
    NORMAL = 1
    DEBUG = 2
    SHUTDOWN = 3


@dataclasses.dataclass
class AppStateData:
    dlist: DisplayList
    cpu: CpuState
    cpu_disasm: str
    monitor_frame_time_ms: int
    paused: bool
    emu_ms: int
    reset_ms: int
    crashed: bool
    state_seq: int
    last_rpc_error: str | None
    active_mode: AppMode
    ui_frozen: bool
    disassembly_enabled: bool
    disassembly_addr: int | None
    dmactl: int
    breakpoints_supported: bool


_state = AppStateData(
    dlist=DisplayList(),
    cpu=CpuState(),
    cpu_disasm="",
    monitor_frame_time_ms=0,
    paused=False,
    emu_ms=0,
    reset_ms=0,
    crashed=False,
    state_seq=0,
    last_rpc_error=None,
    active_mode=AppMode.NORMAL,
    ui_frozen=False,
    disassembly_enabled=True,
    disassembly_addr=None,
    dmactl=0,
    breakpoints_supported=False,
)


class StateStore:
    def __init__(self, backing: AppStateData):
        self._s = backing

    def set_active_mode(self, mode: AppMode):
        self._s.active_mode = mode

    def set_ui_frozen(self, enabled: bool):
        self._s.ui_frozen = enabled

    def set_disassembly_enabled(self, enabled: bool):
        self._s.disassembly_enabled = enabled

    def set_disassembly_addr(self, addr: int):
        self._s.disassembly_addr = addr & 0xFFFF

    def set_breakpoints_supported(self, enabled: bool):
        self._s.breakpoints_supported = enabled

    def set_status(
        self, paused: bool, emu_ms: int, reset_ms: int, crashed: bool, state_seq: int
    ):
        self._s.paused = paused
        self._s.emu_ms = emu_ms
        self._s.reset_ms = reset_ms
        self._s.crashed = crashed
        self._s.state_seq = state_seq

    def set_last_rpc_error(self, error: str | None):
        self._s.last_rpc_error = error

    def set_cpu(self, cpu: CpuState):
        self._s.cpu = cpu

    def set_cpu_disasm(self, cpu_disasm: str):
        self._s.cpu_disasm = cpu_disasm

    def set_dlist(self, dlist: DisplayList, dmactl: int):
        self._s.dlist = dlist
        self._s.dmactl = dmactl

    def set_frame_time_ms(self, ms: int):
        self._s.monitor_frame_time_ms = ms


_store = StateStore(_state)
store = _store


class StateProxy:
    def __init__(self, backing: AppStateData):
        self._backing = backing

    def __getattr__(self, name):
        return getattr(self._backing, name)

    def __setattr__(self, name, value):
        if name == "_backing":
            object.__setattr__(self, name, value)
            return
        raise AttributeError(
            "State is read-only. Use ActionDispatcher to update state."
        )


state = StateProxy(_state)
