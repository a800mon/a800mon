import sys

from ...rpc import Command
from ..common import (
    EMULATOR_CAPABILITIES,
    async_to_sync,
    format_on_off_badge,
    rpc_client,
)


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
    enabled = set(caps)
    known = set()
    for cap_id, desc in EMULATOR_CAPABILITIES:
        known.add(cap_id)
        badge = format_on_off_badge(cap_id in enabled)
        sys.stdout.write(f"{badge} {desc}\n")
    for cap_id in sorted(v for v in enabled if v not in known):
        badge = format_on_off_badge(True)
        sys.stdout.write(f"{badge} Unknown capability 0x{cap_id:04X}\n")
    return 0
