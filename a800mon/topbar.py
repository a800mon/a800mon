from .app import VisualRpcComponent
from .appstate import state
from .rpc import RpcException
from .ui import Color


class TopBar(VisualRpcComponent):
    def __init__(self, *args, status_hook=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._dirty = True
        self._last_rpc_error = None
        self._status_hook = status_hook

    def render(self, force_redraw=False):
        if not self._last_rpc_error == self.rpc.last_error:
            self._dirty = True
            self._last_rpc_error = self.rpc.last_error

        if self._dirty or force_redraw:
            self.window.cursor = 0, 0
            if self._last_rpc_error:
                self.window.print("Atari800 Monitor ", Color.TOPBAR.attr())
                self.window.print(f" {str(self._last_rpc_error)} ", Color.ERROR.attr())
                self.window.fill_to_eol(attr=Color.ERROR.attr())
            else:
                self.window.print(
                    "Atari800 Monitor    (c) 2026 Marcin Nowak", Color.TOPBAR.attr()
                )
                self.window.fill_to_eol(attr=Color.TOPBAR.attr())
            self._dirty = False

        emu_hms = _format_hms(state.emu_ms)
        reset_hms = _format_hms(state.reset_ms)
        frame = f"{state.monitor_frame_time_ms:3d} ms"
        inv_attr = Color.TOPBAR.attr()
        segments = []
        if getattr(state, "crashed", False):
            segments.append((" CRASH ", Color.ERROR.attr()))
        segments += [
            (" UP ", 0),
            (f" {emu_hms} ", inv_attr),
            ("  ", inv_attr),
            (" RS ", 0),
            (f" {reset_hms} ", inv_attr),
            (f" {frame} ", 0),
        ]
        total_len = sum(len(text) for text, _ in segments)
        width = self.window._iw
        if total_len > width:
            cut = total_len - width
            trimmed = []
            for text, attr in segments:
                if cut <= 0:
                    trimmed.append((text, attr))
                    continue
                if cut >= len(text):
                    cut -= len(text)
                    continue
                trimmed.append((text[cut:], attr))
                cut = 0
            segments = trimmed
            total_len = sum(len(text) for text, _ in segments)
        self.window.cursor = max(width - total_len, 0), 0
        for text, attr in segments:
            if attr:
                self.window.print(text, attr=attr)
            else:
                self.window.print(text)

    def update(self):
        try:
            status = self.rpc.status()
        except RpcException:
            return
        state.paused = status.paused
        state.emu_ms = status.emu_ms
        state.reset_ms = status.reset_ms
        state.crashed = status.crashed
        if self._status_hook:
            self._status_hook(state.paused)


def _format_hms(ms):
    total = max(0, int(ms // 1000))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
