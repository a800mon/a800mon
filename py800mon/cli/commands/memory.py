import struct
import sys

from ...atari.atascii import atascii_to_screen, text_to_atascii
from ...atari.disasm import disasm_6502
from ...atari.memory import parse_hex, parse_hex_payload, parse_hex_values
from ...rpc import Command
from ..common import SEARCH_MODE_BYTES, async_to_sync, dump_memory_output, rpc_client


def register(subparsers):
    mem = subparsers.add_parser("mem", help="Memory commands.")
    mem_sub = mem.add_subparsers(dest="mem_cmd", metavar="subcmd")
    mem_sub.required = True

    read = mem_sub.add_parser("read", aliases=["r"], help="Read memory.")
    read.add_argument("addr", help="Address (hex: 0xNNNN, $NNNN, NNNN).")
    read.add_argument("length", help="Length (hex: 0xNNNN, $NNNN, NNNN).")
    format_group = read.add_mutually_exclusive_group()
    format_group.add_argument("--raw", action="store_true", help="Output raw bytes.")
    format_group.add_argument("--json", action="store_true", help="Output JSON.")
    read.add_argument(
        "-a", "--atascii", action="store_true", help="Use ATASCII mapping."
    )
    read.add_argument("-c", "--columns", type=int, default=None, help="Bytes per line.")
    read.add_argument("--nohex", action="store_true", help="Hide hex column.")
    read.add_argument("--noascii", action="store_true", help="Hide ASCII column.")
    read.set_defaults(func=cmd_read)

    write = mem_sub.add_parser("write", aliases=["w"], help="Write memory.")
    write.add_argument("addr", help="Address (hex: 0xNNNN, $NNNN, NNNN).")
    write.add_argument(
        "bytes",
        nargs="*",
        help="Byte/word values (hex). Values > FF are little-endian words.",
    )
    write_input = write.add_mutually_exclusive_group()
    write_input.add_argument(
        "--hex",
        dest="hex_data",
        default=None,
        help="Hex payload (001122...) or '-' to read stdin.",
    )
    write_input.add_argument(
        "--text",
        dest="text_data",
        default=None,
        help="Text payload or '-' to read stdin.",
    )
    write.add_argument(
        "-a", "--atascii", action="store_true", help="Encode --text with ATASCII."
    )
    write.add_argument(
        "-S", "--screen", action="store_true", help="Convert payload to screen codes."
    )
    write.set_defaults(func=cmd_write)

    search = mem_sub.add_parser(
        "search",
        aliases=["s"],
        help="Search memory for a pattern.",
    )
    search.add_argument(
        "-a", "--atascii", action="store_true", help="Encode text as ATASCII."
    )
    search.add_argument(
        "-s", "--screen", action="store_true", help="Convert to screen-codes."
    )
    search.add_argument("start", help="Start address (hex: 0xNNNN, $NNNN, NNNN).")
    search.add_argument("end", help="End address (hex: 0xNNNN, $NNNN, NNNN).")
    search.add_argument(
        "pattern", nargs="+", help="Hex bytes by default; text with -a/-s."
    )
    search.set_defaults(func=cmd_search)

    disasm = mem_sub.add_parser(
        "disasm",
        aliases=["d"],
        help="Disassemble 6502 memory.",
    )
    disasm.add_argument("addr", help="Address (hex: 0xNNNN, $NNNN, NNNN).")
    disasm.add_argument("length", help="Length (hex: 0xNNNN, $NNNN, NNNN).")
    disasm.set_defaults(func=cmd_disasm)


def cmd_read(args):
    addr = parse_hex(args.addr)
    length = parse_hex(args.length)
    data = async_to_sync(rpc_client(args.socket).read_memory(addr, length))
    dump_memory_output(addr, length, data, args, args.columns)
    return 0


def cmd_write(args):
    addr = parse_hex(args.addr)
    has_bytes = args.bytes
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

    if not data:
        raise SystemExit("No data to write.")
    if len(data) > 0xFFFF:
        raise SystemExit(f"Data too long: {len(data)} bytes (max 65535).")
    if args.screen:
        data = bytes(atascii_to_screen(v) for v in data)

    async_to_sync(rpc_client(args.socket).write_memory(addr, data))
    return 0


def cmd_search(args):
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

    start = parse_hex(args.start) & 0xFFFF
    end = parse_hex(args.end) & 0xFFFF
    if not pattern or len(pattern) > 0xFF:
        raise SystemExit("Pattern length must be in range 1..255.")

    payload = (
        struct.pack("<BHHB", SEARCH_MODE_BYTES, start, end, len(pattern)) + pattern
    )
    data = async_to_sync(rpc_client(args.socket).call(Command.SEARCH, payload))
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


def cmd_disasm(args):
    addr = parse_hex(args.addr)
    length = parse_hex(args.length)
    data = async_to_sync(rpc_client(args.socket).read_memory(addr, length))
    for line in disasm_6502(addr, data):
        sys.stdout.write(line + "\n")
    return 0
