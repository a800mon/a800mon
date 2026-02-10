def disasm_6502(start_addr: int, data: bytes) -> list[str]:
    dis, start = _build_disassembler(start_addr, data)
    lines = []
    pc = start
    consumed = 0
    total = len(data)

    while consumed < total:
        size, text = _decode_instruction(dis, pc)
        if size < 1:
            size = 1
        remain = total - consumed
        if size > remain:
            size = remain

        raw = data[consumed: consumed + size]
        lines.append(f"{pc:04X}: {_fmt_bytes(raw):<8} {text}")

        consumed += size
        pc = (pc + size) & 0xFFFF

    return lines


def disasm_6502_one(start_addr: int, data: bytes) -> str:
    if not data:
        return ""
    dis, start = _build_disassembler(start_addr, data)
    size, text = _decode_instruction(dis, start)
    if size < 1:
        size = 1
    raw = data[:size]
    return f"{_fmt_bytes(raw):<8} {text}"


def _build_disassembler(start_addr: int, data: bytes):
    try:
        from py65.devices.mpu6502 import MPU
        from py65.disassembler import Disassembler
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency: py65. Install project dependencies first."
        ) from exc

    mpu = MPU()
    start = start_addr & 0xFFFF
    for offset, byte in enumerate(data):
        mpu.memory[(start + offset) & 0xFFFF] = byte
    return Disassembler(mpu), start


def _decode_instruction(dis, addr: int) -> tuple[int, str]:
    decoded = dis.instruction_at(addr)

    if isinstance(decoded, tuple):
        left, right = decoded[0], decoded[1]
        if isinstance(left, int):
            return left, str(right)
        if isinstance(right, int):
            return right, str(left)

    return 1, str(decoded)


def _fmt_bytes(raw: bytes) -> str:
    return " ".join(f"{b:02X}" for b in raw)
