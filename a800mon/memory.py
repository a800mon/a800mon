import json

from .atascii import ATASCII, screen_to_atascii


def dump_memory_raw(buffer: bytes, use_atascii: bool = False) -> bytes:
    if not use_atascii:
        return buffer
    return bytes(screen_to_atascii(b) & 0xFF for b in buffer)


def dump_memory_json(
    address: int, buffer: bytes, use_atascii: bool = False
) -> str:
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
        chunk = buffer[offset: offset + per_line]
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
