import json

from .atascii import ATASCII, screen_to_atascii


def dump_memory_raw(buffer: bytes, use_atascii: bool = False) -> bytes:
    if not use_atascii:
        return buffer
    return bytes(screen_to_atascii(b) & 0xFF for b in buffer)


def dump_memory_json(address: int, buffer: bytes, use_atascii: bool = False) -> str:
    data = dump_memory_raw(buffer, use_atascii=use_atascii)
    payload = {"address": address, "buffer": list(data)}
    return json.dumps(payload)


def dump_memory_human(
    address: int,
    length: int,
    buffer: bytes,
    use_atascii: bool = False,
    columns: int | None = None,
    show_hex: bool = True,
    show_ascii: bool = True,
) -> str:
    lines = []
    per_line = 16 if columns is None else max(1, int(columns))
    length = max(0, int(length))

    for offset in range(0, length, per_line):
        addr = (address + offset) & 0xFFFF
        chunk = buffer[offset : offset + per_line]
        parts = [f"{addr:04X}:"]

        if show_hex:
            hex_width = per_line * 3 - 1
            parts.append(" ".join(f"{b:02X}" for b in chunk).ljust(hex_width))

        if show_ascii:
            if use_atascii:
                ascii_bytes = "".join(
                    ATASCII[screen_to_atascii(b) & 0x7F] for b in chunk
                )
            else:
                ascii_bytes = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
            parts.append(ascii_bytes)

        lines.append("  ".join(parts))

    return "\n".join(lines)


def dump_memory_human_rows(
    rows: list[tuple[int, bytes]],
    use_atascii: bool = False,
    show_hex: bool = True,
    show_ascii: bool = True,
) -> str:
    if not rows:
        return ""
    draw_width = 0
    for _addr, chunk in rows:
        if len(chunk) > draw_width:
            draw_width = len(chunk)
    lines = []
    for addr, chunk in rows:
        parts = [f"{addr:04X}:"]
        if show_hex:
            tokens = [f"{b:02X}" for b in chunk]
            if len(chunk) < draw_width:
                tokens.extend([".."] * (draw_width - len(chunk)))
            parts.append(" ".join(tokens))
        if show_ascii:
            if use_atascii:
                ascii_bytes = "".join(
                    ATASCII[screen_to_atascii(b) & 0x7F] for b in chunk
                )
            else:
                ascii_bytes = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
            if len(chunk) < draw_width:
                pad = draw_width - len(chunk)
                left = pad // 2
                right = pad - left
                ascii_bytes = "·" * left + ascii_bytes + "·" * right
            parts.append(ascii_bytes)
        lines.append("  ".join(parts))
    return "\n".join(lines)


def parse_hex(value: str) -> int:
    text = value.strip().lower()
    if text.startswith("$"):
        text = text[1:]
    if text.startswith("0x"):
        text = text[2:]
    return int(text, 16)


def parse_hex_u8(value: str) -> int:
    number = parse_hex(value)
    if number < 0 or number > 0xFF:
        raise ValueError(f"Hex value out of range (00..FF): {value}")
    return number


def parse_hex_u16(value: str) -> int:
    number = parse_hex(value)
    if number < 0 or number > 0xFFFF:
        raise ValueError(f"Hex value out of range (0000..FFFF): {value}")
    return number


def parse_hex_values(values: list[str]) -> bytes:
    out = bytearray()
    for value in values:
        number = parse_hex_u16(value)
        if number <= 0xFF:
            out.append(number)
        else:
            out.append(number & 0xFF)
            out.append((number >> 8) & 0xFF)
    return bytes(out)


def parse_hex_payload(text: str) -> bytes:
    normalized = text.replace(",", " ")
    parts = normalized.split()
    if not parts:
        raise ValueError("Hex payload is empty.")
    if len(parts) > 1:
        return bytes(parse_hex_u8(value) for value in parts)
    value = parts[0].strip().lower()
    if value.startswith("$"):
        value = value[1:]
    if value.startswith("0x"):
        value = value[2:]
    if not value:
        raise ValueError("Hex payload is empty.")
    if len(value) % 2 != 0:
        raise ValueError("Hex payload must have an even number of digits.")
    try:
        return bytes.fromhex(value)
    except ValueError as ex:
        raise ValueError("Invalid hex payload.") from ex


def parse_positive_int(value: str) -> int:
    text = value.strip().lower()
    if text.startswith("$"):
        text = "0x" + text[1:]
    number = int(text, 0)
    if number <= 0:
        raise ValueError("Limit must be > 0.")
    return number
