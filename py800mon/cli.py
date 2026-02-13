import argparse
import asyncio
import os
import struct
import sys

from .atascii import atascii_to_screen, text_to_atascii
from .datastructures import CpuState
from .disasm import disasm_6502, disasm_6502_one
from .displaylist import (DLPTRS_ADDR, DMACTL_ADDR, DMACTL_HW_ADDR,
                          DisplayListMemoryMapper, decode_displaylist)
from .main import run as run_monitor
from .memory import (
    dump_memory_human,
    dump_memory_human_rows,
    dump_memory_json,
    dump_memory_raw,
    parse_hex,
    parse_hex_payload,
    parse_hex_u8,
    parse_hex_values,
    parse_positive_int,
)
from .rpc import Command, CommandError, RpcClient, RpcException
from .socket import SocketTransport
from .trainer import Trainer

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

BP_CONDITION_TYPES = {
    "pc": 1,
    "a": 2,
    "x": 3,
    "y": 4,
    "s": 5,
    "read": 6,
    "write": 7,
    "access": 8,
}
BP_TYPE_NAMES = {
    1: "pc",
    2: "a",
    3: "x",
    4: "y",
    5: "s",
    6: "read",
    7: "write",
    8: "access",
    9: "mem",
}
BP_OPS = {
    "<": 1,
    "<=": 2,
    "=": 3,
    "==": 3,
    "!=": 4,
    ">=": 5,
    ">": 6,
}
BP_OP_NAMES = {
    1: "<",
    2: "<=",
    3: "==",
    4: "!=",
    5: ">=",
    6: ">",
}

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


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="py800mon")
    parser.add_argument(
        "-s",
        "--socket",
        default="/tmp/atari.sock",
        help="Path to Atari800 monitor socket.",
    )
    subparsers = parser.add_subparsers(dest="cmd", metavar="cmd")

    monitor = subparsers.add_parser(
        "monitor", help="Run the curses monitor UI.")
    monitor.set_defaults(func=_cmd_monitor)

    run = subparsers.add_parser("run", help="Run a file via RPC.")
    run.add_argument("path", help="Path to file.")
    run.set_defaults(func=_cmd_run)

    pause = subparsers.add_parser("pause", help="Pause emulation.")
    pause.set_defaults(func=_cmd_pause)

    step = subparsers.add_parser("step", help="Step one instruction.")
    step.set_defaults(func=_cmd_step)

    stepvbl = subparsers.add_parser("stepvbl", help="Step one VBLANK.")
    stepvbl.set_defaults(func=_cmd_step_vblank)

    stepover = subparsers.add_parser("stepover", help="Step over instruction.")
    stepover.add_argument(
        "pc",
        nargs="?",
        default=None,
        help="Optional PC address (hex: 0xNNNN, $NNNN, NNNN).",
    )
    stepover.set_defaults(func=_cmd_step_over)

    rununtilret = subparsers.add_parser(
        "rununtilret",
        help="Run until return from subroutine.",
    )
    rununtilret.add_argument(
        "pc",
        nargs="?",
        default=None,
        help="Optional PC address (hex: 0xNNNN, $NNNN, NNNN).",
    )
    rununtilret.set_defaults(func=_cmd_run_until_return)

    cont = subparsers.add_parser("continue", help="Continue emulation.")
    cont.set_defaults(func=_cmd_continue)

    coldstart = subparsers.add_parser(
        "coldstart", help="Cold start emulation.")
    coldstart.set_defaults(func=_cmd_coldstart)

    warmstart = subparsers.add_parser(
        "warmstart", help="Warm start emulation.")
    warmstart.set_defaults(func=_cmd_warmstart)

    removecartrige = subparsers.add_parser(
        "removecartrige", help="Remove cartridge.")
    removecartrige.set_defaults(func=_cmd_removecartrige)

    removetape = subparsers.add_parser("removetape", help="Remove cassette.")
    removetape.set_defaults(func=_cmd_removetape)

    removedisks = subparsers.add_parser(
        "removedisks", help="Remove all disks.")
    removedisks.set_defaults(func=_cmd_removedisks)

    dlist = subparsers.add_parser("dlist", help="Dump display list.")
    dlist.add_argument(
        "address",
        nargs="?",
        default=None,
        help="Optional display list start address (hex: 0xNNNN, $NNNN, NNNN).",
    )
    dlist.set_defaults(func=_cmd_dump_dlist)

    cpu = subparsers.add_parser("cpu", help="Show CPU state.")
    cpu.set_defaults(func=_cmd_cpustate)

    gtia = subparsers.add_parser("gtia", help="Show GTIA register state.")
    gtia.set_defaults(func=_cmd_gtia_state)

    antic = subparsers.add_parser("antic", help="Show ANTIC register state.")
    antic.set_defaults(func=_cmd_antic_state)

    cart = subparsers.add_parser("cart", help="Show cartridge state.")
    cart.set_defaults(func=_cmd_cart_state)

    jumps = subparsers.add_parser("jumps", help="Show jump history ring.")
    jumps.set_defaults(func=_cmd_jumps)

    pia = subparsers.add_parser("pia", help="Show PIA register state.")
    pia.set_defaults(func=_cmd_pia_state)

    pokey = subparsers.add_parser("pokey", help="Show POKEY register state.")
    pokey.set_defaults(func=_cmd_pokey_state)

    stack = subparsers.add_parser("stack", help="Show 6502 stack bytes.")
    stack.set_defaults(func=_cmd_stack)

    history = subparsers.add_parser(
        "history", help="Show CPU execution history.")
    history.add_argument(
        "-n",
        "--count",
        type=int,
        default=None,
        help="Limit output to last N entries.",
    )
    history.set_defaults(func=_cmd_history)

    emulator = subparsers.add_parser(
        "emulator",
        help="Emulator control commands.",
    )
    emulator_sub = emulator.add_subparsers(dest="emulator_cmd", metavar="subcmd")
    emulator_sub.required = True
    emulator_stop = emulator_sub.add_parser("stop", help="Stop emulator.")
    emulator_stop.set_defaults(func=_cmd_emulator_stop)
    emulator_restart = emulator_sub.add_parser("restart", help="Restart emulator.")
    emulator_restart.set_defaults(func=_cmd_emulator_restart)
    emulator_debug = emulator_sub.add_parser(
        "debug",
        help="Switch to emulator built-in monitor.",
    )
    emulator_debug.set_defaults(func=_cmd_emulator_debug)
    emulator_features = emulator_sub.add_parser(
        "features",
        help="Show emulator capability flags.",
    )
    emulator_features.set_defaults(func=_cmd_emulator_config)

    bp = subparsers.add_parser(
        "bp",
        aliases=["breakpoint"],
        help="Manage user breakpoints.",
    )
    bp_sub = bp.add_subparsers(dest="bp_cmd", metavar="subcmd")
    bp.set_defaults(func=_cmd_bp_list)

    bp_list = bp_sub.add_parser("ls", help="List user breakpoints.")
    bp_list.set_defaults(func=_cmd_bp_list)

    bp_add = bp_sub.add_parser(
        "add",
        help='Add one breakpoint clause (AND). Example: bp add pc==0x2000 a==0 mem[0xD20A]==0x0F',
    )
    bp_add.add_argument(
        "conditions",
        nargs="+",
        help="Conditions joined by AND in one clause.",
    )
    bp_add.set_defaults(func=_cmd_bp_add)

    bp_del = bp_sub.add_parser("del", help="Delete breakpoint clause by index (1-based).")
    bp_del.add_argument("index", type=int, help="Clause index (1-based).")
    bp_del.set_defaults(func=_cmd_bp_del)

    bp_clear = bp_sub.add_parser("clear", help="Clear all breakpoint clauses.")
    bp_clear.set_defaults(func=_cmd_bp_clear)

    bp_on = bp_sub.add_parser("on", help="Enable all user breakpoints.")
    bp_on.set_defaults(func=_cmd_bp_on)

    bp_off = bp_sub.add_parser("off", help="Disable all user breakpoints.")
    bp_off.set_defaults(func=_cmd_bp_off)

    bbrk = subparsers.add_parser("bbrk", help="Query/set break-on-BRK mode.")
    bbrk.add_argument(
        "enabled",
        nargs="?",
        default=None,
        help="Optional state: on/off/1/0.",
    )
    bbrk.set_defaults(func=_cmd_bbrk)

    bline = subparsers.add_parser("bline", help="Query/set scanline break value.")
    bline.add_argument(
        "scanline",
        nargs="?",
        default=None,
        help="Optional scanline (hex: 0xNNNN, $NNNN, NNNN).",
    )
    bline.set_defaults(func=_cmd_bline)

    trainer = subparsers.add_parser("trainer", help="Interactive value trainer.")
    trainer.add_argument("start", help="Start address (hex: 0xNNNN, $NNNN, NNNN).")
    trainer.add_argument("stop", help="Stop address (hex: 0xNNNN, $NNNN, NNNN).")
    trainer.add_argument("value", help="Initial byte value (hex: 00..FF).")
    trainer.set_defaults(func=_cmd_trainer)

    search = subparsers.add_parser("search", help="Search memory for a pattern.")
    search.add_argument(
        "-a",
        "--atascii",
        action="store_true",
        help="Convert input text to ATASCII bytes before search.",
    )
    search.add_argument(
        "-s",
        "--screen",
        action="store_true",
        help="Convert input text to screen-codes before search.",
    )
    search.add_argument("start", help="Start address (hex: 0xNNNN, $NNNN, NNNN).")
    search.add_argument("end", help="End address (hex: 0xNNNN, $NNNN, NNNN).")
    search.add_argument(
        "pattern",
        nargs="+",
        help="Hex bytes by default; text when -a and/or -s is used.",
    )
    search.set_defaults(func=_cmd_search)

    cpureg = subparsers.add_parser("cpureg", help="Set CPU register or flag.")
    cpureg.add_argument(
        "target",
        choices=sorted(SET_REG_TARGETS.keys()),
        help="Target register/flag.",
    )
    cpureg.add_argument("value", help="Value (hex: 0xNNNN, $NNNN, NNNN).")
    cpureg.set_defaults(func=_cmd_set_reg)

    status = subparsers.add_parser("status", help="Get status.")
    status.set_defaults(func=_cmd_status)

    ping = subparsers.add_parser("ping", help="Ping RPC server.")
    ping.set_defaults(func=_cmd_ping)

    readmem = subparsers.add_parser("readmem", help="Read memory.")
    readmem.add_argument("addr", help="Address (hex: 0xNNNN, $NNNN, NNNN).")
    readmem.add_argument("length", help="Length (hex: 0xNNNN, $NNNN, NNNN).")
    format_group = readmem.add_mutually_exclusive_group()
    format_group.add_argument(
        "--raw",
        action="store_true",
        help="Output raw bytes without formatting.",
    )
    format_group.add_argument(
        "--json",
        action="store_true",
        help="Output JSON with address and buffer.",
    )
    readmem.add_argument(
        "-a",
        "--atascii",
        action="store_true",
        help="Render ASCII column using ATASCII mapping.",
    )
    readmem.add_argument(
        "-c",
        "--columns",
        type=int,
        default=None,
        help="Bytes per line (default: 16).",
    )
    readmem.add_argument(
        "--nohex",
        action="store_true",
        help="Hide hex column in formatted output.",
    )
    readmem.add_argument(
        "--noascii",
        action="store_true",
        help="Hide ASCII column in formatted output.",
    )
    readmem.set_defaults(func=_cmd_readmem)

    writemem = subparsers.add_parser("writemem", help="Write memory.")
    writemem.add_argument("addr", help="Address (hex: 0xNNNN, $NNNN, NNNN).")
    writemem.add_argument(
        "bytes",
        nargs="*",
        help="Byte/word values (hex). Values > FF are written as little-endian words.",
    )
    writemem_input = writemem.add_mutually_exclusive_group()
    writemem_input.add_argument(
        "--hex",
        dest="hex_data",
        default=None,
        help="Hex payload (001122...) or '-' to read from stdin.",
    )
    writemem_input.add_argument(
        "--text",
        dest="text_data",
        default=None,
        help="Text payload or '-' to read from stdin.",
    )
    writemem.add_argument(
        "-a",
        "--atascii",
        action="store_true",
        help="Encode --text using ATASCII bytes.",
    )
    writemem.add_argument(
        "-S",
        "--screen",
        action="store_true",
        help="Convert payload from ATASCII to screen codes.",
    )
    writemem.set_defaults(func=_cmd_writemem)

    disasm = subparsers.add_parser("disasm", help="Disassemble 6502 memory.")
    disasm.add_argument("addr", help="Address (hex: 0xNNNN, $NNNN, NNNN).")
    disasm.add_argument("length", help="Length (hex: 0xNNNN, $NNNN, NNNN).")
    disasm.set_defaults(func=_cmd_disasm)

    screen = subparsers.add_parser(
        "screen", help="Dump screen memory segments."
    )
    screen.add_argument(
        "segment",
        nargs="?",
        type=int,
        default=None,
        help="Segment number (1-based). When omitted, dumps all segments.",
    )
    screen.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List screen segments.",
    )
    screen.add_argument(
        "-a",
        "--atascii",
        action="store_true",
        help="Render ASCII column using ATASCII mapping.",
    )
    screen.add_argument(
        "-c",
        "--columns",
        type=int,
        default=None,
        help="Bytes per line (default: 16).",
    )
    screen.add_argument(
        "--nohex",
        action="store_true",
        help="Hide hex column in formatted output.",
    )
    screen.add_argument(
        "--noascii",
        action="store_true",
        help="Hide ASCII column in formatted output.",
    )
    screen_format = screen.add_mutually_exclusive_group()
    screen_format.add_argument(
        "--raw",
        action="store_true",
        help="Output raw bytes without formatting.",
    )
    screen_format.add_argument(
        "--json",
        action="store_true",
        help="Output JSON with address and buffer.",
    )
    screen.set_defaults(func=_cmd_screen)
    return parser.parse_args(argv)


def _rpc(socket_path):
    return RpcClient(SocketTransport(socket_path))


def async_to_sync(awaitable):
    return asyncio.run(awaitable)


def _cmd_monitor(args):
    run_monitor(args.socket)
    return 0


def _cmd_run(args):
    path = os.path.realpath(os.path.expanduser(args.path))
    async_to_sync(_rpc(args.socket).call(Command.RUN, path.encode("utf-8")))
    return 0


def _cmd_pause(args):
    async_to_sync(_rpc(args.socket).call(Command.PAUSE))
    return 0


def _cmd_step(args):
    async def run():
        rpc = _rpc(args.socket)
        await rpc.call(Command.STEP)
        await _print_cpu_state(rpc)

    async_to_sync(run())
    return 0


def _cmd_step_vblank(args):
    async def run():
        rpc = _rpc(args.socket)
        await rpc.call(Command.STEP_VBLANK)
        await _print_cpu_state(rpc)

    async_to_sync(run())
    return 0


def _cmd_step_over(args):
    pc = parse_hex(args.pc) if args.pc is not None else None

    async def run():
        rpc = _rpc(args.socket)
        payload = None if pc is None else struct.pack("<H", pc & 0xFFFF)
        await rpc.call(Command.STEP_OVER, payload)
        await _print_cpu_state(rpc)

    async_to_sync(run())
    return 0


def _cmd_run_until_return(args):
    pc = parse_hex(args.pc) if args.pc is not None else None

    async def run():
        rpc = _rpc(args.socket)
        payload = None if pc is None else struct.pack("<H", pc & 0xFFFF)
        await rpc.call(Command.RUN_UNTIL_RETURN, payload)
        await _print_cpu_state(rpc)

    async_to_sync(run())
    return 0


def _cmd_continue(args):
    async_to_sync(_rpc(args.socket).call(Command.CONTINUE))
    return 0


def _cmd_coldstart(args):
    async_to_sync(_rpc(args.socket).call(Command.COLDSTART))
    return 0


def _cmd_warmstart(args):
    async_to_sync(_rpc(args.socket).call(Command.WARMSTART))
    return 0


def _cmd_removecartrige(args):
    async_to_sync(_rpc(args.socket).call(Command.REMOVECARTRIGE))
    return 0


def _cmd_emulator_stop(args):
    async_to_sync(_rpc(args.socket).call(Command.STOP_EMULATOR))
    return 0


def _cmd_emulator_restart(args):
    async_to_sync(_rpc(args.socket).call(Command.RESTART_EMULATOR))
    return 0


def _cmd_removetape(args):
    async_to_sync(_rpc(args.socket).call(Command.REMOVE_TAPE))
    return 0


def _cmd_removedisks(args):
    async_to_sync(_rpc(args.socket).call(Command.REMOVE_DISKS))
    return 0


def _cmd_dump_dlist(args):
    start_from_arg = None
    if args.address is not None:
        start_from_arg = parse_hex(args.address)

    async def run():
        rpc = _rpc(args.socket)
        if start_from_arg is None:
            start_addr = await rpc.read_vector(DLPTRS_ADDR)
            dump = await rpc.read_display_list()
        else:
            start_addr = start_from_arg & 0xFFFF
            dump = await rpc.read_display_list(start_addr)
        dmactl = await rpc.read_byte(DMACTL_ADDR)
        if (dmactl & 0x03) == 0:
            dmactl = await rpc.read_byte(DMACTL_HW_ADDR)
        return start_addr, dump, dmactl

    start_addr, dump, dmactl = async_to_sync(run())
    dlist = decode_displaylist(start_addr, dump)
    for count, entry in dlist.compacted_entries():
        if count > 1:
            line = f"{entry.addr:04X}: {count}x {entry.description}"
        else:
            line = f"{entry.addr:04X}: {entry.description}"
        sys.stdout.write(line + "\n")
    sys.stdout.write("\n")
    sys.stdout.write(f"Length: {len(dump):04X}\n")
    segments = dlist.screen_segments(dmactl)
    if segments:
        sys.stdout.write("Screen segments:\n")
        for idx, (start, end, mode) in enumerate(segments, start=1):
            length = end - start
            last = (end - 1) & 0xFFFF
            sys.stdout.write(
                f"#%d {start:04X}-{last:04X} len={length:04X} antic={mode}\n" % idx
            )
    return 0


def _cmd_cpustate(args):
    async_to_sync(_print_cpu_state(_rpc(args.socket)))
    return 0


def _cmd_gtia_state(args):
    state = async_to_sync(_rpc(args.socket).gtia_state())
    sys.stdout.write("HPOSP:  " + _fmt_bytes(state.hposp) + "\n")
    sys.stdout.write("HPOSM:  " + _fmt_bytes(state.hposm) + "\n")
    sys.stdout.write("SIZEP:  " + _fmt_bytes(state.sizep) + "\n")
    sys.stdout.write(f"SIZEM:  {state.sizem:02X}\n")
    sys.stdout.write("GRAFP:  " + _fmt_bytes(state.grafp) + "\n")
    sys.stdout.write(f"GRAFM:  {state.grafm:02X}\n")
    sys.stdout.write("COLPM:  " + _fmt_bytes(state.colpm) + "\n")
    sys.stdout.write("COLPF:  " + _fmt_bytes(state.colpf) + "\n")
    sys.stdout.write(f"COLBK:  {state.colbk:02X}\n")
    sys.stdout.write(f"PRIOR:  {state.prior:02X}\n")
    sys.stdout.write(f"VDELAY: {state.vdelay:02X}\n")
    sys.stdout.write(f"GRACTL: {state.gractl:02X}\n")
    return 0


def _cmd_antic_state(args):
    state = async_to_sync(_rpc(args.socket).antic_state())
    sys.stdout.write(f"DMACTL: {state.dmactl:02X}\n")
    sys.stdout.write(f"CHACTL: {state.chactl:02X}\n")
    sys.stdout.write(f"DLIST:  {state.dlist:04X}\n")
    sys.stdout.write(f"HSCROL: {state.hscrol:02X}\n")
    sys.stdout.write(f"VSCROL: {state.vscrol:02X}\n")
    sys.stdout.write(f"PMBASE: {state.pmbase:02X}\n")
    sys.stdout.write(f"CHBASE: {state.chbase:02X}\n")
    sys.stdout.write(f"VCOUNT: {state.vcount:02X}\n")
    sys.stdout.write(f"NMIEN:  {state.nmien:02X}\n")
    sys.stdout.write(f"YPOS:   {state.ypos}\n")
    return 0


def _cmd_cart_state(args):
    state = async_to_sync(_rpc(args.socket).cartrige_state())
    sys.stdout.write(f"autoreboot:    {state.autoreboot}\n")
    sys.stdout.write(f"main_present:  {state.main.present}\n")
    sys.stdout.write(f"main_type:     {state.main.cart_type}\n")
    sys.stdout.write(f"main_state:    {state.main.state:08X}\n")
    sys.stdout.write(f"main_size_kb:  {state.main.size_kb}\n")
    sys.stdout.write(f"main_raw:      {state.main.raw}\n")
    sys.stdout.write(f"piggy_present: {state.piggy.present}\n")
    sys.stdout.write(f"piggy_type:    {state.piggy.cart_type}\n")
    sys.stdout.write(f"piggy_state:   {state.piggy.state:08X}\n")
    sys.stdout.write(f"piggy_size_kb: {state.piggy.size_kb}\n")
    sys.stdout.write(f"piggy_raw:     {state.piggy.raw}\n")
    return 0


def _cmd_jumps(args):
    state = async_to_sync(_rpc(args.socket).jumps())
    for idx, pc in enumerate(state.pcs, start=1):
        sys.stdout.write(f"{idx:02d}: {pc:04X}\n")
    return 0


def _cmd_pia_state(args):
    state = async_to_sync(_rpc(args.socket).pia_state())
    sys.stdout.write(f"PACTL: {state.pactl:02X}\n")
    sys.stdout.write(f"PBCTL: {state.pbctl:02X}\n")
    sys.stdout.write(f"PORTA: {state.porta:02X}\n")
    sys.stdout.write(f"PORTB: {state.portb:02X}\n")
    return 0


def _cmd_pokey_state(args):
    state = async_to_sync(_rpc(args.socket).pokey_state())
    sys.stdout.write(f"stereo_enabled: {state.stereo_enabled}\n")
    sys.stdout.write("AUDF1:          " + _fmt_bytes(state.audf1) + "\n")
    sys.stdout.write("AUDC1:          " + _fmt_bytes(state.audc1) + "\n")
    sys.stdout.write(f"AUDCTL1:        {state.audctl1:02X}\n")
    sys.stdout.write(f"KBCODE:         {state.kbcode:02X}\n")
    sys.stdout.write(f"IRQEN:          {state.irqen:02X}\n")
    sys.stdout.write(f"IRQST:          {state.irqst:02X}\n")
    sys.stdout.write(f"SKSTAT:         {state.skstat:02X}\n")
    sys.stdout.write(f"SKCTL:          {state.skctl:02X}\n")
    if state.stereo_enabled:
        sys.stdout.write("AUDF2:          " + _fmt_bytes(state.audf2) + "\n")
        sys.stdout.write("AUDC2:          " + _fmt_bytes(state.audc2) + "\n")
        sys.stdout.write(f"AUDCTL2:        {state.audctl2:02X}\n")
    return 0


def _cmd_stack(args):
    state = async_to_sync(_rpc(args.socket).stack())
    sys.stdout.write(f"S={state.s:02X} count={len(state.entries)}\n")
    for entry in state.entries:
        sys.stdout.write(f"01{entry.stack_off:02X}: {entry.value:02X}\n")
    return 0


def _cmd_history(args):
    entries = async_to_sync(_rpc(args.socket).history())
    if args.count is not None:
        n = max(0, int(args.count))
        entries = entries[:n] if n else []
    entries = list(reversed(entries))
    for idx, entry in enumerate(entries, start=1):
        try:
            dis = disasm_6502_one(entry.pc, entry.opbytes)
        except RuntimeError:
            dis = f"{entry.op0:02X} {entry.op1:02X} {entry.op2:02X}"
        sys.stdout.write(
            f"{idx:03d} Y={entry.y:02X} X={entry.x:02X} PC={entry.pc:04X}  {dis}\n"
        )
    return 0


def _cmd_emulator_debug(args):
    async_to_sync(_rpc(args.socket).call(Command.BUILTIN_MONITOR))
    return 0


def _cmd_emulator_config(args):
    caps = async_to_sync(_rpc(args.socket).build_features())
    enabled = set(caps)
    known = set()
    for cap_id, desc in EMULATOR_CAPABILITIES:
        known.add(cap_id)
        badge = _format_on_off_badge(cap_id in enabled)
        sys.stdout.write(f"{badge} {desc}\n")
    for cap_id in sorted(v for v in enabled if v not in known):
        badge = _format_on_off_badge(True)
        sys.stdout.write(f"{badge} Unknown capability 0x{cap_id:04X}\n")
    return 0


def _cmd_bp_list(args):
    enabled, clauses = async_to_sync(_rpc(args.socket).breakpoint_list())
    sys.stdout.write(f"Enabled: {_format_on_off_badge(enabled)}\n")
    if not clauses:
        sys.stdout.write("No breakpoint clauses.\n")
        return 0
    for idx, clause in enumerate(clauses, start=1):
        cond_text = " && ".join(_format_bp_condition(cond) for cond in clause)
        sys.stdout.write(f"#{idx:02d} {cond_text}\n")
    return 0


def _cmd_bp_add(args):
    conditions = [_parse_bp_condition(text) for text in args.conditions]
    idx = async_to_sync(_rpc(args.socket).breakpoint_add_clause(conditions))
    sys.stdout.write(f"Added clause #{idx + 1}\n")
    return 0


def _cmd_bp_del(args):
    idx = int(args.index)
    if idx <= 0:
        raise SystemExit("Clause index must be >= 1.")
    async_to_sync(_rpc(args.socket).breakpoint_delete_clause(idx - 1))
    return _cmd_bp_list(args)


def _cmd_bp_clear(args):
    async_to_sync(_rpc(args.socket).breakpoint_clear())
    return _cmd_bp_list(args)


def _cmd_bp_on(args):
    async_to_sync(_rpc(args.socket).breakpoint_set_enabled(True))
    return _cmd_bp_list(args)


def _cmd_bp_off(args):
    async_to_sync(_rpc(args.socket).breakpoint_set_enabled(False))
    return _cmd_bp_list(args)


def _cmd_bbrk(args):
    payload = None
    if args.enabled is not None:
        payload = struct.pack("<B", 1 if _parse_bool(args.enabled) else 0)
    data = async_to_sync(_rpc(args.socket).call(Command.BBRK, payload))
    if len(data) < 1:
        raise SystemExit("BBRK payload too short")
    sys.stdout.write(f"bbrk={'on' if data[0] else 'off'}\n")
    return 0


def _cmd_bline(args):
    payload = None
    if args.scanline is not None:
        payload = struct.pack("<H", parse_hex(args.scanline) & 0xFFFF)
    data = async_to_sync(_rpc(args.socket).call(Command.BLINE, payload))
    if len(data) < 3:
        raise SystemExit("BLINE payload too short")
    scanline, mode = struct.unpack("<HB", data[:3])
    mode_name = {0: "disabled", 1: "break", 2: "blink"}.get(mode, f"mode{mode}")
    sys.stdout.write(f"scanline={scanline} mode={mode_name}\n")
    return 0


def _trainer_read_memory(socket_path: str, start: int, length: int):
    async def run():
        rpc = _rpc(socket_path)
        return await rpc.read_memory(start, length)

    return async_to_sync(run())


def _trainer_parse_value(value: str):
    try:
        return parse_hex_u8(value)
    except ValueError as ex:
        raise ValueError("Invalid trainer value (hex 00..FF).") from ex


def _trainer_parse_limit(value: str):
    return parse_positive_int(value)


def _trainer_print(trainer, limit: int):
    total = len(trainer.candidates)
    sys.stdout.write(f"matches={total}\n")
    if total == 0:
        return
    rows = trainer.rows(limit)
    sys.stdout.write("idx  addr  val\n")
    for idx, (addr, value) in enumerate(rows, start=1):
        sys.stdout.write(f"{idx:03d}  {addr:04X}  {value:02X}\n")
    if len(rows) < total:
        sys.stdout.write(f"... {total - len(rows)} more\n")


def _trainer_print_single_auto(trainer):
    rows = trainer.rows(1)
    if not rows:
        return
    sys.stdout.write("idx  addr  val\n")
    addr, value = rows[0]
    sys.stdout.write(f"001  {addr:04X}  {value:02X}\n")


def _cmd_trainer(args):
    start = parse_hex(args.start) & 0xFFFF
    stop = parse_hex(args.stop) & 0xFFFF
    if stop < start:
        raise SystemExit("Stop address must be >= start address.")
    try:
        value = _trainer_parse_value(args.value)
    except ValueError as ex:
        raise SystemExit(str(ex)) from ex

    trainer = Trainer(start, stop)
    trainer.bind_reader(
        lambda addr, length: _trainer_read_memory(args.socket, addr, length)
    )
    matches = trainer.start(value)

    sys.stdout.write(
        f"range={start:04X}-{stop:04X} initial={value:02X} matches={matches}\n"
    )
    sys.stdout.write("commands: c <value>, nc, p [limit], q\n")
    if not matches:
        return 0
    if matches == 1:
        _trainer_print_single_auto(trainer)

    while True:
        try:
            line = input("trainer> ").strip()
        except EOFError:
            sys.stdout.write("\n")
            return 0
        except KeyboardInterrupt:
            sys.stdout.write("\n")
            return 0

        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "q":
            return 0
        if cmd == "p":
            if len(parts) > 2:
                sys.stdout.write("Usage: p [limit]\n")
                continue
            try:
                limit = 20 if not len(parts) == 2 else _trainer_parse_limit(parts[1])
            except ValueError as ex:
                sys.stdout.write(str(ex) + "\n")
                continue
            _trainer_print(trainer, limit)
            continue
        if cmd == "nc":
            if not len(parts) == 1:
                sys.stdout.write("Usage: nc\n")
                continue
            matches = trainer.not_changed()
            sys.stdout.write(f"matches={matches}\n")
            if not matches:
                return 0
            if matches == 1:
                _trainer_print_single_auto(trainer)
            continue
        if cmd == "c":
            if not len(parts) == 2:
                sys.stdout.write("Usage: c <value>\n")
                continue
            try:
                target = _trainer_parse_value(parts[1])
            except ValueError as ex:
                sys.stdout.write(str(ex) + "\n")
                continue
            matches = trainer.changed(target)
            sys.stdout.write(f"matches={matches}\n")
            if not matches:
                return 0
            if matches == 1:
                _trainer_print_single_auto(trainer)
            continue

        sys.stdout.write("Unknown command. Use: c <value>, nc, p [limit], q\n")
    return 0


def _cmd_search(args):
    raw = " ".join(args.pattern)
    if args.atascii or args.screen:
        try:
            pattern = text_to_atascii(raw)
        except ValueError as ex:
            raise SystemExit(str(ex)) from ex
        if args.screen:
            pattern = bytes(atascii_to_screen(v) for v in pattern)
    else:
        pattern = parse_hex_payload(raw)
    mode_id = SEARCH_MODE_BYTES
    start = parse_hex(args.start) & 0xFFFF
    end = parse_hex(args.end) & 0xFFFF
    if len(pattern) == 0 or len(pattern) > 0xFF:
        raise SystemExit("Pattern length must be in range 1..255.")
    payload = (
        struct.pack("<BHHB", mode_id, start, end, len(pattern))
        + pattern
    )
    data = async_to_sync(_rpc(args.socket).call(Command.SEARCH, payload))
    if len(data) < 6:
        raise SystemExit("SEARCH payload too short")
    total, returned = struct.unpack_from("<IH", data, 0)
    expected = 6 + returned * 2
    if len(data) < expected:
        raise SystemExit(
            f"SEARCH payload too short: got={len(data)} expected={expected}"
        )
    sys.stdout.write(f"matches={total} returned={returned}\n")
    off = 6
    for _ in range(returned):
        addr = struct.unpack_from("<H", data, off)[0]
        off += 2
        sys.stdout.write(f"{addr:04X}\n")
    return 0


def _cmd_set_reg(args):
    target = SET_REG_TARGETS[args.target.lower()]
    value = parse_hex(args.value) & 0xFFFF
    payload = struct.pack("<BH", target, value)
    async_to_sync(_rpc(args.socket).call(Command.SET_REG, payload))
    return 0


def _cmd_status(args):
    st = async_to_sync(_rpc(args.socket).status())
    paused = "yes" if st.paused else "no"
    crashed = "yes" if st.crashed else "no"
    sys.stdout.write(
        "paused=%s crashed=%s emu_ms=%d reset_ms=%d state_seq=%d\n"
        % (paused, crashed, st.emu_ms, st.reset_ms, st.state_seq)
    )
    return 0


def _cmd_ping(args):
    data = async_to_sync(_rpc(args.socket).call(Command.PING))
    if data:
        sys.stdout.buffer.write(data)
    return 0


def _cmd_readmem(args):
    addr = parse_hex(args.addr)
    length = parse_hex(args.length)
    data = async_to_sync(_rpc(args.socket).read_memory(addr, length))
    _dump_memory(
        address=addr,
        length=length,
        data=data,
        args=args,
        columns=args.columns,
    )
    return 0


def _cmd_writemem(args):
    addr = parse_hex(args.addr)
    has_bytes = bool(args.bytes)
    has_hex = args.hex_data is not None
    has_text = args.text_data is not None
    if int(has_bytes) + int(has_hex) + int(has_text) != 1:
        raise SystemExit("Specify exactly one payload: <bytes...>, --hex, or --text.")
    if args.atascii and not has_text:
        raise SystemExit("--atascii is only valid with --text.")
    if has_bytes:
        data = parse_hex_values(args.bytes)
    elif has_hex:
        text = (
            sys.stdin.buffer.read().decode("utf-8", errors="replace")
            if args.hex_data == "-"
            else args.hex_data
        )
        data = parse_hex_payload(text)
    else:
        text = (
            sys.stdin.buffer.read().decode("utf-8", errors="replace")
            if args.text_data == "-"
            else args.text_data
        )
        if args.atascii:
            try:
                data = text_to_atascii(text)
            except ValueError as ex:
                raise SystemExit(str(ex)) from ex
        else:
            data = text.encode("utf-8")
    if len(data) == 0:
        raise SystemExit("No data to write.")
    if len(data) > 0xFFFF:
        raise SystemExit(f"Data too long: {len(data)} bytes (max 65535).")
    if args.screen:
        data = bytes(atascii_to_screen(v) for v in data)
    async_to_sync(_rpc(args.socket).write_memory(addr, data))
    return 0


def _cmd_disasm(args):
    addr = parse_hex(args.addr)
    length = parse_hex(args.length)
    data = async_to_sync(_rpc(args.socket).read_memory(addr, length))
    for line in disasm_6502(addr, data):
        sys.stdout.write(line + "\n")
    return 0


def _cmd_screen(args):
    if args.list and args.segment is not None:
        raise SystemExit("--list cannot be used with a segment number.")

    async def run():
        rpc = _rpc(args.socket)
        start_addr = await rpc.read_vector(DLPTRS_ADDR)
        dump = await rpc.read_display_list()
        dmactl = await rpc.read_byte(DMACTL_ADDR)
        if (dmactl & 0x03) == 0:
            dmactl = await rpc.read_byte(DMACTL_HW_ADDR)
        return start_addr, dump, dmactl

    start_addr, dump, dmactl = async_to_sync(run())
    dlist = decode_displaylist(start_addr, dump)
    segments = dlist.screen_segments(dmactl)
    if not segments:
        raise SystemExit("No screen segments found.")
    if args.list:
        for idx, (start, end, mode) in enumerate(segments, start=1):
            length = end - start
            last = (end - 1) & 0xFFFF
            sys.stdout.write(
                f"#%d {start:04X}-{last:04X} len={length:04X} antic={mode}\n" % idx
            )
        return 0

    mapper = DisplayListMemoryMapper(dlist, dmactl)
    if args.segment is None:
        if args.columns is None and not args.raw and not args.json:
            async def read_all_rows():
                rpc = _rpc(args.socket)
                out = []
                for addr, row_len in mapper.row_ranges():
                    if addr is None or row_len <= 0:
                        continue
                    row = await rpc.read_memory(addr, row_len)
                    if row:
                        out.append((addr, row))
                return out

            rows = async_to_sync(read_all_rows())
            if rows:
                sys.stdout.write(
                    dump_memory_human_rows(
                        rows=rows,
                        use_atascii=args.atascii,
                        show_hex=not args.nohex,
                        show_ascii=not args.noascii,
                    )
                    + "\n"
                )
                return 0
        async def read_all_segments():
            rpc = _rpc(args.socket)
            out = []
            for start, end, _mode in segments:
                out.append(await rpc.read_memory(start, end - start))
            return out

        chunks = async_to_sync(read_all_segments())
        data = b"".join(chunks)
        _dump_memory(
            address=segments[0][0],
            length=len(data),
            data=data,
            args=args,
            columns=args.columns,
        )
        return 0

    seg_num = args.segment
    idx = seg_num - 1
    if idx < 0 or idx >= len(segments):
        raise SystemExit(f"Segment out of range (1-{len(segments)})")
    start, end, mode = segments[idx]
    length = end - start
    data = async_to_sync(_rpc(args.socket).read_memory(start, length))
    columns = args.columns
    if columns is None and not args.raw and not args.json:
        rows = []
        for addr, row_len in mapper.row_ranges():
            if addr is None or row_len <= 0:
                continue
            if not (start <= addr < end):
                continue
            rel = addr - start
            row = data[rel : rel + row_len]
            if not row:
                continue
            rows.append((addr, row))
        if rows:
            sys.stdout.write(
                dump_memory_human_rows(
                    rows=rows,
                    use_atascii=args.atascii,
                    show_hex=not args.nohex,
                    show_ascii=not args.noascii,
                )
                + "\n"
            )
            return 0
    if columns is None:
        default_cols = mapper.bytes_per_line(mode)
        if default_cols:
            columns = default_cols
    _dump_memory(
        address=start,
        length=length,
        data=data,
        args=args,
        columns=columns,
    )
    return 0


def _dump_memory(address, length, data, args, columns):
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


async def _print_cpu_state(rpc):
    ypos, xpos, pc, a, x, y, s, p = await rpc.cpu_state()
    cpu = CpuState(ypos=ypos, xpos=xpos, pc=pc, a=a, x=x, y=y, s=s, p=p)
    sys.stdout.write(repr(cpu) + "\n")


def _parse_bool(value):
    text = value.strip().lower()
    if text in ("1", "on", "true", "yes"):
        return True
    if text in ("0", "off", "false", "no"):
        return False
    raise SystemExit(f"Invalid boolean value: {value}")


def _fmt_bytes(values):
    return " ".join(f"{value:02X}" for value in values)


def _split_bp_expression(expr):
    text = expr.strip()
    for op in ("<=", ">=", "==", "!=", "=", "<", ">"):
        pos = text.find(op)
        if pos > 0:
            left = text[:pos].strip()
            right = text[pos + len(op):].strip()
            if not right:
                break
            return left, op, right
    raise SystemExit(f"Invalid breakpoint condition: {expr}")


def _parse_bp_condition(expr):
    left, op, value_text = _split_bp_expression(expr)
    op_id = BP_OPS.get(op)
    if op_id is None:
        raise SystemExit(f"Invalid breakpoint operator in condition: {expr}")
    left_key = left.strip().lower()
    addr = 0
    cond_type = BP_CONDITION_TYPES.get(left_key)
    if cond_type is None:
        if left_key.startswith("mem[") and left_key.endswith("]"):
            cond_type = 9
            try:
                addr = parse_hex(left_key[4:-1])
            except ValueError as ex:
                raise SystemExit(f"Invalid memory address in condition: {expr}") from ex
        elif left_key.startswith("mem:"):
            cond_type = 9
            try:
                addr = parse_hex(left_key[4:])
            except ValueError as ex:
                raise SystemExit(f"Invalid memory address in condition: {expr}") from ex
        else:
            raise SystemExit(f"Invalid breakpoint source in condition: {expr}")
    try:
        value = parse_hex(value_text)
    except ValueError as ex:
        raise SystemExit(f"Invalid breakpoint value in condition: {expr}") from ex
    if value < 0 or value > 0xFFFF:
        raise SystemExit(f"Breakpoint value out of range (0..FFFF): {value_text}")
    if addr < 0 or addr > 0xFFFF:
        raise SystemExit(f"Breakpoint address out of range (0..FFFF): {left}")
    return cond_type, op_id, addr, value


def _format_bp_value(cond_type, value):
    if cond_type in (2, 3, 4, 5):
        return f"${value:02X}"
    return f"${value:04X}"


def _format_bp_condition(cond):
    cond_type, op, addr, value = cond
    op_text = BP_OP_NAMES.get(op, f"op{op}")
    if cond_type == 9:
        return f"mem[{addr:04X}] {op_text} {_format_bp_value(cond_type, value)}"
    name = BP_TYPE_NAMES.get(cond_type, f"type{cond_type}")
    return f"{name} {op_text} {_format_bp_value(cond_type, value)}"


def _cli_color_enabled():
    color_mode = os.getenv("A800MON_COLOR", "").strip().lower()
    term = os.getenv("TERM", "")
    if color_mode == "always":
        return True
    if color_mode == "never":
        return False
    return bool(term and term != "dumb")


def _format_on_off_badge(enabled: bool) -> str:
    text = "ON " if enabled else "OFF"
    badge = f" {text} "
    if not _cli_color_enabled():
        return badge
    if enabled:
        return f"\x1b[42;30m{badge}\x1b[0m"
    return f"\x1b[41;97;1m{badge}\x1b[0m"


def _format_rpc_exception(ex):
    if isinstance(ex, CommandError):
        code = str(ex.status)
        msg = ex.data.decode("utf-8", errors="replace").strip() if ex.data else str(ex)
    else:
        code = "ERR"
        msg = str(ex)
    badge = f" {code} "
    if _cli_color_enabled():
        return f"\x1b[41;97;1m{badge}\x1b[0m {msg}"
    return f"[{code}] {msg}"


def main(argv=None):
    args = _parse_args(argv or sys.argv[1:])
    try:
        if args.cmd is None:
            return _cmd_monitor(args)
        return args.func(args)
    except RpcException as ex:
        sys.stderr.write(_format_rpc_exception(ex) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
