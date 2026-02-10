import curses

from . import debug
from .actions import ActionDispatcher, Actions, ShortcutInput
from .app import App, Component
from .appstate import AppMode, shortcuts, state
from .cpustate import CpuStateViewer
from .displaylist import DisplayListViewer
from .history import HistoryViewer
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
    whistory = Window(title="History")
    top = Window(border=False)
    bottom = Window(border=False)

    screen_inspector = ScreenBufferInspector(rpc, wscreen)
    history_view = HistoryViewer(rpc, whistory, reverse_order=True)
    display_list = DisplayListViewer(rpc, wdlist)
    cpu = CpuStateViewer(rpc, wcpu)
    topbar = TopBar(rpc, top)
    appmode_updater = AppModeUpdater(dispatcher)
    shortcutbar = ShortcutBar(bottom)

    def init_screen(scr):
        w, h = scr.size
        wcpu.reshape(x=0, y=h - 5, w=w, h=3)
        wdlist.reshape(x=0, y=2, w=40, h=wcpu.y - 3)
        right_x = wdlist.x + wdlist.w + 2
        right_total = max(1, w - right_x)
        gap = 2
        if right_total <= gap + 2:
            screen_w = 1
            history_w = 1
        else:
            screen_w = (right_total - gap) * 2 // 3
            history_w = right_total - gap - screen_w
            if screen_w < 1:
                screen_w = 1
            if history_w < 1:
                history_w = 1
                screen_w = max(1, right_total - gap - history_w)
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

        shortcuts.add_global(Shortcut("d", "Toggle DLIST", toggle_dlist))
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
    app.add_component(input_processor)
    app.add_component(topbar)
    app.add_component(appmode_updater)
    app.add_component(shortcutbar)
    app.add_component(cpu)
    app.add_component(display_list)
    app.add_component(screen_inspector)
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
