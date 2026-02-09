import curses
import dataclasses
import enum
import io
import os
import socket
import struct
import sys
import time
import typing

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect("/tmp/atari.sock")

DEBUGLOG = []


def debug(txt):
    DEBUGLOG.append(txt)


@dataclasses.dataclass(frozen=True, slots=True)
class ScreenBufferCell:
    addr: int  # adres w Twoim buforze (np. 0x3800 + offset)
    value: int  # bajt 0..255 (wartość "ekranowa" / ATASCII / to co trzymasz)
    x: int
    y: int

    def as_int(self) -> int:
        return self.value

    def as_ascii(self) -> str:
        # Minimalnie: klasyczne 7-bit ASCII (kontrola -> '.')
        v = self.value & 0x7F
        if 32 <= v <= 126:
            return chr(v)
        return "."

    def as_atascii(self) -> int:
        # Zwraca "surową" wartość ATASCII (jak trzymasz w buforze)
        return self.value & 0xFF

    def as_atascii_char(self) -> str:
        # Jeśli masz własne mapowanie ATASCII->Unicode, podepnij je tutaj.
        # Domyślnie: ASCII z maską 0x7F.
        return self.as_ascii()


class ScreenBufferInspector:
    """
    Warstwa inspekcji/edycji nad Window.
    - przechowuje stan inspect on/off
    - trzyma kursor (x,y)
    - potrafi odwrócić atrybut w bieżącej komórce (inverse)
    - wystawia property .cell (addr, value + helpery)
    """

    def __init__(
        self,
        win,  # Window
    ):
        self.win = win

        self._inspect = False
        self._cx = 0
        self._cy = 0

        # przechowywanie “co było pod kursorem” żeby zdjąć inverse poprawnie
        self._saved_ch: typing.Optional[int] = None
        self._saved_attr: typing.Optional[int] = None
        self._saved_x: typing.Optional[int] = None
        self._saved_y: typing.Optional[int] = None

    @property
    def cols(self):
        return self.win.w

    @property
    def rows(self):
        return self.win.h

    def toggle_inspect(self) -> bool:
        self._inspect = not self._inspect
        return self._inspect

    def set_cursor(self, x: int, y: int) -> None:
        x = int(x)
        y = int(y)

        if self.cols <= 0 or self.rows <= 0:
            return

        # clamp
        if x < 0:
            x = 0
        elif x >= self.cols:
            x = self.cols - 1

        if y < 0:
            y = 0
        elif y >= self.rows:
            y = self.rows - 1

        self._cx = x
        self._cy = y

    def cursor_left(self, n: int = 1) -> None:
        self.set_cursor(self._cx - int(n), self._cy)

    def cursor_right(self, n: int = 1) -> None:
        self.set_cursor(self._cx + int(n), self._cy)

    def cursor_up(self, n: int = 1) -> None:
        self.set_cursor(self._cx, self._cy - int(n))

    def cursor_down(self, n: int = 1) -> None:
        self.set_cursor(self._cx, self._cy + int(n))

    def is_inspecting(self) -> bool:
        return self._inspect

    @property
    def cursor(self) -> tuple[int, int]:
        return self._cx, self._cy

    @property
    def cell(self) -> ScreenBufferCell:
        val = self.win.get_char(self._cx, self._cy) & 0xFF
        return ScreenBufferCell(addr=None, value=val, x=self._cx, y=self._cy)

    def put_value(self, value: int) -> None:
        """
        Zmiana wartości w emulowanym buforze (jeśli podasz set_byte_at),
        oraz aktualizacja wizualna w oknie (put_char).
        """
        self.win.put_char(self._cx, self._cy, value)

    def refresh(self) -> None:
        """
        Wywołuj po każdym odrysowaniu/aktualizacji okna Screen Buffer.
        Nakłada wizualny kursor przez zanegowanie A_REVERSE w komórce kursora.
        """
        if not self._inspect:
            return
        self.win.invert_char(self._cx, self._cy)


class Window:
    def __init__(self, parent, x, y, w, h, title=None):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self._iw = 0
        self._ih = 0
        self.title = title
        self.parent = parent
        self.initialize()

    def initialize(self):
        ph, pw = self.parent.getmaxyx()
        rw = min(pw - self.x, self.w)
        rh = min(ph - self.y, self.h)
        self.outer = self.parent.subwin(rh, rw, self.y, self.x)
        self.inner = self.outer.derwin(rh - 2, rw - 2, 1, 1)
        self._ih, self._iw = self.inner.getmaxyx()
        self.redraw()

    @property
    def cursor(self):
        y, x = self.inner.getyx()
        return x, y

    @cursor.setter
    def cursor(self, v):
        self.inner.move(v[1], v[0])

    def get_char(self, x, y):
        v = self.inner.inch(y, x)
        ch = v & 0xFF
        attr = v & ~0xFF
        return ch, attr

    def put_char(self, x, y, c, attr=0):
        win = self.inner
        cy, cx = win.getyx()
        win.addch(y, x, c, attr)
        win.move(cy, cx)

    def invert_char(self, x: int, y: int) -> None:
        cy, cx = self.inner.getyx()

        v = self.inner.inch(y, x)
        attr = v & curses.A_ATTRIBUTES

        if attr & curses.A_REVERSE:
            new_attr = attr & ~curses.A_REVERSE
        else:
            new_attr = attr | curses.A_REVERSE

        self.inner.chgat(y, x, 1, new_attr)
        self.inner.move(cy, cx)

    def redraw(self):
        self.outer.box()
        if self.title:
            self.outer.addstr(0, 2, self.title[: self.w - 4])
        self.dirty = True

    def reshape(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.initialize()
        self.redraw()

    def move(self, x, y):
        self.outer.mvwin(y, x)
        self.x = x
        self.y = y

    def erase(self):
        self.inner.erase()
        self.dirty = True
        self.cursor = (0, 0)

    def refresh(self):
        self.outer.noutrefresh()
        self.inner.noutrefresh()
        self.dirty = False
        self.cursor = (0, 0)

    def refresh_if_dirty(self):
        if self.dirty:
            self.refresh()

    def print_char(self, char, attr=0, wrap=False):
        cx, cy = self.cursor
        nx = cx + 1
        if not wrap and nx > self._iw - 1:
            return
        self.inner.addch(char, attr)
        if nx == self._iw - 1:
            self.newline()

    def print(self, text, attr=0, wrap=False):
        self.dirty = True
        text = str(text)
        tl = len(text)
        iw, ih = self._iw, self._ih
        cx, cy = self.cursor

        c = 0
        while c < tl and cy < ih:
            cut = min(iw - cx - 1, tl)
            if cut == 0:
                break
            ctxt = text[c : cut + c]
            self.inner.addstr(cy, cx, ctxt, attr)
            cx += cut
            if cx == iw - 1:
                cx = 0
                if cy < ih - 1:
                    cy += 1
                else:
                    break
            if not wrap:
                break
            c += cut

        self.inner.move(cy, cx)

    def print_line(self, text, attr=0, wrap=False):
        self.print(text=text, attr=attr, wrap=wrap)
        self.newline()

    def newline(self):
        cx, cy = self.cursor
        if cy < self._ih - 1:
            self.cursor = 0, cy + 1
        else:
            self.cursor = self._iw - 1, self._ih - 1

    def print_lines(self, lines, attr=0, wrap=False):
        for line in lines:
            cx, cy = self.cursor
            if cy == self.h:
                break
            self.print_line(line, attr=attr, wrap=wrap)
            self.inner.clrtoeol()

    def clear_to_end(self):
        self.inner.clrtobot()
        self.dirty = True

    def __repr__(self):
        return f"<Window title={self.title} w={self.w} h={self.h}>"


DMACTL_ADDR = 0x022F


def rpc_read_vector(addr):
    ptr = rpc(Command.MEM_READ, struct.pack("<HH", addr, 2))
    return ptr[0] | (ptr[1] << 8)


def rpc_read_memory(addr, length):
    return rpc(Command.MEM_READ, struct.pack("<HH", addr, length))


def rpc_read_dmactl():
    data = rpc(Command.MEM_READ, struct.pack("<HH", DMACTL_ADDR, 1))
    return data[0]


def rpc_cpu():
    data = rpc(Command.CPU_STATE)
    ypos, xpos, pc, a, x, y, s, p = struct.unpack("<HHHBBBBB", data)
    return CpuState(ypos=ypos, xpos=xpos, pc=pc, a=a, x=x, y=y, s=s, p=p)


def win_draw_row(win, y, x, row, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y > h - 2:
        return
    max_cols = w - x - 1
    if max_cols < 0 or max_cols > w - 1:
        return
    win.addstr(y, x, row, attr)


@dataclasses.dataclass
class CpuState:
    xpos: int
    ypos: int
    pc: int
    a: int
    x: int
    y: int
    s: int
    p: int

    N_FLAG = 0x80
    V_FLAG = 0x40
    D_FLAG = 0x08
    I_FLAG = 0x04
    Z_FLAG = 0x02
    C_FLAG = 0x01

    def __repr__(self) -> str:
        n = "N" if (self.p & self.N_FLAG) else "-"
        v = "V" if (self.p & self.V_FLAG) else "-"
        d = "D" if (self.p & self.D_FLAG) else "-"
        i = "I" if (self.p & self.I_FLAG) else "-"
        z = "Z" if (self.p & self.Z_FLAG) else "-"
        c = "C" if (self.p & self.C_FLAG) else "-"
        return (
            f"{self.ypos:3d} {self.xpos:3d} A={self.a:02X} X={self.x:02X} "
            f"Y={self.y:02X} S={self.s:02X} P={n}{v}*-{d}{i}{z}{c} "
            f"PC={self.pc:04X}"
        )


class Command(enum.IntEnum):
    PING = 1
    DLIST_ADDR = 2
    DLIST_DUMP = 4
    MEM_READ = 3
    CPU_STATE = 5
    PAUSE = 6
    CONTINUE = 7
    STEP = 8
    STEP_VBLANK = 9
    STATUS = 10


def clrscr():
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()


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

        map_segs = []
        offset = 0
        for s, e in fetch:
            map_segs.append((s, e, offset))
            offset += e - s

        row_slices = []
        for addr, length in rows:
            if addr is None or length == 0:
                # row_slices.append(None)
                continue
            for s, e, off in map_segs:
                if s <= addr and addr + length <= e:
                    start = off + (addr - s)
                    row_slices.append((slice(start, start + length), addr))
                    break
            else:
                # row_slices.append(None)
                pass

        return fetch, row_slices


class DisplayListEntry:
    def __init__(self, addr: int, command: int, arg: int):
        self.addr = addr
        self.command = command
        self.arg = arg

    def __eq__(self, other):
        if not isinstance(other, DisplayListEntry):
            return NotImplemented
        return (self.command, self.arg) == (other.command, other.arg)

    @property
    def is_dli(self):
        return bool(self.command & 0x80)

    @property
    def mode(self):
        return self.command & 0x0F

    @property
    def command_name(self):
        if self.mode == 0:
            return "BLANK"
        elif self.mode == 1:
            if self.command & 0x40:
                return "JVB"
            else:
                return "JMP"
        else:
            return f"MODE {self.mode}"

    @property
    def description(self):
        textcommand = ""
        dli_prefix = "DLI " if self.is_dli else ""
        count = 1

        if self.mode == 0:
            count = ((self.command >> 4) & 0x07) + 1
            textcommand = f"{count} {self.command_name}"
        elif self.mode == 1:
            textcommand = f"{self.command_name} {self.arg:04X}"
        else:
            parts = []
            if self.command & 0x40:
                parts.append(f"LMS {self.arg:04X}")
            if self.command & 0x20:
                parts.append("VSCROL")
            if self.command & 0x10:
                parts.append("HSCROL")
            parts.append(self.command_name)
            textcommand = " ".join(parts)
        return f"{dli_prefix}{textcommand}"

    def __repr__(self):
        return f"<{self.addr:04X}: {self.description}>"


ATASCII = [
    "\u2665",
    "\u2523",
    "\u2503",
    "\u251b",
    "\u252b",
    "\u2513",
    "\u2571",
    "\u2572",
    "\u25e2",
    "\u25d7",
    "\u25e3",
    "\u25dd",
    "\u25d8",
    "\u25d4",
    "\u2581",
    "\u25d6",
    "\u2663",
    "\u250f",
    "\u2501",
    "\u254b",
    "\u2b24",
    "\u2584",
    "\u258e",
    "\u2533",
    "\u253b",
    "\u258c",
    "\u2517",
    "\u241b",
    "\u2191",
    "\u2193",
    "\u2190",
    "\u2192",
    " ",
    "!",
    '"',
    "#",
    "$",
    "%",
    "&",
    "'",
    "(",
    ")",
    "*",
    "+",
    ",",
    "-",
    ".",
    "/",
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    ":",
    ";",
    "<",
    "=",
    ">",
    "?",
    "@",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
    "Z",
    "[",
    "\\",
    "]",
    "^",
    "_",
    "\u25c6",
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
    "i",
    "j",
    "k",
    "l",
    "m",
    "n",
    "o",
    "p",
    "q",
    "r",
    "s",
    "t",
    "u",
    "v",
    "w",
    "x",
    "y",
    "z",
    "\u2660",
    "|",
    "\u21b0",
    "\u25c0",
    "\u25b6",
]


def screen_to_atascii(b):
    c = b & 0x7F
    if c < 64:
        c += 32
    elif c < 96:
        c -= 64
    return c | (b & 0x80)


def atascii_chr(a):
    inv = a & 0x80
    ch = ATASCII[a & 0x7F]  # Twoja mapa ATASCII->UTF8
    attr = curses.A_REVERSE if inv else 0
    return ch, attr


class DisplayList:
    def __init__(self, start_addr: int, entries: typing.List[DisplayListEntry]):
        self.entries = entries
        self.start_addr = start_addr

    def compacted_entries(self):
        if not self.entries:
            raise StopIteration

        run = self.entries[0]
        count = 1

        for e in self.entries[1:]:
            if e == run:
                count += 1
                continue
            yield (count, run)
            run = e
            count = 1

        prefix = f"{count}x " if count > 1 else ""
        yield (count, run)

    def __iter__(self):
        return iter(self.entries)

    @classmethod
    def decode(cls, start_addr: int, data: bytes):
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

        return cls(start_addr, entries)


class RpcError(Exception):
    pass


def rpc(cmd, payload=b""):
    s.sendall(bytes([cmd]) + struct.pack("<H", len(payload)) + payload)
    hdr = s.recv(3)
    status, ln = hdr[0], hdr[1] | (hdr[2] << 8)
    if status == 0:
        data = b""
        while len(data) < ln:
            data += s.recv(ln - len(data))
        return data
    else:
        raise RpcError


def main(scr):
    scr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    curses.curs_set(0)

    scr.nodelay(True)
    scr.keypad(True)

    h, w = scr.getmaxyx()

    wcpu = Window(scr, x=0, y=h - 5, w=w, h=4, title="CPU State")
    wdlist = Window(scr, x=0, y=0, w=40, h=wcpu.y - 1, title="DisplayList")
    wscreen = Window(
        scr,
        x=wdlist.w + wdlist.x + 2,
        y=0,
        w=60,
        h=wcpu.y - 1,
        title="Screen Buffer (ATASCII)",
    )

    def init_screen():
        h, w = scr.getmaxyx()
        scr.erase()

        wcpu.reshape(x=0, y=h - 5, w=w, h=3)
        wdlist.reshape(x=0, y=0, w=40, h=wcpu.y - 1)
        wscreen.reshape(x=wdlist.x + wdlist.w + 2, y=0, w=60, h=wcpu.y - 1)

        scr.refresh()
        wdlist.refresh()
        wscreen.refresh()
        wcpu.refresh()

    init_screen()
    inspector = ScreenBufferInspector(wscreen)

    last_mem = []

    while True:
        start_time = time.time()
        try:
            cpu = rpc_cpu()
        except RpcError:
            cpu = None
        try:
            ptr = rpc(Command.DLIST_ADDR)
        except RpcError:
            dlist = None
        else:
            start = ptr[0] | (ptr[1] << 8)
            try:
                dlist = DisplayList.decode(start, rpc(Command.DLIST_DUMP))
            except RpcError:
                dlist = None

        if dlist:
            entries = (
                (
                    f"{entry.addr:04X}: {count}x {entry.description}"
                    if count > 1
                    else f"{entry.addr:04X}: {entry.description}"
                )
                for count, entry in dlist.compacted_entries()
            )
            wdlist.print_lines(entries)

        if dlist:
            dmactl = rpc_read_dmactl()
            fetch_ranges, row_slices = DisplayListMemoryMapper(dlist, dmactl).plan()
            screen_buf = b"".join(rpc_read_memory(s, e - s) for s, e in fetch_ranges)

            for rownum, row_info in enumerate(row_slices):
                if not row_info:
                    continue
                if isinstance(row_info, tuple):
                    slice_, start_addr = row_info
                else:
                    slice_ = row_info
                    start_addr = fetch_ranges[0][0] + slice_.start
                row = screen_buf[slice_][: wscreen.w]
                wscreen.print(f"{start_addr:04X}: ")
                for i, b in enumerate(row):
                    ac, attr = atascii_chr(screen_to_atascii(b)) if b > 0 else (" ", 0)
                    wscreen.print_char(ac, attr=attr)
                wscreen.newline()

        if cpu:
            wcpu.print(repr(cpu))

        wscreen.clear_to_end()
        wdlist.clear_to_end()
        wcpu.clear_to_end()

        inspector.refresh()

        wscreen.refresh()
        wdlist.refresh()
        wcpu.refresh()

        curses.doupdate()

        ch = scr.getch()
        if ch in (ord("q"), 27):
            break
        if ch == curses.KEY_RESIZE:
            init_screen()
        if ch == ord("i"):
            inspector.toggle_inspect()
        if inspector.is_inspecting():
            if ch == ord("l"):
                inspector.cursor_right()
            if ch == ord("h"):
                inspector.cursor_left()
            if ch == ord("j"):
                inspector.cursor_down()
            if ch == ord("k"):
                inspector.cursor_up()
        if ch == ord("p"):
            rpc(Command.PAUSE)
        if ch == ord("s"):
            rpc(Command.STEP)
        if ch == ord("v"):
            rpc(Command.STEP_VBLANK)
        if ch == ord("c"):
            rpc(Command.CONTINUE)

        time_diff = time.time() - start_time
        sleep_time = 0.1 - time_diff
        if sleep_time > 0:
            time.sleep(sleep_time)


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
        if DEBUGLOG:
            for line in DEBUGLOG:
                print(line)
