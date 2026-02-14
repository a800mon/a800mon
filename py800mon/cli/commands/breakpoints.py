import struct
import sys

from ...breakpoints import format_bp_condition, parse_bp_clauses
from ...atari.memory import parse_hex
from ...rpc import Command
from ..common import async_to_sync, rpc_client
from ..utils import format_toggle_badge


def register(subparsers):
    bp = subparsers.add_parser("bp", help="Manage user breakpoints.")
    bp_sub = bp.add_subparsers(dest="bp_cmd", metavar="subcmd")

    bp.set_defaults(func=cmd_list)

    bp_list = bp_sub.add_parser("ls", help="List user breakpoints.")
    bp_list.set_defaults(func=cmd_list)

    bp_add = bp_sub.add_parser(
        "add",
        help="Add one breakpoint clause (AND).",
    )
    bp_add.add_argument(
        "conditions",
        nargs="+",
        help="Conditions joined by AND in one clause.",
    )
    bp_add.set_defaults(func=cmd_add)

    bp_del = bp_sub.add_parser(
        "del", help="Delete breakpoint clause by index (1-based)."
    )
    bp_del.add_argument("index", type=int, help="Clause index (1-based).")
    bp_del.set_defaults(func=cmd_del)

    bp_clear = bp_sub.add_parser("clear", help="Clear all breakpoint clauses.")
    bp_clear.set_defaults(func=cmd_clear)

    bp_on = bp_sub.add_parser("on", help="Enable all user breakpoints.")
    bp_on.set_defaults(func=cmd_on)

    bp_off = bp_sub.add_parser("off", help="Disable all user breakpoints.")
    bp_off.set_defaults(func=cmd_off)

    scanline = bp_sub.add_parser("scanline", help="Query/set scanline break value.")
    scanline.add_argument(
        "scanline",
        nargs="?",
        default=None,
        help="Optional scanline (hex: 0xNNNN, $NNNN, NNNN).",
    )
    scanline.set_defaults(func=cmd_scanline)


def cmd_list(args):
    bp = async_to_sync(rpc_client(args.socket).breakpoint_list())
    sys.stdout.write(f"Enabled: {format_toggle_badge(bp.enabled)}\n")
    if not bp.clauses:
        sys.stdout.write("No breakpoint clauses.\n")
        return 0
    for idx, clause in enumerate(bp.clauses, start=1):
        cond_text = " AND ".join(
            format_bp_condition(cond) for cond in clause.conditions
        )
        sys.stdout.write(f"#{idx:02d} {cond_text}\n")
    return 0


def cmd_add(args):
    try:
        clauses = parse_bp_clauses(" ".join(args.conditions))
    except ValueError as ex:
        raise SystemExit(str(ex)) from ex

    added = []
    for clause in clauses:
        idx = async_to_sync(rpc_client(args.socket).breakpoint_add_clause(list(clause)))
        added.append(int(idx) + 1)

    if not added:
        return 0
    if len(added) == 1:
        sys.stdout.write(f"Added clause #{added[0]}\n")
    else:
        sys.stdout.write(
            "Added clauses: " + ", ".join(f"#{idx}" for idx in added) + "\n"
        )
    return 0


def cmd_del(args):
    idx = int(args.index)
    if idx <= 0:
        raise SystemExit("Clause index must be >= 1.")
    async_to_sync(rpc_client(args.socket).breakpoint_delete_clause(idx - 1))
    return cmd_list(args)


def cmd_clear(args):
    async_to_sync(rpc_client(args.socket).breakpoint_clear())
    return cmd_list(args)


def cmd_on(args):
    async_to_sync(rpc_client(args.socket).breakpoint_set_enabled(True))
    return cmd_list(args)


def cmd_off(args):
    async_to_sync(rpc_client(args.socket).breakpoint_set_enabled(False))
    return cmd_list(args)


def cmd_scanline(args):
    payload = None
    if args.scanline is not None:
        payload = struct.pack("<H", parse_hex(args.scanline) & 0xFFFF)
    data = async_to_sync(rpc_client(args.socket).call(Command.BLINE, payload))
    if len(data) < 3:
        raise SystemExit("BLINE payload too short")
    scanline, mode = struct.unpack("<HB", data[:3])
    mode_name = {0: "disabled", 1: "break", 2: "blink"}.get(mode, f"mode{mode}")
    sys.stdout.write(f"scanline={scanline} mode={mode_name}\n")
    return 0
