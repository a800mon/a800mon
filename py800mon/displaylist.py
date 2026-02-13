from .app import VisualRpcComponent
from .actions import Actions
from .appstate import state
from .datastructures import DisplayList, DisplayListEntry
from .rpc import RpcException
from .ui import Color, GridWidget

DMACTL_ADDR = 0x022F
DMACTL_HW_ADDR = 0xD400
DLPTRS_ADDR = 0x0230


def decode_displaylist(start_addr: int, data: bytes):
    entries = []
    pc = 0
    while pc < len(data):
        addr = start_addr + pc
        ir = data[pc]
        pc += 1

        cmd = ir & 0x0F
        arg = 0

        if cmd == 1:
            if pc + 1 >= len(data):
                break
            arg = data[pc] | (data[pc + 1] << 8)
            pc += 2
        elif cmd != 0 and (ir & 0x40):
            if pc + 1 >= len(data):
                break
            arg = data[pc] | (data[pc + 1] << 8)
            pc += 2

        entries.append(DisplayListEntry(addr, ir, arg))
        if cmd == 1 and (ir & 0x40):
            break  # JVB kończy listę

    return DisplayList(start_addr, entries)


class DisplayListMemoryMapper:
    def __init__(self, dlist, dmactl, max_read=4096):
        self.dlist = dlist
        self.dmactl = dmactl
        self.max_read = max_read

    def _width_bytes(self):
        w = self.dmactl & 0x03
        if w == 0:
            return 40
        if w == 1:
            return 32
        if w == 2:
            return 40
        if w == 3:
            return 48
        return 0

    def _hscrol_width_bytes(self, width_bytes):
        if width_bytes <= 32:
            return 40
        if width_bytes <= 40:
            return 48
        return 48

    def _bytes_per_line(self, mode, width_bytes):
        if mode in (0, 1):
            return 0
        if mode in (2, 3, 4, 5, 0xD, 0xE, 0xF):
            return width_bytes
        if mode in (6, 7, 0xA, 0xB, 0xC):
            return width_bytes // 2
        if mode in (8, 9):
            return width_bytes // 4
        return width_bytes

    def bytes_per_line(self, mode):
        return self._bytes_per_line(mode, self._width_bytes())

    def row_ranges(self):
        width = self._width_bytes()
        addr = None
        rows = []

        for e in self.dlist.entries:
            ir = e.command
            mode = ir & 0x0F

            if mode == 0:
                count = ((ir >> 4) & 0x07) + 1
                rows.extend([(None, 0)] * count)
                continue

            if mode == 1:
                if ir & 0x40:
                    break
                continue

            if ir & 0x40:
                addr = e.arg

            if addr is None:
                continue

            line_width = width
            if ir & 0x10:
                line_width = self._hscrol_width_bytes(width)
            n = self._bytes_per_line(mode, line_width)
            rows.append((addr, n))
            addr = (addr + n) & 0xFFFF

        return rows

    def row_ranges_with_modes(self):
        width = self._width_bytes()
        addr = None
        rows = []

        for e in self.dlist.entries:
            ir = e.command
            mode = ir & 0x0F

            if mode == 0:
                continue

            if mode == 1:
                if ir & 0x40:
                    break
                continue

            if ir & 0x40:
                addr = e.arg

            if addr is None:
                continue

            line_width = width
            if ir & 0x10:
                line_width = self._hscrol_width_bytes(width)
            n = self._bytes_per_line(mode, line_width)
            rows.append((addr, n, mode))
            addr = (addr + n) & 0xFFFF

        return rows

    def plan(self):
        rows = self.row_ranges()

        segs = []
        for addr, length in rows:
            if addr is None or length == 0:
                continue
            end = addr + length
            if end <= 0x10000:
                segs.append((addr, end))
            else:
                segs.append((addr, 0x10000))
                segs.append((0, end & 0xFFFF))

        if not segs:
            return [], [None] * len(rows)

        segs.sort()
        merged = []
        cur_s, cur_e = segs[0]
        for s, e in segs[1:]:
            if s <= cur_e:
                if e > cur_e:
                    cur_e = e
            else:
                merged.append((cur_s, cur_e))
                cur_s, cur_e = s, e
        merged.append((cur_s, cur_e))

        fetch = []
        for s, e in merged:
            while s < e:
                chunk_end = min(e, s + self.max_read)
                fetch.append((s, chunk_end))
                s = chunk_end

        row_slices = []
        for addr, length in rows:
            if addr is None or length == 0:
                continue
            row_slices.append((addr, length))

        return fetch, row_slices


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
        self._render_grid()

    def _render_grid(self):
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
