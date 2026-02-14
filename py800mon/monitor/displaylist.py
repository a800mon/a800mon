from ..actions import Actions
from ..app import VisualRpcComponent
from ..atari.displaylist import DLPTRS_ADDR, DMACTL_ADDR, DMACTL_HW_ADDR, decode_displaylist
from ..rpc import RpcException
from ..ui import Color, GridWidget
from .appstate import state


class DisplayListViewer(VisualRpcComponent):
    def __init__(self, rpc, window):
        super().__init__(rpc, window)
        self.grid = GridWidget(window)
        self.grid.add_column("address", width=5, attr=Color.ADDRESS.attr())
        self.grid.add_column("description", width=0, attr=Color.TEXT.attr())
        self._dmactl = 0

    async def update(self):
        try:
            start_addr = await self.rpc.read_vector(DLPTRS_ADDR)
            dump = await self.rpc.read_display_list()
            dmactl = await self.rpc.read_byte(DMACTL_ADDR)
            if (dmactl & 0x03) == 0:
                dmactl = await self.rpc.read_byte(DMACTL_HW_ADDR)
        except RpcException:
            return False
        else:
            dlist = decode_displaylist(start_addr, dump)
            self.app.dispatch_action(Actions.SET_DLIST, (dlist, dmactl))
            self._dmactl = dmactl
            return True

    def render(self, force_redraw=False):
        rows = []
        for count, entry in state.dlist.compacted_entries():
            if count > 1:
                desc = f"{count}x {entry.description}"
            else:
                desc = entry.description
            rows.append((f"{entry.addr:04X}:", desc))
        self.grid.set_data(rows)
        if rows and self.grid.selected_row is None:
            self.grid.set_selected_row(0)
        self.grid.render()

    def handle_input(self, ch):
        return self.grid.handle_input(ch)
