import curses

from .color import Color


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
        self._tags = []
        self._tags_by_id = {}
        self._hotkey_label = None
        self.outer = None
        self.inner = None

    @property
    def visible(self):
        return self._visible

    @visible.setter
    def visible(self, value):
        new_val = value
        if new_val == self._visible:
            return
        self._visible = new_val

    def add_to_parent(self, screen):
        if self._screen:
            raise RuntimeError("Window already has parent")
        self._screen = screen
        self.parent = screen.scr

    def initialize(self):
        if not self._screen:
            raise RuntimeError("Window has no parent!")
        parent = self._screen.scr

        ph, pw = parent.getmaxyx()
        sx = max(0, min(self.x, pw - 1))
        sy = max(0, min(self.y, ph - 1))
        rw = max(1, min(self.w, pw - sx))
        rh = max(1, min(self.h, ph - sy))
        if self._border and rw >= 2 and rh >= 2:
            self.outer = parent.subwin(rh, rw, sy, sx)
            self.inner = self.outer.derwin(rh - 2, rw - 2, 1, 1)
        else:
            self.outer = None
            self.inner = parent.subwin(rh, rw, sy, sx)
        self._ih, self._iw = self.inner.getmaxyx()
        self.redraw()

    @property
    def cursor(self):
        y, x = self.inner.getyx()
        return x, y

    @cursor.setter
    def cursor(self, v):
        if not self.inner:
            return
        if self._iw <= 0 or self._ih <= 0:
            return
        x = max(0, min(int(v[0]), self._iw - 1))
        y = max(0, min(int(v[1]), self._ih - 1))
        try:
            self.inner.move(y, x)
        except curses.error:
            pass

    def get_char(self, x, y):
        v = self.inner.inch(y, x)
        ch = v & 0xFF
        attr = v & ~0xFF
        return ch, attr

    def put_char(self, x, y, c, attr=0):
        win = self.inner
        cy, cx = win.getyx()
        try:
            win.addch(y, x, c, attr)
        except curses.error:
            pass
        try:
            win.move(cy, cx)
        except curses.error:
            pass

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
        if self._border and self.outer:
            focus_attr = self._frame_attr()
            self.outer.attron(focus_attr)
            self.outer.box()
            self.outer.attroff(focus_attr)
            self._draw_title_and_tags(focus_attr)
        self._dirty = True

    def set_title(self, title):
        if title == self.title:
            return
        self.title = title
        self.redraw_title()

    def _set_hotkey_label(self, label: str | None):
        text = str(label).strip() if label is not None else ""
        value = text if text else None
        if value == self._hotkey_label:
            return
        self._hotkey_label = value
        self.redraw_title()

    def add_hotkey(self, key, label: str, callback, visible_in_global_bar: bool = False):
        if not self._screen:
            raise RuntimeError("Window has no parent!")
        self._screen.register_window_hotkey(
            self,
            key,
            label,
            callback,
            visible_in_global_bar=visible_in_global_bar,
        )

    def redraw_title(self):
        if not self._border or not self.outer:
            self._dirty = True
            return
        focus_attr = self._frame_attr()
        self.outer.attron(focus_attr)
        # Rewrite only top border line to avoid full box redraw on title updates.
        self.outer.hline(0, 1, curses.ACS_HLINE, self._iw)
        self._draw_title_and_tags(focus_attr)
        self.outer.attroff(focus_attr)
        self._dirty = True

    def add_tag(self, label: str, tag_id: str | None = None, active: bool = False):
        if tag_id is None:
            tag_id = label
        if tag_id in self._tags_by_id:
            raise ValueError(f"Duplicate window tag id: {tag_id}")
        tag = {
            "id": str(tag_id),
            "label": str(label),
            "active": active,
        }
        self._tags.append(tag)
        self._tags_by_id[tag["id"]] = tag
        self.redraw_title()

    def set_tag_active(self, tag_id: str, active: bool):
        if tag_id not in self._tags_by_id:
            raise KeyError(f"Unknown window tag id: {tag_id}")
        tag = self._tags_by_id[tag_id]
        new_state = active
        if tag["active"] == new_state:
            return
        tag["active"] = new_state
        self.redraw_title()

    def _frame_attr(self):
        focus_attr = Color.WINDOW_TITLE.attr()
        if self._screen and self._screen.focused is self:
            focus_attr = Color.FOCUS.attr()
        return focus_attr

    def _draw_title_and_tags(self, base_attr):
        _h, w = self.outer.getmaxyx()
        left_x = 2
        if self._hotkey_label:
            hotkey = f"[ {self._hotkey_label} ]"
            max_hotkey = max(0, w - 3)
            if max_hotkey > 0:
                hotkey = hotkey[:max_hotkey]
                self.outer.addstr(0, 1, hotkey, base_attr)
                left_x = 1 + len(hotkey) + 1
        if self.title and left_x < w - 1:
            title = f" {self.title} "
            max_title = max(0, w - 1 - left_x)
            if max_title > 0:
                self.outer.addstr(0, left_x, title[:max_title], base_attr)
        if not self._tags:
            return

        x = w - 1 - 2  # keep two chars from the right border
        for tag in reversed(self._tags):
            label = f" {str(tag['label']).strip()} "
            tag_w = len(label)
            start = x - tag_w + 1
            if start <= 1:
                break
            attr = Color.TAG_ENABLED.attr() if tag["active"] else base_attr
            try:
                self.outer.addstr(0, start, label, attr)
            except curses.error:
                break
            x = start - 1

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
        if self.outer:
            self.outer.mvwin(y, x)
        elif self.inner:
            self.inner.mvwin(y, x)
        self.x = x
        self.y = y

    def erase(self):
        self.inner.erase()
        self._dirty = True
        self.cursor = (0, 0)

    def _do_refresh(self):
        if self._border and self.outer:
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
        if cx < 0 or cy < 0 or cx >= self._iw or cy >= self._ih:
            return
        self.inner.addch(char, attr)
        nx = cx + 1
        if wrap and nx >= self._iw and cy < self._ih - 1:
            self.cursor = (0, cy + 1)
            return
        if nx < self._iw:
            self.cursor = (nx, cy)
            return
        self.cursor = (self._iw - 1, cy)

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
            cut = min(iw - cx, tl - c)
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
            if not wrap:
                if cx >= iw:
                    cx = iw - 1
                break
            if cx >= iw:
                cx = 0
                if cy < ih - 1:
                    cy += 1
                else:
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
