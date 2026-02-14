import sys

from ...rpc import Command
from ..common import async_to_sync, rpc_client


def register(subparsers):
    rpc = subparsers.add_parser("rpc", help="RPC transport commands.")
    rpc_sub = rpc.add_subparsers(dest="rpc_cmd", metavar="subcmd")
    rpc_sub.required = True

    ping = rpc_sub.add_parser("ping", help="Ping RPC server.")
    ping.set_defaults(func=cmd_ping)


def cmd_ping(args):
    data = async_to_sync(rpc_client(args.socket).call(Command.PING))
    if data:
        sys.stdout.buffer.write(data)
    return 0
