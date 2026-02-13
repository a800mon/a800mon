import enum

from .app import Component, InputComponent, StopLoop
from .appstate import AppMode, state, store
from .rpc import Command, RpcException


class Actions(enum.Enum):
    STEP = enum.auto()
    STEP_VBLANK = enum.auto()
    STEP_OVER = enum.auto()
    PAUSE = enum.auto()
    CONTINUE = enum.auto()
    SYNC_MODE = enum.auto()
    ENTER_SHUTDOWN = enum.auto()
    EXIT_SHUTDOWN = enum.auto()
    COLDSTART = enum.auto()
    WARMSTART = enum.auto()
    TERMINATE = enum.auto()
    SET_ATASCII = enum.auto()
    SET_DISASSEMBLY = enum.auto()
    SET_DISASSEMBLY_ADDR = enum.auto()
    SET_INPUT_FOCUS = enum.auto()
    SET_INPUT_TARGET = enum.auto()
    SET_INPUT_BUFFER = enum.auto()
    QUIT = enum.auto()


class ActionDispatcher(Component):
    def __init__(self, rpc):
        self._rpc = rpc
        self._rpc_queue = []
        self._after_rpc = None

    async def _call_rpc(self, cmd):
        try:
            await self._rpc.call(cmd)
        except RpcException:
            pass

    def _enqueue_rpc(self, cmd):
        self._rpc_queue.append(cmd)

    def set_after_rpc(self, callback):
        self._after_rpc = callback

    def dispatch(self, action: Actions, value=None):
        if action == Actions.STEP:
            self._enqueue_rpc(Command.STEP)
            return
        if action == Actions.STEP_VBLANK:
            self._enqueue_rpc(Command.STEP_VBLANK)
            return
        if action == Actions.STEP_OVER:
            self._enqueue_rpc(Command.STEP_OVER)
            return
        if action == Actions.PAUSE:
            self._enqueue_rpc(Command.PAUSE)
            store.set_active_mode(AppMode.DEBUG)
            return
        if action == Actions.CONTINUE:
            self._enqueue_rpc(Command.CONTINUE)
            store.set_active_mode(AppMode.NORMAL)
            return
        if action == Actions.SYNC_MODE:
            if state.active_mode in (AppMode.DEBUG, AppMode.NORMAL):
                store.set_active_mode(
                    AppMode.DEBUG if state.paused else AppMode.NORMAL
                )
            return
        if action == Actions.ENTER_SHUTDOWN:
            store.set_active_mode(AppMode.SHUTDOWN)
            return
        if action == Actions.EXIT_SHUTDOWN:
            store.set_active_mode(
                AppMode.DEBUG if state.paused else AppMode.NORMAL
            )
            return
        if action == Actions.COLDSTART:
            self._enqueue_rpc(Command.COLDSTART)
            self.dispatch(Actions.EXIT_SHUTDOWN)
            return
        if action == Actions.WARMSTART:
            self._enqueue_rpc(Command.WARMSTART)
            self.dispatch(Actions.EXIT_SHUTDOWN)
            return
        if action == Actions.TERMINATE:
            self._enqueue_rpc(Command.STOP_EMULATOR)
            self.dispatch(Actions.EXIT_SHUTDOWN)
            return
        if action == Actions.SET_ATASCII:
            store.set_use_atascii(bool(value))
            return
        if action == Actions.SET_DISASSEMBLY:
            store.set_disassembly_enabled(bool(value))
            return
        if action == Actions.SET_DISASSEMBLY_ADDR:
            store.set_disassembly_addr(int(value))
            return
        if action == Actions.SET_INPUT_FOCUS:
            store.set_input_focus(bool(value))
            return
        if action == Actions.SET_INPUT_TARGET:
            store.set_input_target(value)
            return
        if action == Actions.SET_INPUT_BUFFER:
            store.set_input_buffer(str(value))
            return
        if action == Actions.QUIT:
            raise StopLoop

    async def post_render(self):
        if not self._rpc_queue:
            return False
        queue, self._rpc_queue = self._rpc_queue, []
        for cmd in queue:
            await self._call_rpc(cmd)
        if self._after_rpc is not None:
            self._after_rpc()
        return False

    def update_status(self, status):
        store.set_status(
            status.paused, status.emu_ms, status.reset_ms, status.crashed, status.state_seq
        )

    def update_last_rpc_error(self, error: str | None):
        store.set_last_rpc_error(error)

    def update_cpu(self, cpu_state, cpu_disasm: str = ""):
        store.set_cpu(cpu_state)
        store.set_cpu_disasm(cpu_disasm)

    def update_dlist(self, dlist):
        store.set_dlist(dlist, state.dmactl)

    def update_dmactl(self, dmactl: int):
        store.set_dlist(state.dlist, dmactl)

    def update_screen_buffer(self, screen_buffer):
        store.set_screen_buffer(screen_buffer)

    def update_frame_time_ms(self, ms):
        store.set_frame_time_ms(ms)

    def update_watchers(self, watchers):
        store.set_watchers(watchers)

    def update_breakpoints(self, enabled, breakpoints):
        store.set_breakpoints(enabled, breakpoints)

    def update_breakpoints_supported(self, enabled):
        store.set_breakpoints_supported(enabled)


class ShortcutInput(InputComponent):
    def __init__(self, shortcuts, dispatcher):
        self._shortcuts = shortcuts
        self._dispatcher = dispatcher

    def handle_input(self, ch):
        if state.input_focus:
            return False
        layer = self._shortcuts.get(state.active_mode)
        if layer and layer.has(ch):
            layer.get(ch).callback()
            return True
        if self._shortcuts.has_global(ch):
            self._shortcuts.get_global(ch).callback()
            return True
        return False
