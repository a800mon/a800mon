import time

from .app import RpcComponent
from .appstate import state
from .datastructures import DisplayList, DisplayListEntry
from .rpc import RpcException
from .ui import Color

DMACTL_ADDR = 0x022F
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
        if w == 1:
            return 32
        if w == 2:
            return 40
        if w == 3:
            return 48
        return 0

    def _bytes_per_line(self, mode, width_bytes):
        if mode in (0, 1):
            return 0
        if mode in (6, 7):
            return width_bytes // 2
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

            n = self._bytes_per_line(mode, width)
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

            n = self._bytes_per_line(mode, width)
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
                # row_slices.append(None)
                continue
            row_slices.append((addr, length))

        return fetch, row_slices


class DisplayListViewer(RpcComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_update = None

    def update(self):
        if self._last_update and time.time() - self._last_update < 0.1:
            return
        try:
            start_addr = self.rpc.read_vector(DLPTRS_ADDR)
            dump = self.rpc.read_display_list()
        except RpcException:
            return
        else:
            state.dlist = decode_displaylist(start_addr, dump)

    def render(self, force_redraw=False):
        entries = (
            (
                (f"{entry.addr:04X}:", f" {count}x {entry.description}")
                if count > 1
                else (f"{entry.addr:04X}:", f" {entry.description}")
            )
            for count, entry in state.dlist.compacted_entries()
        )
        for addr, desc in entries:
            self.window.print(addr, attr=Color.ADDRESS.attr())
            self.window.print(desc)
            self.window.clear_to_eol()
            self.window.newline()
        # self.window.print_lines(entries)
        self.window.clear_to_bottom()
