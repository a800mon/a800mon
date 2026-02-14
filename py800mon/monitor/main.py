import asyncio
import curses

from .. import debug
from ..actions import ActionDispatcher, Actions, ShortcutsComponent
from ..app import App, Component
from ..emulator import CAP_MONITOR_BREAKPOINTS
from ..rpc import RpcClient, RpcException
from ..shortcuts import Shortcut, ShortcutLayer, ShortcutManager
from ..socket import SocketTransport
from ..ui import Color, Screen, Window
from .appstate import AppMode, state
from .breakpoints import BreakpointsViewer
from .cpustate import CpuStateViewer
from .disassembly import DisassemblyViewer
from .displaylist import DisplayListViewer
from .history import HistoryViewer
from .screenbuffer import ScreenBufferInspector
from .shortcutbar import ShortcutBar
from .statusupdater import StatusUpdater
from .topbar import TopBar
from .watchers import WatchersViewer


class AppModeUpdater(Component):
    def __init__(self, app, screen, breakpoints_window):
        super().__init__()
        self._app = app
        self._screen = screen
        self._breakpoints_window = breakpoints_window
        self._last_paused = None
        self._last_breakpoints_visible = breakpoints_window.visible

    async def update(self):
        changed = False
        if self._last_paused is None:
            self._last_paused = state.paused
            self.app.dispatch_action(Actions.SYNC_MODE)
            changed = True
        elif state.paused != self._last_paused:
            self._last_paused = state.paused
            self.app.dispatch_action(Actions.SYNC_MODE)
            changed = True
        visible = state.breakpoints_supported
        if visible == self._last_breakpoints_visible:
            return changed
        self._last_breakpoints_visible = visible
        if not visible and self._screen.focused is self._breakpoints_window:
            self._screen.focus(None)
        self._breakpoints_window.visible = visible
        self._app.rebuild_screen()
        return True


async def main(scr, socket_path):
    rpc = RpcClient(SocketTransport(socket_path))
    dispatcher = ActionDispatcher(rpc)
    try:
        caps = await rpc.config()
    except RpcException:
        caps = []
    dispatcher.dispatch(
        Actions.SET_BREAKPOINTS_SUPPORTED,
        CAP_MONITOR_BREAKPOINTS in set(caps),
    )

    wcpu = Window(title="CPU State")
    wdlist = Window(title="DisplayList")
    wwatch = Window(title="Watchers")
    wscreen = Window(title="Screen Buffer")
    wscreen.add_tag("ATASCII", tag_id="atascii", active=True)
    wscreen.add_tag("ASCII", tag_id="ascii", active=False)
    wdisasm = Window(title="Disassembler")
    wdisasm.add_tag("FOLLOW", tag_id="follow", active=True)
    whistory = Window(title="History")
    wbreakpoints = Window(title="Breakpoints")
    wbreakpoints.add_tag("ENABLED", tag_id="bp_enabled", active=False)
    top = Window(border=False)
    bottom = Window(border=False)

    screen_inspector = ScreenBufferInspector(rpc, wscreen)
    disassembly_view = DisassemblyViewer(rpc, wdisasm)
    watchers_view = WatchersViewer(rpc, wwatch)
    breakpoints_view = BreakpointsViewer(rpc, wbreakpoints)
    history_view = HistoryViewer(rpc, whistory, reverse_order=True)
    display_list = DisplayListViewer(rpc, wdlist)
    cpu = CpuStateViewer(wcpu)
    topbar = TopBar(top)
    status_updater = StatusUpdater(
        rpc=rpc,
        dispatcher=dispatcher,
        paused_interval=0.2,
        running_interval=0.05,
    )
    shortcuts = ShortcutManager()
    shortcutbar = ShortcutBar(bottom, shortcuts)
    wdisasm.visible = state.disassembly_enabled
    wbreakpoints.visible = state.breakpoints_supported

    def init_screen(scr):
        w, h = scr.size
        top_y = 1
        breakpoints_h_target = 13
        wcpu.reshape(x=0, y=h - 4, w=w, h=3)
        old_upper_h = max(1, wcpu.y - top_y - 1)
        upper_h = old_upper_h + 1
        left_total_h = max(2, old_upper_h)
        old_dlist_h = max(1, left_total_h // 2)
        dlist_h = old_dlist_h
        watch_h = max(1, left_total_h - old_dlist_h + 1)
        transfer = min(4, max(0, watch_h - 1))
        dlist_h += transfer
        watch_h -= transfer
        wdlist.reshape(x=0, y=top_y, w=40, h=dlist_h)
        wwatch.reshape(x=0, y=top_y + dlist_h, w=40, h=watch_h)
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

            wscreen.reshape(x=right_x, y=top_y, w=screen_w, h=upper_h)
            wdisasm.reshape(
                x=wscreen.x + wscreen.w + gap,
                y=top_y,
                w=disasm_w,
                h=upper_h,
            )
            history_x = wdisasm.x + wdisasm.w + gap
            history_h = upper_h
            if wbreakpoints.visible:
                break_h = min(
                    breakpoints_h_target,
                    max(1, history_h - 1),
                )
                history_top_h = max(1, history_h - break_h)
                break_h = max(1, history_h - history_top_h)
                whistory.reshape(
                    x=history_x,
                    y=top_y,
                    w=history_w,
                    h=history_top_h,
                )
                wbreakpoints.reshape(
                    x=history_x,
                    y=top_y + history_top_h,
                    w=history_w,
                    h=break_h,
                )
            else:
                whistory.reshape(
                    x=history_x,
                    y=top_y,
                    w=history_w,
                    h=history_h,
                )
        else:
            screen_w = base_screen_w
            history_w = base_history_w
            wscreen.reshape(x=right_x, y=top_y, w=screen_w, h=upper_h)
            history_x = wscreen.x + wscreen.w + gap
            history_h = upper_h
            if wbreakpoints.visible:
                break_h = min(
                    breakpoints_h_target,
                    max(1, history_h - 1),
                )
                history_top_h = max(1, history_h - break_h)
                break_h = max(1, history_h - history_top_h)
                whistory.reshape(
                    x=history_x,
                    y=top_y,
                    w=history_w,
                    h=history_top_h,
                )
                wbreakpoints.reshape(
                    x=history_x,
                    y=top_y + history_top_h,
                    w=history_w,
                    h=break_h,
                )
            else:
                whistory.reshape(
                    x=history_x,
                    y=top_y,
                    w=history_w,
                    h=history_h,
                )
        top.reshape(x=0, y=0, w=w, h=1)
        bottom.reshape(x=0, y=h - 1, w=w, h=1)

    screen = Screen(scr, shortcuts, layout_initializer=init_screen)
    dispatcher.set_input_focus_handler(screen.set_input_focus)
    screen.set_focus_order([wdlist, wwatch, wscreen, wdisasm, whistory, wbreakpoints])
    app = App(
        screen=screen,
        dispatcher=dispatcher,
        status_updater=status_updater,
        input_timeout_ms=200,
    )
    appmode_updater = AppModeUpdater(
        app=app,
        screen=screen,
        breakpoints_window=wbreakpoints,
    )

    def build_shortcuts():
        def action(key, label, action):
            return Shortcut(key, label, lambda: app.dispatch_action(action))

        def step_with_follow(action_id):
            def run():
                disassembly_view.enable_follow()
                app.dispatch_action(action_id)

            return run

        step = Shortcut(
            curses.KEY_F0 + 5,
            "Step",
            step_with_follow(Actions.STEP),
        )
        step_vblank = Shortcut(
            curses.KEY_F0 + 6,
            "Step VBLANK",
            step_with_follow(Actions.STEP_VBLANK),
        )
        step_over = Shortcut(
            curses.KEY_F0 + 7,
            "Step over",
            step_with_follow(Actions.STEP_OVER),
        )
        pause = action(curses.KEY_F0 + 8, "Pause", Actions.PAUSE)
        cont = action(curses.KEY_F0 + 8, "Continue", Actions.CONTINUE)
        enter_shutdown = action(27, "Shutdown", Actions.ENTER_SHUTDOWN)
        exit_shutdown = action(27, "Back", Actions.EXIT_SHUTDOWN)

        normal = ShortcutLayer("NORMAL")
        normal.add(step)
        normal.add(step_vblank)
        normal.add(step_over)
        normal.add(pause)
        normal.add(enter_shutdown)

        debug = ShortcutLayer("DEBUG", color=Color.APPMODE_DEBUG)
        debug.add(step)
        debug.add(step_vblank)
        debug.add(step_over)
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

        def toggle_disassembly():
            if not wdisasm.visible:
                if state.disassembly_addr is None:
                    app.dispatch_action(
                        Actions.SET_DISASSEMBLY_ADDR, state.cpu.pc & 0xFFFF
                    )
                app.dispatch_action(Actions.SET_DISASSEMBLY, True)
                wdisasm.visible = True
                app.rebuild_screen()
            screen.focus(wdisasm)

        wdlist.add_hotkey("l", "DisplayList", lambda: screen.focus(wdlist))
        whistory.add_hotkey("h", "History", lambda: screen.focus(whistory))
        wscreen.add_hotkey("s", "Screen Buffer", lambda: screen.focus(wscreen))
        wwatch.add_hotkey("w", "Watchers", lambda: screen.focus(wwatch))
        wbreakpoints.add_hotkey(
            "b",
            "Breakpoints",
            lambda: screen.focus(wbreakpoints),
        )
        wdisasm.add_hotkey("d", "Disassembly", toggle_disassembly)
        shortcuts.add_global(
            Shortcut(
                9,
                "Next window",
                screen.focus_next,
                visible_in_global_bar=False,
            )
        )
        shortcuts.add_global(
            Shortcut(
                curses.KEY_BTAB,
                "Previous window",
                screen.focus_prev,
                visible_in_global_bar=False,
            )
        )
        shortcuts.add_global(action(curses.KEY_F0 + 9, "Freeze", Actions.TOGGLE_FREEZE))
        shortcuts.add_global(action("q", "Quit", Actions.QUIT))

    shortcuts_component = ShortcutsComponent(screen.shortcuts)
    app.add_component(dispatcher)
    app.add_component(cpu)
    app.add_component(disassembly_view)
    app.add_component(watchers_view)
    app.add_component(breakpoints_view)
    app.add_component(shortcuts_component)
    app.add_component(topbar)
    app.add_component(appmode_updater)
    app.add_component(shortcutbar)
    app.add_component(display_list)
    app.add_component(screen_inspector)
    app.add_component(history_view)

    build_shortcuts()
    await app.loop()


def run(socket_path):
    try:
        curses.wrapper(lambda scr: asyncio.run(main(scr, socket_path)))
    except KeyboardInterrupt:
        pass
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
        try:
            curses.endwin()
        except curses.error:
            pass
        debug.print_log()
