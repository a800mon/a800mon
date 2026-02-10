import curses
import enum


class Screen:
    def __init__(self, scr, layout_initializer=None):
        self.scr = scr
        self.windows = []
        self.layout_initializer = layout_initializer
        self._initialized = False
        self.focused = None
        self.scr.nodelay(True)

    def initialize(self):
        curses.noecho()
        curses.cbreak()
        curses.set_escdelay(25)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.scr.keypad(True)
        self.scr.erase()
        if curses.has_colors():
            curses.start_color()
            init_color_pairs()
        self._initialized = True

    @property
    def size(self):
        h, w = self.scr.getmaxyx()
        return w, h

    def add(self, window):
        window.add_to_parent(self.scr)
        window._screen = self
        self.windows.append(window)

    def focus(self, window):
        old = self.focused
        if old is window:
            return
        self.focused = window
        if old and old.on_blur:
            old.on_blur()
        if window and window.on_focus:
            window.on_focus()
        if old:
            old.redraw()
        if window:
            window.redraw()

    def refresh(self):
        if not self._initialized:
            raise RuntimeError("Screen not initialized!")
        for window in self.windows:
            if not window.visible:
                continue
            window.refresh_if_dirty()
        self.scr.refresh()

    def get_input_char(self):
        ch = self.scr.getch()
        return ch

    def rebuild(self):
        self.scr.erase()
        if self.layout_initializer:
            self.layout_initializer(self)
        for window in self.windows:
            if window.visible:
                window.initialize()

    def update(self):
        if not self._initialized:
            raise RuntimeError("Screen not initialized!")
        self.refresh()
        curses.doupdate()


class Component:
    def __init__(self):
        self._dirty = True

    def refresh(self):
        self._do_refresh()

    def refresh_if_dirty(self):
        if self._dirty:
            self.refresh()
            self._dirty = False


class Window:
    def __init__(self, x=0, y=0, w=1, h=1, title=None, border=True):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self._iw = 0
        self._ih = 0
        self._border = border
        self.title = title
        self.parent = None
        self._screen = None
        self._visible = True
        self.reset_cursor_on_refresh = True
        self.on_focus = None
        self.on_blur = None

    @property
    def visible(self):
        return self._visible

    @visible.setter
    def visible(self, value):
        new_val = bool(value)
        if new_val == self._visible:
            return
        self._visible = new_val

    def add_to_parent(self, parent):
        if self.parent:
            raise RuntimeError("Window already has parent")
        self.parent = parent

    def initialize(self):
        if not self.parent:
            raise RuntimeError("Window has no parent!")

        ph, pw = self.parent.getmaxyx()
        rw = min(pw - self.x, self.w)
        rh = min(ph - self.y, self.h)
        if self._border:
            self.outer = self.parent.subwin(rh, rw, self.y, self.x)
            self.inner = self.outer.derwin(rh - 2, rw - 2, 1, 1)
        else:
            self.inner = self.parent.subwin(rh, rw, self.y, self.x)
        self._ih, self._iw = self.inner.getmaxyx()
        self.redraw()

    @property
    def cursor(self):
        y, x = self.inner.getyx()
        return x, y

    @cursor.setter
    def cursor(self, v):
        self.inner.move(v[1], v[0])

    def get_char(self, x, y):
        v = self.inner.inch(y, x)
        ch = v & 0xFF
        attr = v & ~0xFF
        return ch, attr

    def put_char(self, x, y, c, attr=0):
        win = self.inner
        cy, cx = win.getyx()
        win.addch(y, x, c, attr)
        win.move(cy, cx)

    def invert_char(self, x: int, y: int) -> None:
        cy, cx = self.inner.getyx()

        v = self.inner.inch(y, x)
        attr = v & curses.A_ATTRIBUTES

        if attr & curses.A_REVERSE:
            new_attr = attr & ~curses.A_REVERSE
        else:
            new_attr = attr | curses.A_REVERSE

        self.inner.chgat(y, x, 1, new_attr)
        self.inner.move(cy, cx)

    def redraw(self):
        if self._border:
            focus_attr = Color.WINDOW_TITLE.attr()
            if self._screen is not None and self._screen.focused is self:
                focus_attr = Color.FOCUS.attr()
            self.outer.attron(focus_attr)
            self.outer.box()
            self.outer.attroff(focus_attr)
            if self.title:
                self.outer.addstr(
                    0, 2, f" {self.title[: self._iw - 6]} ", focus_attr)
        self._dirty = True

    def set_title(self, title):
        if title == self.title:
            return
        self.title = title
        self.redraw_title()

    def redraw_title(self):
        if not self._border or not hasattr(self, "outer"):
            self._dirty = True
            return
        focus_attr = Color.WINDOW_TITLE.attr()
        if self._screen is not None and self._screen.focused is self:
            focus_attr = Color.FOCUS.attr()
        self.outer.attron(focus_attr)
        # Rewrite only top border line to avoid full box redraw on title updates.
        self.outer.hline(0, 1, curses.ACS_HLINE, self._iw)
        if self.title:
            self.outer.addstr(0, 2, f" {self.title[: self._iw - 6]} ", focus_attr)
        self.outer.attroff(focus_attr)
        self._dirty = True

    def reshape(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        if not self.visible:
            return
        self.initialize()
        self.redraw()
        self.refresh()

    def move(self, x, y):
        self.outer.mvwin(y, x)
        self.x = x
        self.y = y

    def erase(self):
        self.inner.erase()
        self._dirty = True
        self.cursor = (0, 0)

    def _do_refresh(self):
        if self._border:
            self.outer.noutrefresh()
        self.inner.noutrefresh()
        if self.reset_cursor_on_refresh:
            self.cursor = (0, 0)

    def refresh(self):
        self._do_refresh()

    def refresh_if_dirty(self):
        if self._dirty:
            self.refresh()
            self._dirty = False

    def print_char(self, char, attr=0, wrap=False):
        cx, cy = self.cursor
        nx = cx + 1
        if not wrap and nx > self._iw - 1:
            return
        self.inner.addch(char, attr)
        if nx == self._iw - 1:
            self.newline()

    def print(self, text, attr=0, wrap=False):
        self._dirty = True
        text = str(text)
        tl = len(text)
        iw, ih = self._iw, self._ih
        if iw <= 0 or ih <= 0:
            return
        cx, cy = self.cursor
        if cx < 0 or cy < 0 or cx >= iw or cy >= ih:
            cx = max(0, min(cx, iw - 1))
            cy = max(0, min(cy, ih - 1))

        c = 0
        while c < tl and cy < ih:
            cut = min(iw - cx - 1, tl - c)
            if cut <= 0:
                if wrap and cy < ih - 1:
                    cx = 0
                    cy += 1
                    continue
                break
            ctxt = text[c: c + cut]
            try:
                self.inner.addstr(cy, cx, ctxt, attr)
            except curses.error:
                break
            cx += cut
            if cx == iw - 1:
                cx = 0
                if cy < ih - 1:
                    cy += 1
                else:
                    break
            if not wrap:
                break
            c += cut

        try:
            self.inner.move(cy, cx)
        except curses.error:
            pass

    def print_line(self, text, attr=0, wrap=False):
        self.print(text=text, attr=attr, wrap=wrap)
        self.newline()

    def newline(self):
        cx, cy = self.cursor
        if cy < self._ih - 1:
            self.cursor = 0, cy + 1
        # else:
        #    self.cursor = self._iw - 1, self._ih - 1

    def print_lines(self, lines, attr=0, wrap=False):
        for line in lines:
            cx, cy = self.cursor
            if cy == self.h:
                break
            self.print_line(line, attr=attr, wrap=wrap)
            self.inner.clrtoeol()

    def clear_to_bottom(self):
        self.inner.clrtobot()
        self._dirty = True

    def fill_to_eol(self, char=" ", attr=0):
        cx, cy = self.cursor
        ll = self._iw - cx
        self.print(char * ll, attr=attr)
        self._dirty = True

    def clear_to_eol(self, inverse=False):
        if inverse:
            self.inner.attron(curses.A_REVERSE)
        self.inner.clrtoeol()
        self.inner.attroff(curses.A_REVERSE)
        self._dirty = True

    def __repr__(self):
        return f"<Window title={self.title} w={self.w} h={self.h}>"


def init_color_pairs():
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_RED)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(6, curses.COLOR_YELLOW, curses.COLOR_BLACK)


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
    MNEMONIC = (4, curses.A_BOLD)

    def attr(self):
        return curses.color_pair(self.value[0]) | self.value[1]
