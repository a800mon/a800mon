import os

from ..rpc import CommandError


def color_enabled() -> bool:
    color_mode = os.getenv("A800MON_COLOR", "").strip().lower()
    term = os.getenv("TERM", "")
    if color_mode == "always":
        return True
    if color_mode == "never":
        return False
    return term not in (None, "", "dumb")


def format_toggle_badge(enabled: bool) -> str:
    text = "ON " if enabled else "OFF"
    badge = f" {text} "
    if not color_enabled():
        return badge
    if enabled:
        return f"\x1b[42;30m{badge}\x1b[0m"
    return f"\x1b[41;97;1m{badge}\x1b[0m"


def format_error(code: str, message: str) -> str:
    badge = f" {code} "
    if color_enabled():
        return f"\x1b[41;97;1m{badge}\x1b[0m {message}"
    return f"[{code}] {message}"


def format_rpc_error(ex) -> str:
    if isinstance(ex, CommandError):
        code = str(ex.status)
        message = (
            ex.data.decode("utf-8", errors="replace").strip() if ex.data else str(ex)
        )
        return format_error(code, message)
    return format_error("ERR", str(ex))


def format_capability_lines(cap_ids, capabilities):
    enabled = {cap_id & 0xFFFF for cap_id in cap_ids}
    known = set()
    lines = []
    for cap_id, desc in capabilities:
        known.add(cap_id)
        lines.append(f"{format_toggle_badge(cap_id in enabled)} {desc}")
    for cap_id in sorted(cap_id for cap_id in enabled if cap_id not in known):
        lines.append(
            f"{format_toggle_badge(True)} Unknown capability 0x{cap_id:04X}"
        )
    return lines
