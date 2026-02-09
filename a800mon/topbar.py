import time

from .app import VisualRpcComponent
from .appstate import state, store
from .rpc import RpcException
from .ui import Color

CRASH_LABEL = {
    True: (" CRASH ", Color.ERROR),
    False: ("       ", Color.TOPBAR),
}
TITLE = "Atari800 Monitor"
COPYTIGHT = "(c) 2026 Marcin Nowak"
TOPRIGHT_LEN = 43


class TopBar(VisualRpcComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dirty = True
        self._last_rpc_error = None
        self._last_status_ts = 0.0

    def render(self, force_redraw=False):
        if not self._last_rpc_error == self.rpc.last_error:
            force_redraw = True
            self._last_rpc_error = self.rpc.last_error

        if force_redraw:
            self.window.cursor = 0, 0
            if self._last_rpc_error:
                self.window.print(f"{TITLE} ", Color.TOPBAR.attr())
                self.window.print(
                    f" {str(self._last_rpc_error)} ", Color.ERROR.attr())
                self.window.fill_to_eol(attr=Color.ERROR.attr())
            else:
                self.window.print(
                    f"{TITLE}     {COPYTIGHT}", Color.TOPBAR.attr())
                self.window.fill_to_eol(attr=Color.TOPBAR.attr())

        if self._dirty:
            segments = (
                CRASH_LABEL[state.crashed],
                (" UP ", Color.TEXT),
                (f" {_format_hms(state.emu_ms)} ", Color.TOPBAR),
                (" RS ", Color.TEXT),
                (f" {_format_hms(state.reset_ms)} ", Color.TOPBAR),
                (f" {state.monitor_frame_time_ms:3d} ms ", Color.TEXT),
            )
            self.window.cursor = (self.window._iw - TOPRIGHT_LEN, 0)
            for text, color in segments:
                self.window.print(text, attr=color.attr())

    def update(self):
        if self._last_status_ts and time.time() - self._last_status_ts < 0.5:
            return
        try:
            status = self.rpc.status()
        except RpcException:
            return
        store.set_status(status.paused, status.emu_ms, status.reset_ms, status.crashed)
        self._last_status_ts = time.time()
        self._changed = True


def _format_hms(ms):
    total = max(0, int(ms // 1000))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
