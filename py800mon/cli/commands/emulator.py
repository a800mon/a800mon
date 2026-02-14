import sys

from ...emulator import EMULATOR_CAPABILITIES
from ...rpc import Command
from ..common import (
    async_to_sync,
    rpc_client,
)
from ..utils import format_capability_lines


def register(subparsers):
    emulator = subparsers.add_parser(
        "emulator",
        aliases=["e"],
        help="Emulator control commands.",
    )
    emulator_sub = emulator.add_subparsers(dest="emulator_cmd", metavar="subcmd")

    reboot = emulator_sub.add_parser("reboot", help="Reboot emulation.")
    mode = reboot.add_mutually_exclusive_group()
    mode.add_argument("--cold", action="store_true", help="Cold start.")
    mode.add_argument("--warm", action="store_true", help="Warm start (default).")
    reboot.set_defaults(func=cmd_reboot)

    status = emulator_sub.add_parser("status", help="Get status.")
    status.set_defaults(func=cmd_status)

    stop = emulator_sub.add_parser("stop", help="Stop emulator.")
    stop.set_defaults(func=cmd_stop)

    restart = emulator_sub.add_parser("restart", help="Restart emulator.")
    restart.set_defaults(func=cmd_restart)

    features = emulator_sub.add_parser("features", help="Show emulator capabilities.")
    features.set_defaults(func=cmd_features)

    emulator.set_defaults(func=cmd_status)


def cmd_reboot(args):
    command = Command.COLDSTART if args.cold else Command.WARMSTART
    async_to_sync(rpc_client(args.socket).call(command))
    return 0


def cmd_status(args):
    st = async_to_sync(rpc_client(args.socket).status())
    paused = "yes" if st.paused else "no"
    crashed = "yes" if st.crashed else "no"
    sys.stdout.write(
        "paused=%s crashed=%s emu_ms=%d reset_ms=%d state_seq=%d\n"
        % (paused, crashed, st.emu_ms, st.reset_ms, st.state_seq)
    )
    return 0


def cmd_stop(args):
    async_to_sync(rpc_client(args.socket).call(Command.STOP_EMULATOR))
    return 0


def cmd_restart(args):
    async_to_sync(rpc_client(args.socket).call(Command.RESTART_EMULATOR))
    return 0


def cmd_features(args):
    caps = async_to_sync(rpc_client(args.socket).build_features())
    for line in format_capability_lines(caps, EMULATOR_CAPABILITIES):
        sys.stdout.write(line + "\n")
    return 0
