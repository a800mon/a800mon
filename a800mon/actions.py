import enum
import curses

from .app import Component, InputComponent, StopLoop
from .appstate import AppMode, state, store
from .rpc import Command, RpcException


class Actions(enum.Enum):
    STEP = enum.auto()
    STEP_VBLANK = enum.auto()
    PAUSE = enum.auto()
    CONTINUE = enum.auto()
    SYNC_MODE = enum.auto()
    ENTER_SHUTDOWN = enum.auto()
    EXIT_SHUTDOWN = enum.auto()
    COLDSTART = enum.auto()
    WARMSTART = enum.auto()
    TERMINATE = enum.auto()
    SET_DLIST_INSPECT = enum.auto()
    SET_ATASCII = enum.auto()
    SET_DISASSEMBLY = enum.auto()
    SET_DISASSEMBLY_ADDR = enum.auto()
    SET_INPUT_FOCUS = enum.auto()
    SET_INPUT_BUFFER = enum.auto()
    DLIST_NEXT = enum.auto()
    DLIST_PREV = enum.auto()
    QUIT = enum.auto()


class ActionDispatcher(Component):
    def __init__(self, rpc):
        self._rpc = rpc
        self._rpc_queue = []

    def _call_rpc(self, cmd):
        try:
            self._rpc.call(cmd)
        except RpcException:
            pass

    def _enqueue_rpc(self, cmd):
        self._rpc_queue.append(cmd)

    def dispatch(self, action: Actions, value=None):
        if action == Actions.STEP:
            self._enqueue_rpc(Command.STEP)
            return
        if action == Actions.STEP_VBLANK:
            self._enqueue_rpc(Command.STEP_VBLANK)
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
        if action == Actions.SET_DLIST_INSPECT:
            new_val = bool(value)
            store.set_displaylist_inspect(new_val)
            if not new_val:
                store.set_dlist_selected_region(None)
            elif state.dlist_selected_region is None:
                store.set_dlist_selected_region(0)
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
        if action == Actions.SET_INPUT_BUFFER:
            store.set_input_buffer(str(value))
            return
        if action == Actions.DLIST_NEXT:
            if not state.displaylist_inspect:
                return
            store.set_dlist_selected_region((state.dlist_selected_region or 0) + 1)
            return
        if action == Actions.DLIST_PREV:
            if not state.displaylist_inspect:
                return
            new_idx = (state.dlist_selected_region or 0) - 1
            if new_idx < 0:
                new_idx = 0
            store.set_dlist_selected_region(new_idx)
            return
        if action == Actions.QUIT:
            raise StopLoop

    def post_render(self):
        if not self._rpc_queue:
            return
        queue, self._rpc_queue = self._rpc_queue, []
        for cmd in queue:
            self._call_rpc(cmd)

    def update_status(self, status):
        store.set_status(
            status.paused, status.emu_ms, status.reset_ms, status.crashed
        )

    def update_cpu(self, cpu_state):
        store.set_cpu(cpu_state)

    def update_dlist(self, dlist):
        store.set_dlist(dlist, state.dmactl)

    def update_dmactl(self, dmactl: int):
        store.set_dlist(state.dlist, dmactl)

    def update_screen_buffer(self, screen_buffer):
        store.set_screen_buffer(screen_buffer)

    def update_frame_time_ms(self, ms):
        store.set_frame_time_ms(ms)


class ShortcutInput(InputComponent):
    def __init__(self, shortcuts, dispatcher):
        self._shortcuts = shortcuts
        self._dispatcher = dispatcher

    def handle_input(self, ch):
        if self._shortcuts.has_global(ch):
            self._shortcuts.get_global(ch).callback()
            return True

        layer = self._shortcuts.get(state.active_mode)
        if layer and layer.has(ch):
            layer.get(ch).callback()
            return True

        if state.displaylist_inspect and ch in (ord("j"), ord("k")):
            if ch == ord("j"):
                self._dispatcher.dispatch(Actions.DLIST_NEXT)
            else:
                self._dispatcher.dispatch(Actions.DLIST_PREV)
            return True
        if state.displaylist_inspect and ch in (curses.KEY_UP, curses.KEY_DOWN):
            if ch == curses.KEY_DOWN:
                self._dispatcher.dispatch(Actions.DLIST_NEXT)
            else:
                self._dispatcher.dispatch(Actions.DLIST_PREV)
            return True
        return False
