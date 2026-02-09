import curses

from . import debug
from .app import App
from .cpustate import CpuStateViewer
from .displaylist import DisplayListViewer
from .rpc import RpcClient
from .screenbuffer import ScreenBufferInspector
from .socket import SocketTransport
from .topbar import TopBar
from .ui import Screen, Window


def main(scr):
    wcpu = Window(title="CPU State")
    wdlist = Window(title="DisplayList")
    wscreen = Window(title="Screen Buffer (ATASCII)")
    top = Window(border=False)

    def init_screen(scr):
        w, h = scr.size
        wcpu.reshape(x=0, y=h - 5, w=w, h=3)
        wdlist.reshape(x=0, y=2, w=40, h=wcpu.y - 3)
        wscreen.reshape(x=wdlist.x + wdlist.w + 2, y=2, w=60, h=wcpu.y - 3)
        top.reshape(x=0, y=0, w=w, h=1)

    rpc = RpcClient(SocketTransport("/tmp/atari.sock"))

    screen_inspector = ScreenBufferInspector(rpc, wscreen)
    display_list = DisplayListViewer(rpc, wdlist)
    cpu = CpuStateViewer(rpc, wcpu)
    topbar = TopBar(rpc, top)

    scr = Screen(scr, layout_initializer=init_screen)
    app = App(screen=scr)
    app.add_component(topbar)
    app.add_component(cpu)
    app.add_component(display_list)
    app.add_component(screen_inspector)

    app.loop()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
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
