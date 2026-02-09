import argparse
import os
import sys

from .datastructures import CpuState
from .disasm import disasm_6502, disasm_6502_one
from .displaylist import (DLPTRS_ADDR, DMACTL_ADDR, DMACTL_HW_ADDR,
                          DisplayListMemoryMapper, decode_displaylist)
from .main import run as run_monitor
from .memory import dump_memory_human, dump_memory_json, dump_memory_raw
from .rpc import Command, RpcClient
from .socket import SocketTransport


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="a800mon")
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

    stopemulator = subparsers.add_parser("stopemulator", help="Stop emulator.")
    stopemulator.set_defaults(func=_cmd_stop_emulator)

    removetape = subparsers.add_parser("removetape", help="Remove cassette.")
    removetape.set_defaults(func=_cmd_removetape)

    removedisks = subparsers.add_parser(
        "removedisks", help="Remove all disks.")
    removedisks.set_defaults(func=_cmd_removedisks)

    dump_dlist = subparsers.add_parser("dump_dlist", help="Dump display list.")
    dump_dlist.set_defaults(func=_cmd_dump_dlist)

    cpustate = subparsers.add_parser("cpustate", help="Show CPU state.")
    cpustate.set_defaults(func=_cmd_cpustate)

    history = subparsers.add_parser("history", help="Show CPU execution history.")
    history.add_argument(
        "-n",
        "--count",
        type=int,
        default=None,
        help="Limit output to last N entries.",
    )
    history.set_defaults(func=_cmd_history)

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

    disasm = subparsers.add_parser("disasm", help="Disassemble 6502 memory.")
    disasm.add_argument("addr", help="Address (hex: 0xNNNN, $NNNN, NNNN).")
    disasm.add_argument("length", help="Length (hex: 0xNNNN, $NNNN, NNNN).")
    disasm.set_defaults(func=_cmd_disasm)

    screen = subparsers.add_parser(
        "screen", help="Dump screen memory segment or list segments."
    )
    screen.add_argument(
        "segment",
        nargs="?",
        type=int,
        default=None,
        help="Segment number (1-based). When omitted, lists segments.",
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


def _cmd_monitor(args):
    run_monitor(args.socket)
    return 0


def _cmd_run(args):
    path = os.path.realpath(os.path.expanduser(args.path))
    _rpc(args.socket).call(Command.RUN, path.encode("utf-8"))
    return 0


def _cmd_pause(args):
    _rpc(args.socket).call(Command.PAUSE)
    return 0


def _cmd_step(args):
    rpc = _rpc(args.socket)
    rpc.call(Command.STEP)
    _print_cpu_state(rpc)
    return 0


def _cmd_step_vblank(args):
    rpc = _rpc(args.socket)
    rpc.call(Command.STEP_VBLANK)
    _print_cpu_state(rpc)
    return 0


def _cmd_continue(args):
    _rpc(args.socket).call(Command.CONTINUE)
    return 0


def _cmd_coldstart(args):
    _rpc(args.socket).call(Command.COLDSTART)
    return 0


def _cmd_warmstart(args):
    _rpc(args.socket).call(Command.WARMSTART)
    return 0


def _cmd_removecartrige(args):
    _rpc(args.socket).call(Command.REMOVECARTRIGE)
    return 0


def _cmd_stop_emulator(args):
    _rpc(args.socket).call(Command.STOP_EMULATOR)
    return 0


def _cmd_removetape(args):
    _rpc(args.socket).call(Command.REMOVE_TAPE)
    return 0


def _cmd_removedisks(args):
    _rpc(args.socket).call(Command.REMOVE_DISKS)
    return 0


def _cmd_dump_dlist(args):
    rpc = _rpc(args.socket)
    start_addr = rpc.read_vector(DLPTRS_ADDR)
    dump = rpc.read_display_list()
    dlist = decode_displaylist(start_addr, dump)
    for count, entry in dlist.compacted_entries():
        if count > 1:
            line = f"{entry.addr:04X}: {count}x {entry.description}"
        else:
            line = f"{entry.addr:04X}: {entry.description}"
        sys.stdout.write(line + "\n")
    sys.stdout.write("\n")
    sys.stdout.write(f"Length: {len(dump):04X}\n")
    dmactl = rpc.read_byte(DMACTL_ADDR)
    if (dmactl & 0x03) == 0:
        dmactl = rpc.read_byte(DMACTL_HW_ADDR)
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
    _print_cpu_state(_rpc(args.socket))
    return 0


def _cmd_history(args):
    entries = _rpc(args.socket).history()
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


def _cmd_status(args):
    st = _rpc(args.socket).status()
    paused = "yes" if st.paused else "no"
    crashed = "yes" if st.crashed else "no"
    sys.stdout.write(
        "paused=%s crashed=%s emu_ms=%d reset_ms=%d\n"
        % (paused, crashed, st.emu_ms, st.reset_ms)
    )
    return 0


def _cmd_ping(args):
    data = _rpc(args.socket).call(Command.PING)
    if data:
        sys.stdout.buffer.write(data)
    return 0


def _cmd_readmem(args):
    addr = _parse_hex(args.addr)
    length = _parse_hex(args.length)
    data = _rpc(args.socket).read_memory(addr, length)
    _dump_memory(
        address=addr,
        length=length,
        data=data,
        args=args,
        columns=args.columns,
    )
    return 0


def _cmd_disasm(args):
    addr = _parse_hex(args.addr)
    length = _parse_hex(args.length)
    data = _rpc(args.socket).read_memory(addr, length)
    for line in disasm_6502(addr, data):
        sys.stdout.write(line + "\n")
    return 0


def _cmd_screen(args):
    rpc = _rpc(args.socket)
    start_addr = rpc.read_vector(DLPTRS_ADDR)
    dump = rpc.read_display_list()
    dlist = decode_displaylist(start_addr, dump)
    dmactl = rpc.read_byte(DMACTL_ADDR)
    if (dmactl & 0x03) == 0:
        dmactl = rpc.read_byte(DMACTL_HW_ADDR)
    segments = dlist.screen_segments(dmactl)
    if not segments:
        raise SystemExit("No screen segments found.")
    if args.segment is None:
        for idx, (start, end, mode) in enumerate(segments, start=1):
            length = end - start
            last = (end - 1) & 0xFFFF
            sys.stdout.write(
                f"#%d {start:04X}-{last:04X} len={length:04X} antic={mode}\n" % idx
            )
        return 0
    seg_num = args.segment
    idx = seg_num - 1
    if idx < 0 or idx >= len(segments):
        raise SystemExit(f"Segment out of range (1-{len(segments)})")
    start, end, mode = segments[idx]
    length = end - start
    data = rpc.read_memory(start, length)
    columns = args.columns
    if columns is None:
        mapper = DisplayListMemoryMapper(dlist, dmactl)
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


def _print_cpu_state(rpc):
    ypos, xpos, pc, a, x, y, s, p = rpc.cpu_state()
    cpu = CpuState(ypos=ypos, xpos=xpos, pc=pc, a=a, x=x, y=y, s=s, p=p)
    sys.stdout.write(repr(cpu) + "\n")


def _parse_hex(value):
    text = value.strip().lower()
    if text.startswith("$"):
        text = text[1:]
    if text.startswith("0x"):
        text = text[2:]
    return int(text, 16)


def main(argv=None):
    args = _parse_args(argv or sys.argv[1:])
    if args.cmd is None:
        return _cmd_monitor(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
