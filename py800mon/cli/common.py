import asyncio
import sys

from ..datastructures import CpuState
from ..atari.memory import dump_memory_human, dump_memory_json, dump_memory_raw
from ..rpc import RpcClient
from ..socket import SocketTransport

SET_REG_TARGETS = {
    "pc": 1,
    "a": 2,
    "x": 3,
    "y": 4,
    "s": 5,
    "n": 6,
    "v": 7,
    "d": 8,
    "i": 9,
    "z": 10,
    "c": 11,
}

SEARCH_MODE_BYTES = 1


def rpc_client(socket_path):
    return RpcClient(SocketTransport(socket_path))


def async_to_sync(awaitable):
    return asyncio.run(awaitable)


async def print_cpu_state(rpc):
    ypos, xpos, pc, a, x, y, s, p = await rpc.cpu_state()
    cpu = CpuState(ypos=ypos, xpos=xpos, pc=pc, a=a, x=x, y=y, s=s, p=p)
    sys.stdout.write(repr(cpu) + "\n")


def parse_bool(value):
    text = value.strip().lower()
    if text in ("1", "on", "true", "yes"):
        return True
    if text in ("0", "off", "false", "no"):
        return False
    raise SystemExit(f"Invalid boolean value: {value}")


def fmt_bytes(values):
    return " ".join(f"{value:02X}" for value in values)


def dump_memory_output(address, length, data, args, columns):
    if columns is not None and (args.raw or args.json):
        raise SystemExit("--columns is only valid for formatted output")

    if args.raw:
        raw = dump_memory_raw(data, use_atascii=args.atascii)
        if raw:
            sys.stdout.buffer.write(raw)
        return

    if args.json:
        sys.stdout.write(
            dump_memory_json(address, data, use_atascii=args.atascii) + "\n"
        )
        return

    sys.stdout.write(
        dump_memory_human(
            address=address,
            length=length,
            buffer=data,
            use_atascii=args.atascii,
            columns=columns,
            show_hex=not args.nohex,
            show_ascii=not args.noascii,
        )
        + "\n"
    )
