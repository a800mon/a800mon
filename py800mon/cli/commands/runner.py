import os

from ...rpc import Command
from ..common import async_to_sync, rpc_client


def register(subparsers):
    run = subparsers.add_parser("run", help="Run a file via RPC.")
    run.add_argument("path", help="Path to file.")
    run.set_defaults(func=cmd_run)


def cmd_run(args):
    path = os.path.realpath(os.path.expanduser(args.path))
    async_to_sync(rpc_client(args.socket).call(Command.RUN, path.encode("utf-8")))
    return 0
