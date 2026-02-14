import curses

from ..atari.memory import parse_hex_u16
from .color import Color
from .inputwidget import InputWidget


class AddressInputWidget(InputWidget):
    def __init__(self, *args, **kwargs):
        kwargs["max_length"] = 4
        super().__init__(*args, **kwargs)

    def _normalize_char(self, ch: str) -> str:
        return ch.upper()

    def _is_char_allowed(self, ch: str) -> bool:
        return ("0" <= ch <= "9") or ("A" <= ch <= "F")

    def _to_value(self):
        if not self._buffer:
            return None
        return parse_hex_u16(self._buffer)

    def render(self, force_redraw=False):
        self.window.cursor = 0, 0
        color = Color.INPUT_INVALID if self.invalid else self.color
        attr = color.attr() | curses.A_REVERSE
        text = self._buffer[-4:].upper().rjust(4, "0")
        self.window.print(text, attr=attr)
        self.window.fill_to_eol(attr=attr)
        self.window.cursor = (4, 0)
