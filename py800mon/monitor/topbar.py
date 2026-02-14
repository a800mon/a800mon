from ..app import Component, VisualComponent
from ..ui import Color
from .appstate import state

CRASH_LABEL = {
    True: (" CRASH ", Color.ERROR),
    False: ("       ", Color.TOPBAR),
}
TITLE = "Atari800 Monitor"
COPYTIGHT = "(c) 2026 Marcin Nowak"
TOPRIGHT_LEN = 43


class TopBar(VisualComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_snapshot = None

    async def update(self):
        snapshot = (
            state.last_rpc_error,
            state.crashed,
            state.emu_ms,
            state.reset_ms,
            state.monitor_frame_time_ms,
            state.ui_frozen,
        )
        if self._last_snapshot == snapshot:
            return False
        self._last_snapshot = snapshot
        return True

    def render(self, force_redraw=False):
        self.window.cursor = 0, 0
        if state.last_rpc_error:
            self.window.print(f"{TITLE} ", Color.TOPBAR.attr())
            self.window.print(f" {state.last_rpc_error} ", Color.ERROR.attr())
            self.window.fill_to_eol(attr=Color.ERROR.attr())
        else:
            self.window.print(f"{TITLE}     {COPYTIGHT}", Color.TOPBAR.attr())
            if state.ui_frozen:
                self.window.print("   ", Color.TOPBAR.attr())
                self.window.print(" FREEZE ", Color.ERROR.attr())
            self.window.fill_to_eol(attr=Color.TOPBAR.attr())

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


def _format_hms(ms):
    total = max(0, int(ms // 1000))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
