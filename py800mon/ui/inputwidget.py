import curses

from ..app import VisualComponent
from .color import Color


class InputWidget(VisualComponent):
    def __init__(
        self,
        window,
        color: Color = Color.TEXT,
        max_length: int | None = None,
        on_enter=None,
        on_change=None,
    ):
        super().__init__(window)
        self.color = color
        self.max_length = max_length
        self.on_enter = on_enter
        self.on_change = on_change
        self.invalid = False
        self._buffer = ""

    @property
    def buffer(self) -> str:
        return self._buffer

    def activate(self, initial_buffer: str = ""):
        text = str(initial_buffer)
        if self.max_length is not None:
            text = text[: self.max_length]
        self._buffer = text

    def deactivate(self):
        self.invalid = False
        self._buffer = ""

    def set_invalid(self, invalid: bool):
        self.invalid = invalid

    def _normalize_char(self, ch: str) -> str:
        return ch

    def _is_char_allowed(self, ch: str) -> bool:
        code = ord(ch)
        return 32 <= code <= 126

    def _to_value(self):
        return self._buffer

    def set_buffer(self, value: str) -> None:
        text = str(value)
        if self.max_length is not None:
            text = text[: self.max_length]
        if text == self._buffer:
            return
        self._buffer = text
        self.emit_change()

    def _append_char(self, ch: int) -> None:
        if ch < 0 or ch > 255:
            return
        char = self._normalize_char(chr(ch))
        if not self._is_char_allowed(char):
            return
        if self.max_length is not None and len(self._buffer) >= self.max_length:
            return
        self._buffer += char
        self.emit_change()

    def _backspace(self) -> None:
        if not self._buffer:
            return
        self._buffer = self._buffer[:-1]
        self.emit_change()

    def handle_key(self, ch: int) -> bool:
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self._backspace()
            return True
        before = self._buffer
        self._append_char(ch)
        return self._buffer != before

    def emit_change(self):
        if not self.on_change:
            return
        self.on_change(self._to_value())

    def emit_enter(self):
        if not self.on_enter:
            return
        self.on_enter(self._to_value())

    def render(self, force_redraw=False):
        self.window.cursor = 0, 0
        color = Color.INPUT_INVALID if self.invalid else self.color
        attr = color.attr() | curses.A_REVERSE
        text = self._buffer
        self.window.print(text, attr=attr)
        self.window.fill_to_eol(attr=attr)
        cursor_x = len(text)
        if cursor_x > self.window._iw - 1:
            cursor_x = self.window._iw - 1
        if cursor_x < 0:
            cursor_x = 0
        self.window.cursor = (cursor_x, 0)
