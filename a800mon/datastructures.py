import dataclasses
import typing

from .atascii import ATASCII, screen_to_atascii


@dataclasses.dataclass
class CpuState:
    xpos: int = 0
    ypos: int = 0
    pc: int = 0
    a: int = 0
    x: int = 0
    y: int = 0
    s: int = 0
    p: int = 0

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


class DisplayList:
    def __init__(
        self, start_addr: int = 0, entries: typing.List[DisplayListEntry] = []
    ):
        self.entries = entries
        self.start_addr = start_addr

    def compacted_entries(self):
        if not self.entries:
            return

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


@dataclasses.dataclass
class ScreenBuffer:
    start_address: int = 0
    buffer: bytes = b""
    range_index: typing.List[typing.Tuple[int, int, int]] = dataclasses.field(
        default_factory=list
    )
    row_slices: typing.List[
        typing.Union[
            slice,
            typing.Tuple[slice, int],
            typing.Tuple[int, typing.List[slice]],
            typing.Tuple[int, int],
        ]
    ] = dataclasses.field(default_factory=list)

    def get_range(self, addr: int, length: int) -> bytes:
        if length <= 0 or not self.range_index:
            return b""
        addr &= 0xFFFF
        end = addr + length
        if end <= 0x10000:
            return self._get_range_linear(addr, length)
        first_len = 0x10000 - addr
        return self._get_range_linear(addr, first_len) + self._get_range_linear(
            0, length - first_len
        )

    def _get_range_linear(self, addr: int, length: int) -> bytes:
        if length <= 0:
            return b""
        end = addr + length
        parts = []
        remaining = length
        cur = addr
        while remaining > 0:
            for start, stop, offset in self.range_index:
                if start <= cur < stop:
                    take = min(remaining, stop - cur)
                    buf_start = offset + (cur - start)
                    parts.append(self.buffer[buf_start : buf_start + take])
                    cur += take
                    remaining -= take
                    break
            else:
                return b""
        return b"".join(parts)


@dataclasses.dataclass
class Memory:
    start: int
    length: int
    buffer: bytes

    BYTES_PER_LINE = 16

    def __repr__(self) -> str:
        return self.format()

    def format(
        self,
        use_atascii: bool = False,
        columns: int | None = None,
        show_hex: bool = True,
        show_ascii: bool = True,
    ) -> str:
        lines = []
        length = max(0, int(self.length))
        per_line = self.BYTES_PER_LINE
        if columns is not None:
            per_line = max(1, int(columns))
        for offset in range(0, length, per_line):
            addr = (self.start + offset) & 0xFFFF
            chunk = self.buffer[offset : offset + per_line]
            parts = [f"{addr:04X}:"]
            if show_hex:
                hex_width = per_line * 3 - 1
                hex_bytes = " ".join(f"{b:02X}" for b in chunk).ljust(hex_width)
                parts.append(hex_bytes)
            if show_ascii:
                if use_atascii:
                    ascii_bytes = "".join(
                        ATASCII[screen_to_atascii(b) & 0x7F] for b in chunk
                    )
                else:
                    ascii_bytes = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
                parts.append(ascii_bytes)
            lines.append("  ".join(parts))
        return "\n".join(lines)
