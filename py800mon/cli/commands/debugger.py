import asyncio
import struct
import sys
import time

from ...atari.disasm import disasm_6502_one
from ...atari.memory import parse_hex
from ...rpc import Command, RpcException
from ..common import (
    async_to_sync,
    print_cpu_state,
    rpc_client,
)
from ..utils import format_rpc_error


HELP_TEXT = (
    "commands: pause(p), step(s), stepvbl(v), "
    "untilret(r [pc]), continue(c), stack(t), q"
)


def register(subparsers):
    debug = subparsers.add_parser("debug", aliases=["d"], help="Debugger commands.")
    debug_sub = debug.add_subparsers(dest="debug_cmd", metavar="subcmd")

    shell = debug_sub.add_parser(
        "shell",
        aliases=["s"],
        help="Interactive debugger session.",
    )
    shell.set_defaults(func=cmd_shell)

    jumps = debug_sub.add_parser(
        "jumps",
        aliases=["j"],
        help="Show jump history ring.",
    )
    jumps.set_defaults(func=cmd_jumps)

    history = debug_sub.add_parser(
        "history",
        aliases=["h"],
        help="Show CPU execution history.",
    )
    history.add_argument(
        "-n",
        "--count",
        type=int,
        default=None,
        help="Limit output to last N entries.",
    )
    history.set_defaults(func=cmd_history)

    debug.set_defaults(func=cmd_shell)


async def _pause_rpc(rpc) -> bool:
    await rpc.call(Command.PAUSE)
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        st = await rpc.status()
        if st.paused:
            return True
        await rpc.call(Command.PAUSE)
        await rpc.call(Command.PING)
    return False


async def _continue_rpc(rpc) -> bool:
    await rpc.call(Command.CONTINUE)
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        st = await rpc.status()
        if not st.paused:
            return True
        await rpc.call(Command.PING)
    return False


async def _step_rpc(rpc) -> None:
    await rpc.call(Command.STEP)
    await print_cpu_state(rpc)


async def _step_vblank_rpc(rpc) -> None:
    await rpc.call(Command.STEP_VBLANK)
    await print_cpu_state(rpc)


async def _untilret_rpc(rpc, pc) -> None:
    payload = None if pc is None else struct.pack("<H", pc & 0xFFFF)
    await rpc.call(Command.RUN_UNTIL_RETURN, payload)
    await print_cpu_state(rpc)


def _print_stack_state(state):
    sys.stdout.write(f"S={state.s:02X} count={len(state.entries)}\n")
    for entry in state.entries:
        sys.stdout.write(f"01{entry.stack_off:02X}: {entry.value:02X}\n")


def cmd_shell(args):
    async def run():
        rpc = rpc_client(args.socket)
        sys.stdout.write(HELP_TEXT + "\n")
        while True:
            try:
                line = (await asyncio.to_thread(input, "debug> ")).strip()
            except EOFError:
                sys.stdout.write("\n")
                return 0
            except KeyboardInterrupt:
                sys.stdout.write("\n")
                return 0

            if not line:
                continue
            parts = line.split()
            cmd = parts[0].lower()

            if cmd in ("q", "quit", "exit"):
                return 0
            if cmd in ("help", "?"):
                sys.stdout.write(HELP_TEXT + "\n")
                continue

            try:
                if cmd in ("pause", "p"):
                    if not await _pause_rpc(rpc):
                        sys.stdout.write(
                            "Pause requested but emulator is still running.\n"
                        )
                    else:
                        await print_cpu_state(rpc)
                    continue

                if cmd in ("step", "s"):
                    await _step_rpc(rpc)
                    continue

                if cmd in ("stepvbl", "v"):
                    await _step_vblank_rpc(rpc)
                    continue

                if cmd in ("untilret", "r"):
                    if len(parts) > 2:
                        sys.stdout.write("Usage: untilret [pc]\n")
                        continue
                    pc = None
                    if len(parts) == 2:
                        try:
                            pc = parse_hex(parts[1])
                        except ValueError as ex:
                            sys.stdout.write(str(ex) + "\n")
                            continue
                    await _untilret_rpc(rpc, pc)
                    continue

                if cmd in ("continue", "cont", "c"):
                    if not await _continue_rpc(rpc):
                        sys.stdout.write(
                            "Continue requested but emulator is still paused.\n"
                        )
                    continue

                if cmd in ("stack", "t"):
                    _print_stack_state(await rpc.stack())
                    continue
            except RpcException as ex:
                sys.stdout.write(format_rpc_error(ex) + "\n")
                continue

            sys.stdout.write("Unknown command. " + HELP_TEXT + "\n")

    return async_to_sync(run())


def cmd_jumps(args):
    state = async_to_sync(rpc_client(args.socket).jumps())
    for idx, pc in enumerate(state.pcs, start=1):
        sys.stdout.write(f"{idx:02d}: {pc:04X}\n")
    return 0


def cmd_history(args):
    entries = async_to_sync(rpc_client(args.socket).history())
    if args.count is not None:
        n = max(0, int(args.count))
        entries = entries[:n] if n else []
    entries = list(reversed(entries))
    for idx, entry in enumerate(entries, start=1):
        try:
            dis = disasm_6502_one(entry.pc, entry.opbytes)
        except RuntimeError:
            dis = f"{entry.op0:02X} {entry.op1:02X} {entry.op2:02X}"
        sys.stdout.write(
            f"{idx:03d} Y={entry.y:02X} X={entry.x:02X} PC={entry.pc:04X}  {dis}\n"
        )
    return 0
