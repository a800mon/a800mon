import curses
import enum

from .color import Color


class DialogWidget:
    def __init__(
        self,
        window,
        title: str = "",
        decision: str = "YES",
        decision_color=None,
    ):
        self.window = window
        self.title = str(title)
        self.decision = str(decision)
        self.decision_color = (
            Color.INPUT_INVALID if decision_color is None else decision_color
        )
        self.active = False

    def activate(self, title: str, decision: str = "YES"):
        self.title = str(title)
        self.decision = str(decision)
        self.active = True

    def deactivate(self):
        self.active = False

    def handle_input(self, ch):
        if not self.active:
            return DialogInput.NONE
        if ch == 27:
            self.deactivate()
            return DialogInput.CANCEL
        if ch in (10, 13, curses.KEY_ENTER):
            self.deactivate()
            return DialogInput.CONFIRM
        return DialogInput.CONSUME

    def render(self):
        if not self.active:
            return
        self.window.cursor = (0, 0)
        base_attr = Color.TEXT.attr() | curses.A_REVERSE
        decision_attr = self.decision_color.attr() | curses.A_REVERSE
        title = self.title.strip()
        decision = f" {self.decision.strip()} "
        self.window.fill_to_eol(attr=base_attr)
        if title:
            self.window.cursor = (0, 0)
            self.window.print(title, attr=base_attr)
        start = self.window._iw - len(decision)
        if start < 0:
            start = 0
        self.window.cursor = (start, 0)
        self.window.print(decision, attr=decision_attr)


class DialogInput(enum.IntEnum):
    NONE = 0
    CANCEL = 1
    CONFIRM = 2
    CONSUME = 3
