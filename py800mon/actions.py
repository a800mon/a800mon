import enum

from .app import Component, StopLoop
from .monitor.appstate import AppMode, state, store
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
    TOGGLE_FREEZE = enum.auto()
    SET_DISASSEMBLY = enum.auto()
    SET_DISASSEMBLY_ADDR = enum.auto()
    SET_BREAKPOINTS_SUPPORTED = enum.auto()
    SET_STATUS = enum.auto()
    SET_LAST_RPC_ERROR = enum.auto()
    SET_CPU = enum.auto()
    SET_DLIST = enum.auto()
    SET_DMACTL = enum.auto()
    SET_FRAME_TIME_MS = enum.auto()
    SET_INPUT_FOCUS = enum.auto()
    QUIT = enum.auto()


class ActionDispatcher(Component):
    def __init__(self, rpc, set_input_focus=lambda _handler: None):
        super().__init__()
        self._rpc = rpc
        self._rpc_queue = []
        self._rpc_flushed = False
        self._set_input_focus = set_input_focus

    async def update(self):
        if not self._rpc_queue:
            return False
        queue, self._rpc_queue = self._rpc_queue, []
        for cmd in queue:
            await self._call_rpc(cmd)
        self._rpc_flushed = True
        return True

    async def _call_rpc(self, cmd):
        try:
            await self._rpc.call(cmd)
        except RpcException:
            pass

    def _enqueue_rpc(self, cmd):
        self._rpc_queue.append(cmd)

    def set_input_focus_handler(self, callback):
        self._set_input_focus = callback

    def take_rpc_flushed(self):
        flushed = self._rpc_flushed
        self._rpc_flushed = False
        return flushed

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
                store.set_active_mode(AppMode.DEBUG if state.paused else AppMode.NORMAL)
            return
        if action == Actions.ENTER_SHUTDOWN:
            store.set_active_mode(AppMode.SHUTDOWN)
            return
        if action == Actions.EXIT_SHUTDOWN:
            store.set_active_mode(AppMode.DEBUG if state.paused else AppMode.NORMAL)
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
        if action == Actions.TOGGLE_FREEZE:
            store.set_ui_frozen(not state.ui_frozen)
            return
        if action == Actions.SET_DISASSEMBLY:
            store.set_disassembly_enabled(value)
            return
        if action == Actions.SET_DISASSEMBLY_ADDR:
            store.set_disassembly_addr(int(value))
            return
        if action == Actions.SET_BREAKPOINTS_SUPPORTED:
            store.set_breakpoints_supported(value)
            return
        if action == Actions.SET_STATUS:
            status = value
            store.set_status(
                status.paused,
                status.emu_ms,
                status.reset_ms,
                status.crashed,
                status.state_seq,
            )
            return
        if action == Actions.SET_LAST_RPC_ERROR:
            store.set_last_rpc_error(value)
            return
        if action == Actions.SET_CPU:
            cpu_state, cpu_disasm = value
            store.set_cpu(cpu_state)
            store.set_cpu_disasm(cpu_disasm)
            return
        if action == Actions.SET_DLIST:
            dlist, dmactl = value
            store.set_dlist(dlist, int(dmactl))
            return
        if action == Actions.SET_DMACTL:
            store.set_dlist(state.dlist, int(value))
            return
        if action == Actions.SET_FRAME_TIME_MS:
            store.set_frame_time_ms(int(value))
            return
        if action == Actions.SET_INPUT_FOCUS:
            self._set_input_focus(value)
            return
        if action == Actions.QUIT:
            raise StopLoop


class ShortcutsComponent(Component):
    def __init__(self, shortcuts):
        super().__init__()
        self._shortcuts = shortcuts

    def handle_input(self, ch):
        layer = self._shortcuts.get(state.active_mode)
        if layer and layer.has(ch):
            layer.get(ch).callback()
            return True
        if self._shortcuts.has_global(ch):
            self._shortcuts.get_global(ch).callback()
            return True
        return False
