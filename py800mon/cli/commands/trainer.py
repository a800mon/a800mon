import sys

from ...atari.memory import parse_hex, parse_hex_u8, parse_positive_int
from ...trainer import Trainer
from ..common import async_to_sync, rpc_client


def register(subparsers):
    trainer = subparsers.add_parser("trainer", help="Interactive value trainer.")
    trainer.add_argument("start", help="Start address (hex: 0xNNNN, $NNNN, NNNN).")
    trainer.add_argument("stop", help="Stop address (hex: 0xNNNN, $NNNN, NNNN).")
    trainer.add_argument("value", help="Initial byte value (hex: 00..FF).")
    trainer.set_defaults(func=cmd_trainer)


def _trainer_read_memory(socket_path: str, start: int, length: int):
    async def run():
        rpc = rpc_client(socket_path)
        return await rpc.read_memory(start, length)

    return async_to_sync(run())


def _trainer_parse_value(value: str):
    try:
        return parse_hex_u8(value)
    except ValueError as ex:
        raise ValueError("Invalid trainer value (hex 00..FF).") from ex


def _trainer_parse_limit(value: str):
    return parse_positive_int(value)


def _trainer_print(trainer, limit: int):
    total = len(trainer.candidates)
    sys.stdout.write(f"matches={total}\n")
    if total == 0:
        return
    rows = trainer.rows(limit)
    sys.stdout.write("idx  addr  val\n")
    for idx, (addr, value) in enumerate(rows, start=1):
        sys.stdout.write(f"{idx:03d}  {addr:04X}  {value:02X}\n")
    if len(rows) < total:
        sys.stdout.write(f"... {total - len(rows)} more\n")


def _trainer_print_single_auto(trainer):
    rows = trainer.rows(1)
    if not rows:
        return
    sys.stdout.write("idx  addr  val\n")
    addr, value = rows[0]
    sys.stdout.write(f"001  {addr:04X}  {value:02X}\n")


def cmd_trainer(args):
    start = parse_hex(args.start) & 0xFFFF
    stop = parse_hex(args.stop) & 0xFFFF
    if stop < start:
        raise SystemExit("Stop address must be >= start address.")
    try:
        value = _trainer_parse_value(args.value)
    except ValueError as ex:
        raise SystemExit(str(ex)) from ex

    trainer = Trainer(start, stop)
    trainer.bind_reader(
        lambda addr, length: _trainer_read_memory(args.socket, addr, length)
    )
    matches = trainer.start(value)

    sys.stdout.write(
        f"range={start:04X}-{stop:04X} initial={value:02X} matches={matches}\n"
    )
    sys.stdout.write("commands: c <value>, nc, p [limit], q\n")
    if not matches:
        return 0
    if matches == 1:
        _trainer_print_single_auto(trainer)

    while True:
        try:
            line = input("trainer> ").strip()
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

        if cmd == "q":
            return 0
        if cmd == "p":
            if len(parts) > 2:
                sys.stdout.write("Usage: p [limit]\n")
                continue
            try:
                limit = 20 if len(parts) != 2 else _trainer_parse_limit(parts[1])
            except ValueError as ex:
                sys.stdout.write(str(ex) + "\n")
                continue
            _trainer_print(trainer, limit)
            continue
        if cmd == "nc":
            if len(parts) != 1:
                sys.stdout.write("Usage: nc\n")
                continue
            matches = trainer.not_changed()
            sys.stdout.write(f"matches={matches}\n")
            if not matches:
                return 0
            if matches == 1:
                _trainer_print_single_auto(trainer)
            continue
        if cmd == "c":
            if len(parts) != 2:
                sys.stdout.write("Usage: c <value>\n")
                continue
            try:
                target = _trainer_parse_value(parts[1])
            except ValueError as ex:
                sys.stdout.write(str(ex) + "\n")
                continue
            matches = trainer.changed(target)
            sys.stdout.write(f"matches={matches}\n")
            if not matches:
                return 0
            if matches == 1:
                _trainer_print_single_auto(trainer)
            continue

        sys.stdout.write("Unknown command. Use: c <value>, nc, p [limit], q\n")
