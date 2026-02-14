from ..app import Component, VisualComponent
from .appstate import state


class CpuStateViewer(VisualComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_snapshot = None

    async def update(self):
        snapshot = (state.cpu, state.cpu_disasm)
        if self._last_snapshot == snapshot:
            return False
        self._last_snapshot = snapshot
        return True

    def render(self, force_redraw=False):
        line = repr(state.cpu)
        if state.cpu_disasm:
            line += f"  {state.cpu_disasm}"
        self.window.print(line)
        self.window.clear_to_eol()
