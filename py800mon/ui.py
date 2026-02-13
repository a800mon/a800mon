import curses
import dataclasses
import enum


class Screen:
    def __init__(self, scr, layout_initializer=None):
        self.scr = scr
        self.windows = []
        self._focus_order = []
        self.layout_initializer = layout_initializer
        self._initialized = False
        self.focused = None
        self._focus_index = -1
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
        # self.scr.erase()
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

    def set_focus_order(self, windows):
        self._focus_order = [window for window in windows if window is not None]
        self._focus_index = -1

    def focus(self, window):
        old = self.focused
        if old is window:
            return
        self.focused = window
        order = self._focus_cycle_windows()
        if window is None:
            self._focus_index = -1
        elif window in order:
            self._focus_index = order.index(window)
        else:
            self._focus_index = -1
        if old and old.on_blur:
            old.on_blur()
        if window and window.on_focus:
            window.on_focus()
        if old:
            old.redraw()
        if window:
            window.redraw()

    def focus_next(self):
        self._focus_step(1)

    def focus_prev(self):
        self._focus_step(-1)

    def _focus_step(self, step):
        order = self._focus_cycle_windows()
        total = len(order)
        if total <= 0:
            return
        idx = self._focus_index
        if idx < 0 or idx >= total:
            idx = -1 if step > 0 else 0
        for _ in range(total):
            idx = (idx + step) % total
            window = order[idx]
            if not window.visible:
                continue
            self.focus(window)
            return
        self.focus(None)

    def _focus_cycle_windows(self):
        if self._focus_order:
            return self._focus_order
        return self.windows

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

    def set_input_timeout_ms(self, timeout_ms):
        if timeout_ms is None:
            self.scr.nodelay(True)
            return
        self.scr.timeout(int(timeout_ms))

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
        if self._border:
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

    def set_hotkey_label(self, label: str | None):
        text = str(label).strip() if label is not None else ""
        value = text if text else None
        if value == self._hotkey_label:
            return
        self._hotkey_label = value
        self.redraw_title()

    def redraw_title(self):
        if not self._border or self.outer is None:
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
            "active": bool(active),
        }
        self._tags.append(tag)
        self._tags_by_id[tag["id"]] = tag
        self.redraw_title()

    def set_tag_active(self, tag_id: str, active: bool):
        if tag_id not in self._tags_by_id:
            raise KeyError(f"Unknown window tag id: {tag_id}")
        tag = self._tags_by_id[tag_id]
        new_state = bool(active)
        if tag["active"] == new_state:
            return
        tag["active"] = new_state
        self.redraw_title()

    def _frame_attr(self):
        focus_attr = Color.WINDOW_TITLE.attr()
        if self._screen is not None and self._screen.focused is self:
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


@dataclasses.dataclass(frozen=True, slots=True)
class GridCell:
    text: str
    attr: int = 0


class GridWindow(Window):
    def __init__(self, *args, col_gap=1, show_scrollbar=True, **kwargs):
        super().__init__(*args, **kwargs)
        self._grid_rows = ()
        self._grid_col_widths = ()
        self._grid_offset = 0
        self._grid_selected = None
        self._grid_col_gap = max(0, int(col_gap))
        self._grid_show_scrollbar = bool(show_scrollbar)
        self._grid_selection_enabled = True

    @property
    def grid_offset(self) -> int:
        return self._grid_offset

    @property
    def grid_selected(self) -> int | None:
        return self._grid_selected

    def set_grid_rows(self, rows):
        normalized = []
        for row in rows:
            normalized.append(
                tuple(GridCell(str(cell.text), int(cell.attr)) for cell in row)
            )
        new_rows = tuple(normalized)
        if new_rows == self._grid_rows:
            return
        self._grid_rows = new_rows
        self._clamp_grid_state()
        self._dirty = True

    def set_grid_column_widths(self, widths):
        new_widths = tuple(max(0, int(width)) for width in widths)
        if new_widths == self._grid_col_widths:
            return
        self._grid_col_widths = new_widths
        self._dirty = True

    def set_grid_selected(self, idx: int | None):
        if idx is None or len(self._grid_rows) == 0:
            new_sel = None
        else:
            new_sel = max(0, min(int(idx), len(self._grid_rows) - 1))
        if new_sel == self._grid_selected:
            return
        self._grid_selected = new_sel
        self.ensure_grid_selected_visible()
        self._dirty = True

    def set_grid_offset(self, offset: int):
        max_offset = self._grid_max_offset()
        new_offset = max(0, min(int(offset), max_offset))
        if new_offset == self._grid_offset:
            return
        self._grid_offset = new_offset
        self._dirty = True

    def set_grid_show_scrollbar(self, enabled: bool):
        new_value = bool(enabled)
        if new_value == self._grid_show_scrollbar:
            return
        self._grid_show_scrollbar = new_value
        self._dirty = True

    def set_grid_selection_enabled(self, enabled: bool):
        new_value = bool(enabled)
        if new_value == self._grid_selection_enabled:
            return
        self._grid_selection_enabled = new_value
        self._dirty = True

    def scroll_grid(self, delta: int):
        self.set_grid_offset(self._grid_offset + int(delta))

    def scroll_grid_page(self, direction: int):
        page = max(1, self._ih)
        self.scroll_grid(int(direction) * page)

    def grid_home(self):
        self.set_grid_offset(0)

    def grid_end(self):
        self.set_grid_offset(self._grid_max_offset())

    def grid_move_selected(self, delta: int):
        count = len(self._grid_rows)
        if count <= 0:
            self.set_grid_selected(None)
            return
        step = int(delta)
        cur = self._grid_selected
        if cur is None:
            if step < 0:
                self.set_grid_selected(count - 1)
            else:
                self.set_grid_selected(0)
            return
        self.set_grid_selected(max(0, min(cur + step, count - 1)))

    def grid_move_selected_page(self, direction: int):
        page = max(1, self._ih)
        self.grid_move_selected(int(direction) * page)

    def grid_select_home(self):
        if not self._grid_rows:
            self.set_grid_selected(None)
            return
        self.set_grid_selected(0)

    def grid_select_end(self):
        if not self._grid_rows:
            self.set_grid_selected(None)
            return
        self.set_grid_selected(len(self._grid_rows) - 1)

    def handle_grid_navigation_input(self, ch: int) -> bool:
        if ch == curses.KEY_UP:
            if self._grid_selection_enabled:
                self.grid_move_selected(-1)
            else:
                self.scroll_grid(-1)
            return True
        if ch == curses.KEY_DOWN:
            if self._grid_selection_enabled:
                self.grid_move_selected(1)
            else:
                self.scroll_grid(1)
            return True
        if ch in (curses.KEY_PPAGE, 339):
            if self._grid_selection_enabled:
                self.grid_move_selected_page(-1)
            else:
                self.scroll_grid_page(-1)
            return True
        if ch in (curses.KEY_NPAGE, 338):
            if self._grid_selection_enabled:
                self.grid_move_selected_page(1)
            else:
                self.scroll_grid_page(1)
            return True
        if ch in (curses.KEY_HOME, 262):
            if self._grid_selection_enabled:
                self.grid_select_home()
            else:
                self.grid_home()
            return True
        if ch in (curses.KEY_END, 360):
            if self._grid_selection_enabled:
                self.grid_select_end()
            else:
                self.grid_end()
            return True
        return False

    def ensure_grid_row_visible(self, idx: int):
        if self._ih <= 0:
            return
        row = max(0, min(int(idx), len(self._grid_rows) - 1))
        if row < self._grid_offset:
            self._grid_offset = row
            self._dirty = True
            return
        max_visible = self._grid_offset + self._ih - 1
        if row > max_visible:
            self._grid_offset = row - self._ih + 1
            self._dirty = True

    def ensure_grid_selected_visible(self):
        if self._grid_selected is None:
            return
        self.ensure_grid_row_visible(self._grid_selected)

    def initialize(self):
        super().initialize()
        self._clamp_grid_state()

    def render_grid(self):
        ih = self._ih
        if ih <= 0:
            return
        has_focus = self._screen is None or self._screen.focused is self
        show_scrollbar = (
            self._grid_show_scrollbar
            and self._iw > 0
            and len(self._grid_rows) > ih
        )
        content_w = self._iw - 1 if show_scrollbar else self._iw
        if content_w < 0:
            content_w = 0
        start = self._grid_offset
        end = min(len(self._grid_rows), start + ih)
        drawn = 0
        for row_idx in range(start, end):
            row = self._grid_rows[row_idx]
            rev_attr = (
                curses.A_REVERSE
                if (
                    self._grid_selection_enabled
                    and has_focus
                    and self._grid_selected == row_idx
                )
                else 0
            )
            x = 0
            for col_idx, cell in enumerate(row):
                text = cell.text
                if col_idx < len(self._grid_col_widths):
                    width = self._grid_col_widths[col_idx]
                    if width > 0:
                        text = text[:width].ljust(width)
                if x >= content_w:
                    break
                if text:
                    cut = min(len(text), content_w - x)
                    if cut > 0:
                        self.cursor = (x, drawn)
                        self.print(text[:cut], attr=cell.attr | rev_attr)
                        x += cut
                if col_idx < len(row) - 1 and self._grid_col_gap > 0 and x < content_w:
                    gap = min(self._grid_col_gap, content_w - x)
                    if gap > 0:
                        self.cursor = (x, drawn)
                        self.print(" " * gap, attr=rev_attr)
                        x += gap
            self.cursor = (x, drawn)
            if x < content_w:
                fill = " " * (content_w - x)
                self.print(fill, attr=rev_attr)
            self.clear_to_eol()
            drawn += 1
        if drawn < ih:
            self.cursor = (0, drawn)
            self.clear_to_bottom()
        if show_scrollbar:
            self._draw_grid_scrollbar()

    def _grid_max_offset(self) -> int:
        return max(0, len(self._grid_rows) - self._ih)

    def _clamp_grid_state(self):
        if self._grid_selected is not None:
            if not self._grid_rows:
                self._grid_selected = None
            elif self._grid_selected >= len(self._grid_rows):
                self._grid_selected = len(self._grid_rows) - 1
            elif self._grid_selected < 0:
                self._grid_selected = 0
        self._grid_offset = max(0, min(self._grid_offset, self._grid_max_offset()))
        self.ensure_grid_selected_visible()

    def _draw_grid_scrollbar(self):
        if self._iw <= 0 or self._ih <= 0:
            return
        total = len(self._grid_rows)
        if total <= self._ih:
            return

        track_h = self._ih
        max_offset = max(1, total - self._ih)
        thumb_h = max(1, (self._ih * self._ih) // total)
        thumb_h = min(track_h, thumb_h)
        thumb_top = (self._grid_offset * (track_h - thumb_h)) // max_offset

        x = self._iw - 1
        track_attr = Color.WINDOW_TITLE.attr()
        if self._screen is not None and self._screen.focused is self:
            thumb_attr = Color.FOCUS.attr()
        else:
            thumb_attr = Color.WINDOW_TITLE.attr()
        for y in range(track_h):
            if thumb_top <= y < thumb_top + thumb_h:
                self.put_char(x, y, "#", attr=thumb_attr)
            else:
                self.put_char(x, y, "|", attr=track_attr)


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


class DialogInput(enum.IntEnum):
    NONE = 0
    CANCEL = 1
    CONFIRM = 2
    CONSUME = 3
