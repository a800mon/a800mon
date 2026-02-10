import curses

from . import debug
from .actions import ActionDispatcher, Actions, ShortcutInput
from .app import App, Component
from .appstate import AppMode, shortcuts, state
from .cpustate import CpuStateViewer
from .disassembly import DisassemblyInputHandler, DisassemblyViewer
from .displaylist import DisplayListViewer
from .history import HistoryViewer
from .inputwidget import AddressInputWidget, InputWidgetManager
from .rpc import RpcClient
from .screenbuffer import ScreenBufferInspector
from .shortcutbar import ShortcutBar
from .shortcuts import Shortcut, ShortcutLayer
from .socket import SocketTransport
from .topbar import TopBar
from .ui import Color, Screen, Window


class AppModeUpdater(Component):
    def __init__(self, dispatcher):
        self._dispatcher = dispatcher
        self._last_paused = None

    def update(self):
        if self._last_paused is None:
            self._last_paused = state.paused
            self._dispatcher.dispatch(Actions.SYNC_MODE)
            return
        if state.paused != self._last_paused:
            self._last_paused = state.paused
            self._dispatcher.dispatch(Actions.SYNC_MODE)


def main(scr, socket_path):
    rpc = RpcClient(SocketTransport(socket_path))
    dispatcher = ActionDispatcher(rpc)

    wcpu = Window(title="CPU State")
    wdlist = Window(title="DisplayList")
    wscreen = Window(title="Screen Buffer (ATASCII)")
    wdisasm = Window(title="Disassembly")
    waddr_input = Window(border=False)
    whistory = Window(title="History")
    top = Window(border=False)
    bottom = Window(border=False)

    screen_inspector = ScreenBufferInspector(rpc, wscreen)
    disassembly_view = DisassemblyViewer(rpc, wdisasm)
    history_view = HistoryViewer(rpc, whistory, reverse_order=True)
    display_list = DisplayListViewer(rpc, wdlist)
    cpu = CpuStateViewer(rpc, wcpu)
    topbar = TopBar(rpc, top)
    appmode_updater = AppModeUpdater(dispatcher)
    shortcutbar = ShortcutBar(bottom)
    wdisasm.visible = state.disassembly_enabled
    waddr_input.visible = False
    waddr_input.reset_cursor_on_refresh = False

    def init_screen(scr):
        w, h = scr.size
        wcpu.reshape(x=0, y=h - 5, w=w, h=3)
        wdlist.reshape(x=0, y=2, w=40, h=wcpu.y - 3)
        right_x = wdlist.x + wdlist.w + 2
        right_total = max(1, w - right_x)
        gap = 2
        if right_total <= gap + 2:
            base_screen_w = 1
            base_history_w = 1
        else:
            base_screen_w = (right_total - gap) * 2 // 3
            base_history_w = right_total - gap - base_screen_w
            if base_screen_w < 1:
                base_screen_w = 1
            if base_history_w < 1:
                base_history_w = 1
                base_screen_w = max(1, right_total - gap - base_history_w)

        if wdisasm.visible:
            history_w = max(1, base_history_w - 8)
            disasm_w = max(1, base_history_w - 8)
            screen_w = right_total - history_w - disasm_w - 2 * gap
            if screen_w < 1:
                screen_w = 1
                remaining = max(2, right_total - screen_w - 2 * gap)
                history_w = max(1, remaining // 2)
                disasm_w = max(1, remaining - history_w)

            wscreen.reshape(x=right_x, y=2, w=screen_w, h=wcpu.y - 3)
            wdisasm.reshape(
                x=wscreen.x + wscreen.w + gap,
                y=2,
                w=disasm_w,
                h=wcpu.y - 3,
            )
            waddr_input.reshape(x=wdisasm.x + 1, y=wdisasm.y + 1, w=6, h=1)
            whistory.reshape(
                x=wdisasm.x + wdisasm.w + gap,
                y=2,
                w=history_w,
                h=wcpu.y - 3,
            )
        else:
            screen_w = base_screen_w
            history_w = base_history_w
            wscreen.reshape(x=right_x, y=2, w=screen_w, h=wcpu.y - 3)
            whistory.reshape(
                x=wscreen.x + wscreen.w + gap,
                y=2,
                w=history_w,
                h=wcpu.y - 3,
            )
        top.reshape(x=0, y=0, w=w, h=1)
        bottom.reshape(x=0, y=h - 1, w=w, h=1)

    screen = Screen(scr, layout_initializer=init_screen)
    app = App(screen=screen)
    input_manager = InputWidgetManager(dispatcher, app.rebuild_screen)
    address_input = AddressInputWidget(
        waddr_input,
        color=Color.ADDRESS,
        on_change=lambda value: (
            dispatcher.dispatch(Actions.SET_DISASSEMBLY_ADDR, value)
            if value is not None
            else None
        ),
        on_enter=lambda value: (
            dispatcher.dispatch(Actions.SET_DISASSEMBLY_ADDR, value)
            if value is not None
            else None
        ),
    )
    disasm_input = DisassemblyInputHandler(
        screen=screen,
        disasm_window=wdisasm,
        input_manager=input_manager,
        address_widget=address_input,
    )

    def build_shortcuts():
        def action(key, label, action):
            return Shortcut(key, label, lambda: dispatcher.dispatch(action))

        step = action(curses.KEY_F0 + 5, "Step", Actions.STEP)
        step_vblank = action(
            curses.KEY_F0 + 6, "Step VBLANK", Actions.STEP_VBLANK
        )
        pause = action(curses.KEY_F0 + 8, "Pause", Actions.PAUSE)
        cont = action(curses.KEY_F0 + 8, "Continue", Actions.CONTINUE)
        enter_shutdown = action(27, "Shutdown", Actions.ENTER_SHUTDOWN)
        exit_shutdown = action(27, "Back", Actions.EXIT_SHUTDOWN)

        normal = ShortcutLayer("NORMAL")
        normal.add(step)
        normal.add(step_vblank)
        normal.add(pause)
        normal.add(enter_shutdown)

        debug = ShortcutLayer("DEBUG", color=Color.APPMODE_DEBUG)
        debug.add(step)
        debug.add(step_vblank)
        debug.add(cont)
        debug.add(enter_shutdown)

        shutdown = ShortcutLayer("SHUTDOWN", color=Color.APPMODE_SHUTDOWN)
        shutdown.add(action("c", "Cold start", Actions.COLDSTART))
        shutdown.add(action("w", "Warm start", Actions.WARMSTART))
        shutdown.add(action("t", "Terminate", Actions.TERMINATE))
        shutdown.add(exit_shutdown)

        shortcuts.add(AppMode.NORMAL, normal)
        shortcuts.add(AppMode.DEBUG, debug)
        shortcuts.add(AppMode.SHUTDOWN, shutdown)

        def toggle_dlist():
            new_val = not state.displaylist_inspect
            dispatcher.dispatch(Actions.SET_DLIST_INSPECT, new_val)
            screen.focus(wdlist if new_val else None)

        def toggle_disassembly():
            if not wdisasm.visible:
                dispatcher.dispatch(Actions.SET_DISASSEMBLY, True)
                wdisasm.visible = True
                app.rebuild_screen()
                screen.focus(wdisasm)
            elif screen.focused is not wdisasm:
                screen.focus(wdisasm)
            else:
                screen.focus(wdlist if state.displaylist_inspect else None)
                dispatcher.dispatch(Actions.SET_DISASSEMBLY, False)
                wdisasm.visible = False
                app.rebuild_screen()

        shortcuts.add_global(Shortcut("s", "Toggle DLIST", toggle_dlist))
        shortcuts.add_global(Shortcut("d", "Disassembly", toggle_disassembly))
        shortcuts.add_global(
            Shortcut(
                9,
                "ATASCII/ASCII",
                lambda: dispatcher.dispatch(
                    Actions.SET_ATASCII, not state.use_atascii
                ),
            )
        )
        shortcuts.add_global(action("q", "Quit", Actions.QUIT))

    input_processor = ShortcutInput(shortcuts, dispatcher)
    app.add_component(dispatcher)
    app.add_component(input_manager)
    app.add_component(disasm_input)
    app.add_component(input_processor)
    app.add_component(topbar)
    app.add_component(appmode_updater)
    app.add_component(shortcutbar)
    app.add_component(cpu)
    app.add_component(display_list)
    app.add_component(screen_inspector)
    app.add_component(disassembly_view)
    app.add_component(address_input)
    app.add_component(history_view)

    build_shortcuts()
    app.loop()


def run(socket_path):
    try:
        curses.wrapper(lambda scr: main(scr, socket_path))
    except KeyboardInterrupt:
        try:
            curses.endwin()
        except curses.error:
            pass
        raise
    except curses.error:
        try:
            curses.endwin()
        except curses.error:
            pass
        raise
    except Exception:
        try:
            curses.endwin()
        except curses.error:
            pass
        raise
    finally:
        debug.print_log()
