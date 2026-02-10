import curses

from .actions import Actions
from .app import InputComponent, VisualComponent
from .appstate import state
from .ui import Color


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
        self._buffer = ""

    @property
    def buffer(self) -> str:
        return self._buffer

    def activate(self, initial_buffer: str = ""):
        self._buffer = ""
        self.set_buffer(initial_buffer)

    def deactivate(self):
        self._buffer = ""

    def _normalize_char(self, ch: str) -> str:
        return ch

    def _is_char_allowed(self, ch: str) -> bool:
        code = ord(ch)
        return 32 <= code <= 126

    def _to_value(self):
        return self._buffer

    def set_buffer(self, value: str) -> bool:
        text = str(value)
        if self.max_length is not None:
            text = text[: self.max_length]
        if text == self._buffer:
            return False
        self._buffer = text
        self.emit_change()
        return True

    def append_char(self, ch: int) -> bool:
        if ch < 0 or ch > 255:
            return False
        char = chr(ch)
        char = self._normalize_char(char)
        if not self._is_char_allowed(char):
            return False
        if self.max_length is not None and len(self._buffer) >= self.max_length:
            return False
        self._buffer += char
        self.emit_change()
        return True

    def backspace(self) -> bool:
        if not self._buffer:
            return False
        self._buffer = self._buffer[:-1]
        self.emit_change()
        return True

    def emit_change(self):
        if self.on_change is None:
            return
        self.on_change(self._to_value())

    def emit_enter(self):
        if self.on_enter is None:
            return
        self.on_enter(self._to_value())

    def render(self, force_redraw=False):
        self.window.cursor = 0, 0
        attr = self.color.attr() | curses.A_REVERSE
        text = state.input_buffer
        self.window.print(text, attr=attr)
        self.window.fill_to_eol(attr=attr)
        cursor_x = len(text)
        if cursor_x > self.window._iw - 1:
            cursor_x = self.window._iw - 1
        if cursor_x < 0:
            cursor_x = 0
        self.window.cursor = (cursor_x, 0)


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
        return int(self._buffer, 16)

    def render(self, force_redraw=False):
        self.window.cursor = 0, 0
        attr = self.color.attr() | curses.A_REVERSE
        text = state.input_buffer[-4:].upper().rjust(4, "0")
        self.window.print(text, attr=attr)
        self.window.fill_to_eol(attr=attr)
        self.window.cursor = (4, 0)


class InputWidgetManager(InputComponent):
    def __init__(self, dispatcher, rebuild_screen):
        self._dispatcher = dispatcher
        self._rebuild_screen = rebuild_screen
        self._active_widget = None
        self._snapshot = ""
        self._replace_on_next_input = False

    def open(self, widget: InputWidget, initial_buffer: str):
        self._active_widget = widget
        self._snapshot = str(initial_buffer)
        self._replace_on_next_input = True
        widget.activate(initial_buffer)
        self._dispatcher.dispatch(Actions.SET_INPUT_BUFFER, widget.buffer)
        self._dispatcher.dispatch(Actions.SET_INPUT_FOCUS, True)
        widget.window.visible = True
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        self._rebuild_screen()

    def _close(self):
        if self._active_widget is None:
            return
        self._dispatcher.dispatch(Actions.SET_INPUT_FOCUS, False)
        self._active_widget.window.visible = False
        self._active_widget.deactivate()
        self._active_widget = None
        self._snapshot = ""
        self._replace_on_next_input = False
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self._rebuild_screen()

    def _commit(self):
        if self._active_widget is None:
            return
        self._dispatcher.dispatch(Actions.SET_INPUT_BUFFER, self._active_widget.buffer)
        self._active_widget.emit_enter()
        self._close()

    def _cancel(self):
        if self._active_widget is None:
            return
        self._active_widget.set_buffer(self._snapshot)
        self._dispatcher.dispatch(Actions.SET_INPUT_BUFFER, self._snapshot)
        self._close()

    def handle_input(self, ch):
        if not state.input_focus or self._active_widget is None:
            return False

        if ch == 27:
            self._cancel()
            return True

        if ch in (10, 13, curses.KEY_ENTER):
            self._commit()
            return True

        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self._replace_on_next_input = False
            if self._active_widget.backspace():
                self._dispatcher.dispatch(
                    Actions.SET_INPUT_BUFFER, self._active_widget.buffer
                )
            return True

        if self._replace_on_next_input:
            self._active_widget.set_buffer("")
            self._dispatcher.dispatch(Actions.SET_INPUT_BUFFER, "")
            self._replace_on_next_input = False

        if self._active_widget.append_char(ch):
            self._dispatcher.dispatch(
                Actions.SET_INPUT_BUFFER, self._active_widget.buffer
            )
            return True

        return True
