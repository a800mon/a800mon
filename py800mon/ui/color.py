import curses
import enum


def init_color_pairs():
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_RED)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(6, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(8, curses.COLOR_BLUE, curses.COLOR_BLACK)


class Color(enum.Enum):
    ADDRESS = (1, curses.A_BOLD | curses.A_DIM)
    TEXT = (0, 0)
    WINDOW_TITLE = (0, curses.A_DIM)
    ERROR = (2, curses.A_BLINK)
    TOPBAR = (0, curses.A_REVERSE)
    FOCUS = (3, curses.A_BOLD)
    APPMODE = (4, curses.A_BOLD | curses.A_REVERSE | curses.A_DIM)
    APPMODE_DEBUG = (6, curses.A_BOLD | curses.A_REVERSE | curses.A_DIM)
    APPMODE_SHUTDOWN = (5, curses.A_BOLD | curses.A_REVERSE | curses.A_DIM)
    SHORTCUT = (0, curses.A_REVERSE)
    TAG_ENABLED = (4, curses.A_REVERSE)
    MNEMONIC = (4, curses.A_BOLD)
    COMMENT = (7, curses.A_DIM)
    UNUSED = (8, curses.A_DIM)
    INPUT_INVALID = (5, curses.A_BOLD)

    def attr(self):
        return curses.color_pair(self.value[0]) | self.value[1]
