import dataclasses

from .memorymap import lookup_symbol

FLOW_MNEMONICS = {
    "JMP",
    "JSR",
    "BCC",
    "BCS",
    "BEQ",
    "BMI",
    "BNE",
    "BPL",
    "BVC",
    "BVS",
    "BRA",
}


@dataclasses.dataclass(frozen=True)
class DecodedInstruction:
    addr: int
    size: int
    raw: bytes
    raw_text: str
    mnemonic: str
    operand: str
    comment: str
    asm_text: str
    addressing: str
    flow_target: int | None
    operand_addr_span: tuple[int, int] | None


def disasm_6502(start_addr: int, data: bytes) -> list[str]:
    lines = []
    for ins in disasm_6502_decoded(start_addr, data):
        lines.append(f"{ins.addr:04X}: {ins.raw_text:<8} {ins.asm_text}")
    return lines


def disasm_6502_one(start_addr: int, data: bytes) -> str:
    raw_text, asm_text = disasm_6502_one_parts(start_addr, data)
    return f"{raw_text:<8} {asm_text}"


def disasm_6502_one_parts(start_addr: int, data: bytes) -> tuple[str, str]:
    ins = disasm_6502_one_decoded(start_addr, data)
    if ins is None:
        return "", ""
    return ins.raw_text, ins.asm_text


def disasm_6502_one_decoded(start_addr: int, data: bytes) -> DecodedInstruction | None:
    decoded = disasm_6502_decoded(start_addr, data)
    if not decoded:
        return None
    return decoded[0]


def disasm_6502_decoded(start_addr: int, data: bytes) -> list[DecodedInstruction]:
    if not data:
        return []
    mpu, start = _build_mpu(start_addr, data)
    pc = start
    consumed = 0
    total = len(data)
    decoded = []

    while consumed < total:
        remain = total - consumed
        ins = _decode_instruction(mpu, pc, remain)
        size = ins.size
        if size < 1:
            size = 1
        if size > remain:
            size = remain

        raw = data[consumed: consumed + size]
        raw_text = _fmt_bytes(raw)
        ins = dataclasses.replace(ins, size=size, raw=raw, raw_text=raw_text)
        decoded.append(ins)

        consumed += size
        pc = (pc + size) & 0xFFFF

    return decoded


def _build_mpu(start_addr: int, data: bytes):
    try:
        from py65.devices.mpu6502 import MPU
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency: py65. Install project dependencies first."
        ) from exc

    mpu = MPU()
    start = start_addr & 0xFFFF
    for offset, byte in enumerate(data):
        mpu.memory[(start + offset) & 0xFFFF] = byte
    return mpu, start


def _decode_instruction(mpu, pc: int, remain: int) -> DecodedInstruction:
    opcode = mpu.ByteAt(pc)
    mnemonic, addressing = mpu.disassemble[opcode]
    mnemonic = str(mnemonic).upper()

    operand, size, comment_addr, addr_span = _decode_operand(mpu, pc, addressing)
    if size < 1:
        size = 1
    if size > remain:
        size = remain

    base_asm = mnemonic if not operand else f"{mnemonic} {operand}"
    comment = _comment_for_addr(comment_addr)
    asm_text = base_asm if not comment else f"{base_asm:<18} {comment}"

    flow_target = None
    if mnemonic in FLOW_MNEMONICS and comment_addr is not None:
        flow_target = comment_addr

    return DecodedInstruction(
        addr=pc & 0xFFFF,
        size=size,
        raw=b"",
        raw_text="",
        mnemonic=mnemonic,
        operand=operand,
        comment=comment,
        asm_text=asm_text,
        addressing=addressing,
        flow_target=flow_target,
        operand_addr_span=addr_span,
    )


def _decode_operand(mpu, pc: int, addressing: str):
    addr_fmt = mpu.ADDR_FORMAT
    byte_fmt = mpu.BYTE_FORMAT
    addr_mask = mpu.addrMask
    byte_mask = mpu.byteMask

    if addressing == "acc":
        return "A", 1, None, None
    if addressing == "abs":
        address = mpu.WordAt(pc + 1)
        token = ("$" + (addr_fmt % address)).upper()
        return token, 3, address, (0, len(token))
    if addressing == "abx":
        address = mpu.WordAt(pc + 1)
        token = ("$" + (addr_fmt % address)).upper()
        return f"{token},X", 3, address, (0, len(token))
    if addressing == "aby":
        address = mpu.WordAt(pc + 1)
        token = ("$" + (addr_fmt % address)).upper()
        return f"{token},Y", 3, address, (0, len(token))
    if addressing == "imm":
        value = mpu.ByteAt(pc + 1)
        return "#$" + (byte_fmt % value), 2, None, None
    if addressing == "imp":
        return "", 1, None, None
    if addressing == "ind":
        address = mpu.WordAt(pc + 1)
        token = ("$" + (addr_fmt % address)).upper()
        return f"({token})", 3, address, (1, 1 + len(token))
    if addressing == "iny":
        zp = mpu.ByteAt(pc + 1)
        token = ("$" + (byte_fmt % zp)).upper()
        return f"({token}),Y", 2, zp, (1, 1 + len(token))
    if addressing == "inx":
        zp = mpu.ByteAt(pc + 1)
        token = ("$" + (byte_fmt % zp)).upper()
        return f"({token},X)", 2, zp, (1, 1 + len(token))
    if addressing == "iax":
        address = mpu.WordAt(pc + 1)
        token = ("$" + (addr_fmt % address)).upper()
        return f"({token},X)", 3, address, (1, 1 + len(token))
    if addressing == "rel":
        opv = mpu.ByteAt(pc + 1)
        target = pc + 2
        if opv & (1 << (mpu.BYTE_WIDTH - 1)):
            target -= (opv ^ byte_mask) + 1
        else:
            target += opv
        target &= addr_mask
        token = ("$" + (addr_fmt % target)).upper()
        return token, 2, target, (0, len(token))
    if addressing == "zpi":
        zp = mpu.ByteAt(pc + 1)
        token = ("$" + (byte_fmt % zp)).upper()
        return f"({token})", 2, zp, (1, 1 + len(token))
    if addressing == "zpg":
        zp = mpu.ByteAt(pc + 1)
        token = ("$" + (byte_fmt % zp)).upper()
        return token, 2, zp, (0, len(token))
    if addressing == "zpx":
        zp = mpu.ByteAt(pc + 1)
        token = ("$" + (byte_fmt % zp)).upper()
        return f"{token},X", 2, zp, (0, len(token))
    if addressing == "zpy":
        zp = mpu.ByteAt(pc + 1)
        token = ("$" + (byte_fmt % zp)).upper()
        return f"{token},Y", 2, zp, (0, len(token))
    raise NotImplementedError(f"Addressing mode: {addressing!r}")


def _fmt_bytes(raw: bytes) -> str:
    return " ".join(f"{b:02X}" for b in raw)


def _comment_for_addr(addr: int | None) -> str:
    if addr is None:
        return ""
    symbol = lookup_symbol(addr & 0xFFFF)
    if not symbol:
        return ""
    return f";{symbol}"
