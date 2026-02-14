import asyncio
import os
import sys

from ..datastructures import CpuState
from ..atari.memory import dump_memory_human, dump_memory_json, dump_memory_raw
from ..rpc import CommandError, RpcClient
from ..socket import SocketTransport

EMULATOR_CAPABILITIES = [
    (0x0001, "SDL2 video backend (VIDEO_SDL2)"),
    (0x0002, "SDL1 video backend (VIDEO_SDL)"),
    (0x0003, "Sound support (SOUND)"),
    (0x0004, "Callback sound backend (SOUND_CALLBACK)"),
    (0x0005, "Audio recording (AUDIO_RECORDING)"),
    (0x0006, "Video recording (VIDEO_RECORDING)"),
    (0x0007, "Code breakpoints/history (MONITOR_BREAK)"),
    (0x0008, "User breakpoint table (MONITOR_BREAKPOINTS)"),
    (0x0009, "Readline monitor support (MONITOR_READLINE)"),
    (0x000A, "Disassembler label hints (MONITOR_HINTS)"),
    (0x000B, "UTF-8 monitor output (MONITOR_UTF8)"),
    (0x000C, "ANSI monitor output (MONITOR_ANSI)"),
    (0x000D, "Monitor assembler command (MONITOR_ASSEMBLER)"),
    (0x000E, "Monitor profiling/coverage (MONITOR_PROFILE)"),
    (0x000F, "Monitor TRACE command (MONITOR_TRACE)"),
    (0x0010, "NetSIO/FujiNet emulation (NETSIO)"),
    (0x0011, "IDE emulation (IDE)"),
    (0x0012, "R: device support (R_IO_DEVICE)"),
    (0x0013, "Black Box emulation (PBI_BB)"),
    (0x0014, "MIO emulation (PBI_MIO)"),
    (0x0015, "Prototype80 emulation (PBI_PROTO80)"),
    (0x0016, "1400XL/1450XLD emulation (PBI_XLD)"),
    (0x0017, "VoiceBox emulation (VOICEBOX)"),
    (0x0018, "AF80 card emulation (AF80)"),
    (0x0019, "BIT3 card emulation (BIT3)"),
    (0x001A, "XEP80 emulation (XEP80_EMULATION)"),
    (0x001B, "NTSC filter (NTSC_FILTER)"),
    (0x001C, "PAL blending (PAL_BLENDING)"),
    (0x001D, "Crash menu support (CRASH_MENU)"),
    (0x001E, "New cycle-exact core (NEW_CYCLE_EXACT)"),
    (0x001F, "libpng support (HAVE_LIBPNG)"),
    (0x0020, "zlib support (HAVE_LIBZ)"),
]

SET_REG_TARGETS = {
    "pc": 1,
    "a": 2,
    "x": 3,
    "y": 4,
    "s": 5,
    "n": 6,
    "v": 7,
    "d": 8,
    "i": 9,
    "z": 10,
    "c": 11,
}

SEARCH_MODE_BYTES = 1


def rpc_client(socket_path):
    return RpcClient(SocketTransport(socket_path))


def async_to_sync(awaitable):
    return asyncio.run(awaitable)


async def print_cpu_state(rpc):
    ypos, xpos, pc, a, x, y, s, p = await rpc.cpu_state()
    cpu = CpuState(ypos=ypos, xpos=xpos, pc=pc, a=a, x=x, y=y, s=s, p=p)
    sys.stdout.write(repr(cpu) + "\n")


def parse_bool(value):
    text = value.strip().lower()
    if text in ("1", "on", "true", "yes"):
        return True
    if text in ("0", "off", "false", "no"):
        return False
    raise SystemExit(f"Invalid boolean value: {value}")


def fmt_bytes(values):
    return " ".join(f"{value:02X}" for value in values)


def cli_color_enabled():
    color_mode = os.getenv("A800MON_COLOR", "").strip().lower()
    term = os.getenv("TERM", "")
    if color_mode == "always":
        return True
    if color_mode == "never":
        return False
    return term not in (None, "", "dumb")


def format_on_off_badge(enabled: bool) -> str:
    text = "ON " if enabled else "OFF"
    badge = f" {text} "
    if not cli_color_enabled():
        return badge
    if enabled:
        return f"\x1b[42;30m{badge}\x1b[0m"
    return f"\x1b[41;97;1m{badge}\x1b[0m"


def format_rpc_exception(ex):
    if isinstance(ex, CommandError):
        code = str(ex.status)
        msg = ex.data.decode("utf-8", errors="replace").strip() if ex.data else str(ex)
    else:
        code = "ERR"
        msg = str(ex)
    badge = f" {code} "
    if cli_color_enabled():
        return f"\x1b[41;97;1m{badge}\x1b[0m {msg}"
    return f"[{code}] {msg}"


def dump_memory_output(address, length, data, args, columns):
    if columns is not None and (args.raw or args.json):
        raise SystemExit("--columns is only valid for formatted output")

    if args.raw:
        raw = dump_memory_raw(data, use_atascii=args.atascii)
        if raw:
            sys.stdout.buffer.write(raw)
        return

    if args.json:
        sys.stdout.write(
            dump_memory_json(address, data, use_atascii=args.atascii) + "\n"
        )
        return

    sys.stdout.write(
        dump_memory_human(
            address=address,
            length=length,
            buffer=data,
            use_atascii=args.atascii,
            columns=columns,
            show_hex=not args.nohex,
            show_ascii=not args.noascii,
        )
        + "\n"
    )
