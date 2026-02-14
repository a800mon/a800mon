import argparse
import sys

from ..monitor.main import run as run_monitor
from ..rpc import RpcException
from .commands import (
    breakpoints,
    cartrige,
    cpu,
    debugger,
    disks,
    emulator,
    memory,
    rpc,
    runner,
    screen,
    tape,
    trainer,
)
from .utils import format_rpc_error


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="py800mon")
    parser.add_argument(
        "-s",
        "--socket",
        default="/tmp/atari.sock",
        help="Path to Atari800 monitor socket.",
    )
    subparsers = parser.add_subparsers(dest="cmd", metavar="cmd")

    monitor = subparsers.add_parser("monitor", help="Run the curses monitor UI.")
    monitor.set_defaults(func=cmd_monitor)

    runner.register(subparsers)
    debugger.register(subparsers)
    emulator.register(subparsers)
    breakpoints.register(subparsers)
    memory.register(subparsers)
    cpu.register(subparsers)
    rpc.register(subparsers)
    cartrige.register(subparsers)
    tape.register(subparsers)
    disks.register(subparsers)
    screen.register(subparsers)
    trainer.register(subparsers)

    return parser.parse_args(argv)


def cmd_monitor(args):
    run_monitor(args.socket)
    return 0


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.cmd is None:
            return cmd_monitor(args)
        return args.func(args)
    except RpcException as ex:
        sys.stderr.write(format_rpc_error(ex) + "\n")
        return 1
