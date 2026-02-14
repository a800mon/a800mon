import struct

from ...atari.memory import parse_hex
from ...rpc import Command
from ..common import (
    SET_REG_TARGETS,
    async_to_sync,
    parse_bool,
    print_cpu_state,
    rpc_client,
)


def register(subparsers):
    cpu = subparsers.add_parser("cpu", help="CPU commands.")
    cpu_sub = cpu.add_subparsers(dest="cpu_cmd", metavar="subcmd")

    get_cmd = cpu_sub.add_parser("get", help="Show CPU state.")
    get_cmd.set_defaults(func=cmd_get)

    set_cmd = cpu_sub.add_parser("set", help="Set CPU register or flag.")
    set_cmd.add_argument(
        "target",
        choices=sorted(SET_REG_TARGETS.keys()),
        help="Target register/flag.",
    )
    set_cmd.add_argument("value", help="Value (hex: 0xNNNN, $NNNN, NNNN).")
    set_cmd.set_defaults(func=cmd_set)

    bbrk = cpu_sub.add_parser("bbrk", help="Query/set break-on-BRK mode.")
    bbrk.add_argument(
        "enabled",
        nargs="?",
        default=None,
        help="Optional state: on/off/1/0.",
    )
    bbrk.set_defaults(func=cmd_bbrk)

    cpu.set_defaults(func=cmd_get)


def cmd_get(args):
    async_to_sync(print_cpu_state(rpc_client(args.socket)))
    return 0


def cmd_set(args):
    target = SET_REG_TARGETS[args.target.lower()]
    value = parse_hex(args.value) & 0xFFFF
    payload = struct.pack("<BH", target, value)
    async_to_sync(rpc_client(args.socket).call(Command.SET_REG, payload))
    return 0


def cmd_bbrk(args):
    payload = None
    if args.enabled is not None:
        payload = struct.pack("<B", 1 if parse_bool(args.enabled) else 0)
    data = async_to_sync(rpc_client(args.socket).call(Command.BBRK, payload))
    if len(data) < 1:
        raise SystemExit("BBRK payload too short")
    state = "on" if data[0] else "off"
    print(f"bbrk={state}")
    return 0
