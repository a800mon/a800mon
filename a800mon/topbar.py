from .app import RpcComponent
from .ui import Color


class TopBar(RpcComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dirty = True
        self._last_rpc_error = None

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
