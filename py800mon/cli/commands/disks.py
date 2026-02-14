import struct

from ...rpc import Command
from ..common import async_to_sync, rpc_client


def register(subparsers):
    disk = subparsers.add_parser("disk", help="Disk commands.")
    disk_sub = disk.add_subparsers(dest="disk_cmd", metavar="subcmd")
    disk_sub.required = True

    remove = disk_sub.add_parser("remove", help="Remove disk(s).")
    remove.add_argument(
        "number",
        nargs="?",
        type=int,
        default=None,
        help="Optional disk number.",
    )
    remove.add_argument(
        "--all",
        action="store_true",
        help="Remove all disks.",
    )
    remove.set_defaults(func=cmd_remove)


def cmd_remove(args):
    if args.all and args.number is not None:
        raise SystemExit("Use either --all or <number>, not both.")

    payload = None
    if args.number is not None:
        if args.number < 1 or args.number > 255:
            raise SystemExit("Disk number must be in range 1..255.")
        payload = struct.pack("<B", args.number)

    async_to_sync(rpc_client(args.socket).call(Command.REMOVE_DISKS, payload))
    return 0
