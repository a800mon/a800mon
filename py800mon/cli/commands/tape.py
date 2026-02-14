from ...rpc import Command
from ..common import async_to_sync, rpc_client


def register(subparsers):
    tape = subparsers.add_parser("tape", help="Tape commands.")
    tape_sub = tape.add_subparsers(dest="tape_cmd", metavar="subcmd")
    tape_sub.required = True

    remove = tape_sub.add_parser("remove", help="Remove cassette.")
    remove.set_defaults(func=cmd_remove)


def cmd_remove(args):
    async_to_sync(rpc_client(args.socket).call(Command.REMOVE_TAPE))
    return 0
