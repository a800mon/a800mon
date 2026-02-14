import sys

from ...atari.displaylist import (
    DLPTRS_ADDR,
    DMACTL_ADDR,
    DMACTL_HW_ADDR,
    DisplayListMemoryMapper,
    decode_displaylist,
)
from ...atari.memory import dump_memory_human_rows
from ..common import async_to_sync, dump_memory_output, fmt_bytes, rpc_client


def register(subparsers):
    dump = subparsers.add_parser("dump", help="Dump hardware/display state.")
    dump_sub = dump.add_subparsers(dest="dump_cmd", metavar="subcmd")
    dump_sub.required = True

    dlist = dump_sub.add_parser("dlist", help="Dump display list.")
    dlist.add_argument(
        "address",
        nargs="?",
        default=None,
        help="Optional display list start address (hex: 0xNNNN, $NNNN, NNNN).",
    )
    dlist.set_defaults(func=cmd_dump_dlist)

    gtia = dump_sub.add_parser("gtia", help="Show GTIA register state.")
    gtia.set_defaults(func=cmd_gtia_state)

    antic = dump_sub.add_parser("antic", help="Show ANTIC register state.")
    antic.set_defaults(func=cmd_antic_state)

    pia = dump_sub.add_parser("pia", help="Show PIA register state.")
    pia.set_defaults(func=cmd_pia_state)

    pokey = dump_sub.add_parser("pokey", help="Show POKEY register state.")
    pokey.set_defaults(func=cmd_pokey_state)

    screen = subparsers.add_parser("screen", help="Dump screen memory segments.")
    screen.add_argument(
        "segment",
        nargs="?",
        type=int,
        default=None,
        help="Segment number (1-based). When omitted, dumps all segments.",
    )
    screen.add_argument(
        "-l", "--list", action="store_true", help="List screen segments."
    )
    screen.add_argument(
        "-a", "--atascii", action="store_true", help="Use ATASCII mapping."
    )
    screen.add_argument(
        "-c", "--columns", type=int, default=None, help="Bytes per line."
    )
    screen.add_argument("--nohex", action="store_true", help="Hide hex column.")
    screen.add_argument("--noascii", action="store_true", help="Hide ASCII column.")
    fmt = screen.add_mutually_exclusive_group()
    fmt.add_argument("--raw", action="store_true", help="Output raw bytes.")
    fmt.add_argument("--json", action="store_true", help="Output JSON.")
    screen.set_defaults(func=cmd_screen)


async def _read_dlist_context(socket):
    rpc = rpc_client(socket)
    start_addr = await rpc.read_vector(DLPTRS_ADDR)
    dump = await rpc.read_display_list()
    dmactl = await rpc.read_byte(DMACTL_ADDR)
    if (dmactl & 0x03) == 0:
        dmactl = await rpc.read_byte(DMACTL_HW_ADDR)
    return start_addr, dump, dmactl


def cmd_dump_dlist(args):
    from ...atari.memory import parse_hex

    start_from_arg = parse_hex(args.address) if args.address is not None else None

    async def run():
        rpc = rpc_client(args.socket)
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
        line = (
            f"{entry.addr:04X}: {count}x {entry.description}"
            if count > 1
            else f"{entry.addr:04X}: {entry.description}"
        )
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


def cmd_gtia_state(args):
    state = async_to_sync(rpc_client(args.socket).gtia_state())
    sys.stdout.write("HPOSP:  " + fmt_bytes(state.hposp) + "\n")
    sys.stdout.write("HPOSM:  " + fmt_bytes(state.hposm) + "\n")
    sys.stdout.write("SIZEP:  " + fmt_bytes(state.sizep) + "\n")
    sys.stdout.write(f"SIZEM:  {state.sizem:02X}\n")
    sys.stdout.write("GRAFP:  " + fmt_bytes(state.grafp) + "\n")
    sys.stdout.write(f"GRAFM:  {state.grafm:02X}\n")
    sys.stdout.write("COLPM:  " + fmt_bytes(state.colpm) + "\n")
    sys.stdout.write("COLPF:  " + fmt_bytes(state.colpf) + "\n")
    sys.stdout.write(f"COLBK:  {state.colbk:02X}\n")
    sys.stdout.write(f"PRIOR:  {state.prior:02X}\n")
    sys.stdout.write(f"VDELAY: {state.vdelay:02X}\n")
    sys.stdout.write(f"GRACTL: {state.gractl:02X}\n")
    return 0


def cmd_antic_state(args):
    state = async_to_sync(rpc_client(args.socket).antic_state())
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


def cmd_pia_state(args):
    state = async_to_sync(rpc_client(args.socket).pia_state())
    sys.stdout.write(f"PACTL: {state.pactl:02X}\n")
    sys.stdout.write(f"PBCTL: {state.pbctl:02X}\n")
    sys.stdout.write(f"PORTA: {state.porta:02X}\n")
    sys.stdout.write(f"PORTB: {state.portb:02X}\n")
    return 0


def cmd_pokey_state(args):
    state = async_to_sync(rpc_client(args.socket).pokey_state())
    sys.stdout.write(f"stereo_enabled: {state.stereo_enabled}\n")
    sys.stdout.write("AUDF1:          " + fmt_bytes(state.audf1) + "\n")
    sys.stdout.write("AUDC1:          " + fmt_bytes(state.audc1) + "\n")
    sys.stdout.write(f"AUDCTL1:        {state.audctl1:02X}\n")
    sys.stdout.write(f"KBCODE:         {state.kbcode:02X}\n")
    sys.stdout.write(f"IRQEN:          {state.irqen:02X}\n")
    sys.stdout.write(f"IRQST:          {state.irqst:02X}\n")
    sys.stdout.write(f"SKSTAT:         {state.skstat:02X}\n")
    sys.stdout.write(f"SKCTL:          {state.skctl:02X}\n")
    if state.stereo_enabled:
        sys.stdout.write("AUDF2:          " + fmt_bytes(state.audf2) + "\n")
        sys.stdout.write("AUDC2:          " + fmt_bytes(state.audc2) + "\n")
        sys.stdout.write(f"AUDCTL2:        {state.audctl2:02X}\n")
    return 0


def cmd_screen(args):
    if args.list and args.segment is not None:
        raise SystemExit("--list cannot be used with a segment number.")

    start_addr, dump, dmactl = async_to_sync(_read_dlist_context(args.socket))
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
                rpc = rpc_client(args.socket)
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
            rpc = rpc_client(args.socket)
            out = []
            for start, end, _mode in segments:
                out.append(await rpc.read_memory(start, end - start))
            return out

        chunks = async_to_sync(read_all_segments())
        data = b"".join(chunks)
        dump_memory_output(segments[0][0], len(data), data, args, args.columns)
        return 0

    idx = args.segment - 1
    if idx < 0 or idx >= len(segments):
        raise SystemExit(f"Segment out of range (1-{len(segments)})")

    start, end, mode = segments[idx]
    length = end - start
    data = async_to_sync(rpc_client(args.socket).read_memory(start, length))

    columns = args.columns
    if columns is None and not args.raw and not args.json:
        rows = []
        for addr, row_len in mapper.row_ranges():
            if addr is None or row_len <= 0 or not (start <= addr < end):
                continue
            rel = addr - start
            row = data[rel : rel + row_len]
            if row:
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

    dump_memory_output(start, length, data, args, columns)
    return 0
