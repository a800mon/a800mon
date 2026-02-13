import curses
import dataclasses
import enum


class Screen:
    def __init__(self, scr, layout_initializer=None):
        self.scr = scr
        self.windows = []
        self._window_input_handlers = {}
        self._focus_order = []
        self.layout_initializer = layout_initializer
        self._initialized = False
        self.focused = None
        self._focus_index = -1
        self._input_handler = None
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
        window.add_to_parent(self)
        self.windows.append(window)

    def set_window_input_handler(self, window, handler):
        if handler is None:
            self._window_input_handlers.pop(window, None)
            return
        self._window_input_handlers[window] = handler

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

    def set_input_focus(self, handler):
        self._input_handler = handler

    def has_input_focus(self):
        return self._input_handler is not None

    def handle_input(self, ch):
        if self._input_handler is None:
            if self.focused is None:
                return False
            handler = self._window_input_handlers.get(self.focused)
            if handler is None:
                return False
            return bool(handler(ch))
        return bool(self._input_handler(ch))

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
        rw = min(pw - self.x, self.w)
        rh = min(ph - self.y, self.h)
        if self._border:
            self.outer = parent.subwin(rh, rw, self.y, self.x)
            self.inner = self.outer.derwin(rh - 2, rw - 2, 1, 1)
        else:
            self.inner = parent.subwin(rh, rw, self.y, self.x)
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
class GridColumn:
    name: str = ""
    attr: int = 0
    width: int = 0
    attr_callback: object = None


class GridWidget:
    def __init__(self, window, col_gap=1, show_scrollbar=True):
        self.window = window
        self._columns = ()
        self._data = ()
        self._rows = ()
        self._offset = 0
        self._selected_row = None
        self._highlighted_row = None
        self._col_gap = max(0, int(col_gap))
        self._show_scrollbar = bool(show_scrollbar)
        self._selection_enabled = True
        self._virtual_total = None
        self._virtual_offset = None
        self._virtual_page = None
        self.editable_column = None
        self.on_cell_input_change = None
        self._editing_active = False
        self._edit_row = None
        self._edit_value = ""

    def clear_columns(self):
        if not self._columns:
            return
        self._columns = ()
        self._editing_active = False
        self._edit_row = None
        self._edit_value = ""
        self.editable_column = None
        self.window._dirty = True

    def add_column(
        self,
        name: str,
        width: int = 0,
        attr: int = 0,
        attr_callback=None,
    ):
        columns = list(self._columns)
        columns.append(
            GridColumn(
                name=name,
                attr=int(attr),
                width=max(0, int(width)),
                attr_callback=attr_callback,
            )
        )
        self._columns = tuple(columns)
        self._rebuild_rows()

    def set_data(self, rows):
        new_data = tuple(tuple(row) for row in rows)
        if new_data == self._data:
            return
        self._data = new_data
        self._editing_active = False
        self._edit_row = None
        self._edit_value = ""
        self._rebuild_rows()

    def set_row(self, y: int, values):
        row_idx = int(y)
        if row_idx < 0:
            return
        data = [tuple(row) for row in self._data]
        if row_idx >= len(data):
            while len(data) < row_idx:
                data.append(tuple())
            data.append(tuple(values))
        else:
            data[row_idx] = tuple(values)
        self.set_data(data)

    def set_cell(self, x: int, y: int, value):
        row_idx = int(y)
        col_idx = int(x)
        if row_idx < 0 or col_idx < 0:
            return
        data = [list(row) for row in self._data]
        if row_idx >= len(data):
            while len(data) <= row_idx:
                data.append([])
        row = data[row_idx]
        if col_idx >= len(row):
            row.extend("" for _ in range(col_idx - len(row) + 1))
        row[col_idx] = value
        self.set_data(tuple(tuple(r) for r in data))

    @property
    def grid_offset(self) -> int:
        return self._offset

    @property
    def selected_row(self) -> int | None:
        return self._selected_row

    @selected_row.setter
    def selected_row(self, idx: int | None):
        if idx is None or len(self._rows) == 0:
            new_sel = None
        else:
            new_sel = max(0, min(int(idx), len(self._rows) - 1))
        if new_sel == self._selected_row:
            return
        self._selected_row = new_sel
        self._editing_active = False
        self.ensure_selected_visible()
        self.window._dirty = True

    @property
    def highlighted_row(self) -> int | None:
        return self._highlighted_row

    @highlighted_row.setter
    def highlighted_row(self, idx: int | None):
        if idx is None or len(self._rows) == 0:
            new_row = None
        else:
            new_row = max(0, min(int(idx), len(self._rows) - 1))
        if new_row == self._highlighted_row:
            return
        self._highlighted_row = new_row
        self.window._dirty = True

    def set_selected_row(self, idx: int | None):
        self.selected_row = idx

    def set_highlighted_row(self, idx: int | None):
        self.highlighted_row = idx

    def set_offset(self, offset: int):
        max_offset = self._max_offset()
        new_offset = max(0, min(int(offset), max_offset))
        if new_offset == self._offset:
            return
        self._offset = new_offset
        self.window._dirty = True

    def set_show_scrollbar(self, enabled: bool):
        new_value = bool(enabled)
        if new_value == self._show_scrollbar:
            return
        self._show_scrollbar = new_value
        self.window._dirty = True

    def set_selection_enabled(self, enabled: bool):
        new_value = bool(enabled)
        if new_value == self._selection_enabled:
            return
        self._selection_enabled = new_value
        self.window._dirty = True

    def set_editable_columns_range(self, start_column_idx: int, end_column_idx: int):
        start = int(start_column_idx)
        end = int(end_column_idx)
        if start > end:
            start, end = end, start
        self.editable_column = (start, end)
        self._editing_active = False
        self._edit_row = None
        self._edit_value = ""
        self.window._dirty = True

    @property
    def editing_value(self) -> str:
        return self._edit_value

    def begin_edit(self, row_idx: int, initial_value: str = ""):
        if self.editable_column is None:
            return False
        row = int(row_idx)
        if row < 0 or row >= len(self._rows):
            return False
        self._edit_row = row
        self._edit_value = str(initial_value)
        self._editing_active = True
        self.window._dirty = True
        return True

    def end_edit(self):
        if not self._editing_active:
            return
        self._editing_active = False
        self._edit_row = None
        self._edit_value = ""
        self.window._dirty = True

    def set_virtual_scroll(
        self, total: int, offset: int, page: int | None = None
    ):
        total_i = max(1, int(total))
        page_i = total_i if page is None else max(1, min(int(page), total_i))
        offset_i = max(0, min(int(offset), total_i - 1))
        new_state = (total_i, offset_i, page_i)
        cur_state = (
            self._virtual_total,
            self._virtual_offset,
            self._virtual_page,
        )
        if cur_state == new_state:
            return
        self._virtual_total = total_i
        self._virtual_offset = offset_i
        self._virtual_page = page_i
        self.window._dirty = True

    def clear_virtual_scroll(self):
        if (
            self._virtual_total is None
            and self._virtual_offset is None
            and self._virtual_page is None
        ):
            return
        self._virtual_total = None
        self._virtual_offset = None
        self._virtual_page = None
        self.window._dirty = True

    def scroll(self, delta: int):
        self.set_offset(self._offset + int(delta))

    def scroll_page(self, direction: int):
        page = max(1, self.window._ih)
        self.scroll(int(direction) * page)

    def home(self):
        self.set_offset(0)

    def end(self):
        self.set_offset(self._max_offset())

    def move_selected(self, delta: int):
        count = len(self._rows)
        if count <= 0:
            self.selected_row = None
            return
        step = int(delta)
        cur = self._selected_row
        if cur is None:
            if step < 0:
                self.selected_row = count - 1
            else:
                self.selected_row = 0
            return
        self.selected_row = max(0, min(cur + step, count - 1))

    def move_selected_page(self, direction: int):
        page = max(1, self.window._ih)
        self.move_selected(int(direction) * page)

    def select_home(self):
        if not self._rows:
            self.selected_row = None
            return
        self.selected_row = 0

    def select_end(self):
        if not self._rows:
            self.selected_row = None
            return
        self.selected_row = len(self._rows) - 1

    def handle_navigation_input(self, ch: int) -> bool:
        if ch == curses.KEY_UP:
            if self._selection_enabled:
                self.move_selected(-1)
            else:
                self.scroll(-1)
            return True
        if ch == curses.KEY_DOWN:
            if self._selection_enabled:
                self.move_selected(1)
            else:
                self.scroll(1)
            return True
        if ch in (curses.KEY_PPAGE, 339):
            if self._selection_enabled:
                self.move_selected_page(-1)
            else:
                self.scroll_page(-1)
            return True
        if ch in (curses.KEY_NPAGE, 338):
            if self._selection_enabled:
                self.move_selected_page(1)
            else:
                self.scroll_page(1)
            return True
        if ch in (curses.KEY_HOME, 262):
            if self._selection_enabled:
                self.select_home()
            else:
                self.home()
            return True
        if ch in (curses.KEY_END, 360):
            if self._selection_enabled:
                self.select_end()
            else:
                self.end()
            return True
        return False

    def handle_input(self, ch: int) -> bool:
        if self._handle_edit_input(ch):
            return True
        return self.handle_navigation_input(ch)

    def _handle_edit_input(self, ch: int) -> bool:
        if (
            self.editable_column is None
            or not self._editing_active
            or self._edit_row is None
        ):
            self._editing_active = False
            return False
        y = int(self._edit_row)
        if y < 0 or y >= len(self._data):
            self._editing_active = False
            return False
        if ch in (10, 13, curses.KEY_ENTER):
            self.end_edit()
            return True
        if ch == 27:
            self.end_edit()
            return True
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if not self._edit_value:
                return True
            self._edit_value = self._edit_value[:-1]
            self._emit_cell_input_change(self.editable_column[0], y, self._edit_value)
            self._editing_active = True
            self.window._dirty = True
            return True
        if ch < 32 or ch > 126:
            return True
        char = chr(ch)
        width = self._editable_input_width(y)
        if width <= 0:
            return True
        if len(self._edit_value) >= width:
            return True
        self._edit_value += char
        self._emit_cell_input_change(self.editable_column[0], y, self._edit_value)
        self._editing_active = True
        self.window._dirty = True
        return True

    def _cell_text(self, x: int, y: int) -> str:
        if y < 0 or y >= len(self._data):
            return ""
        row = self._data[y]
        if x < 0 or x >= len(row):
            return ""
        value = row[x]
        return "" if value is None else str(value)

    def _emit_cell_input_change(self, x: int, y: int, value):
        callback = self.on_cell_input_change
        if callback is None:
            return
        callback(int(x), int(y), value)

    def ensure_row_visible(self, idx: int):
        ih = self.window._ih
        if ih <= 0:
            return
        if not self._rows:
            return
        row = max(0, min(int(idx), len(self._rows) - 1))
        if row < self._offset:
            self._offset = row
            self.window._dirty = True
            return
        max_visible = self._offset + ih - 1
        if row > max_visible:
            self._offset = row - ih + 1
            self.window._dirty = True

    def ensure_selected_visible(self):
        if self._selected_row is None:
            return
        self.ensure_row_visible(self._selected_row)

    def render(self):
        w = self.window
        ih = w._ih
        if ih <= 0:
            return
        self._clamp_state()
        has_focus = w._screen is None or w._screen.focused is w
        total, scroll_offset, scroll_page = self._scrollbar_metrics()
        show_scrollbar = self._show_scrollbar and w._iw > 0 and total > scroll_page
        content_w = w._iw - 1 if show_scrollbar else w._iw
        if content_w < 0:
            content_w = 0
        start = self._offset
        end = min(len(self._rows), start + ih)
        drawn = 0
        for row_idx in range(start, end):
            row = self._rows[row_idx]
            row_attr = 0
            if self._highlighted_row == row_idx:
                row_attr |= curses.A_REVERSE
            if (
                self._selection_enabled
                and has_focus
                and self._selected_row == row_idx
            ):
                row_attr |= curses.A_REVERSE
            x = 0
            col_count = max(len(self._columns), len(row))
            for col_idx in range(col_count):
                text = row[col_idx] if col_idx < len(row) else ""
                width = self._column_width(col_idx)
                if width > 0:
                    text = str(text)[:width].ljust(width)
                else:
                    text = str(text)
                if x >= content_w:
                    break
                if text:
                    cut = min(len(text), content_w - x)
                    if cut > 0:
                        w.cursor = (x, drawn)
                        w.print(
                            text[:cut],
                            attr=self._cell_attr(col_idx, row_idx) | row_attr,
                        )
                        x += cut
                if col_idx < col_count - 1 and self._col_gap > 0 and x < content_w:
                    gap = min(self._col_gap, content_w - x)
                    if gap > 0:
                        w.cursor = (x, drawn)
                        w.print(" " * gap, attr=row_attr)
                        x += gap
            w.cursor = (x, drawn)
            if x < content_w:
                fill = " " * (content_w - x)
                w.print(fill, attr=row_attr)
            w.clear_to_eol()
            drawn += 1
        if drawn < ih:
            w.cursor = (0, drawn)
            w.clear_to_bottom()
        if show_scrollbar:
            self._draw_grid_scrollbar(total, scroll_offset, scroll_page)
        self._render_edit_overlay(start, content_w)

    def _max_offset(self) -> int:
        return max(0, len(self._rows) - self.window._ih)

    def _column_width(self, col_idx: int) -> int:
        if col_idx < 0 or col_idx >= len(self._columns):
            return 0
        return max(0, int(self._columns[col_idx].width))

    def _column_attr(self, col_idx: int) -> int:
        if col_idx < 0 or col_idx >= len(self._columns):
            return 0
        return int(self._columns[col_idx].attr)

    def _cell_attr(self, col_idx: int, row_idx: int) -> int:
        base = self._column_attr(col_idx)
        if row_idx < 0 or row_idx >= len(self._data):
            return base
        if col_idx < 0 or col_idx >= len(self._columns):
            return base
        callback = self._columns[col_idx].attr_callback
        if callback is None:
            return base
        row = self._data[row_idx]
        value = row[col_idx] if col_idx < len(row) else ""
        attr = callback(value, row)
        if attr is None:
            return base
        return int(attr)

    def _rebuild_rows(self):
        rows = []
        for row in self._data:
            rows.append(tuple("" if value is None else str(value) for value in row))
        new_rows = tuple(rows)
        if new_rows == self._rows:
            return
        self._rows = new_rows
        self._clamp_state()
        self.window._dirty = True

    def _editable_input_width(self, row_idx: int) -> int:
        if self.editable_column is None:
            return 0
        start, end = self.editable_column
        total = 0
        for col_idx in range(start, end + 1):
            width = self._column_width(col_idx)
            if width <= 0:
                width = len(self._cell_text(col_idx, row_idx))
            total += max(1, width)
            if col_idx < end:
                total += self._col_gap
        return max(0, total)

    def _editable_start_x(self, row_idx: int) -> int:
        if self.editable_column is None:
            return 0
        start, _end = self.editable_column
        x = 0
        for col_idx in range(start):
            width = self._column_width(col_idx)
            if width <= 0:
                width = len(self._cell_text(col_idx, row_idx))
            x += width
            if self._col_gap > 0:
                x += self._col_gap
        return max(0, x)

    def _render_edit_overlay(self, start_row: int, content_w: int):
        if (
            not self._editing_active
            or self._edit_row is None
            or self.editable_column is None
        ):
            return
        row_idx = int(self._edit_row)
        if row_idx < start_row or row_idx >= start_row + self.window._ih:
            return
        y = row_idx - start_row
        x = self._editable_start_x(row_idx)
        width = self._editable_input_width(row_idx)
        if width <= 0 or x >= content_w:
            return
        width = min(width, content_w - x)
        text = self._edit_value[:width].ljust(width)
        attr = Color.TEXT.attr() | curses.A_REVERSE
        self.window.cursor = (x, y)
        self.window.print(text, attr=attr)
        cx = min(len(self._edit_value), max(0, width - 1))
        self.window.cursor = (x + cx, y)

    def _clamp_state(self):
        if self._selected_row is not None:
            if not self._rows:
                self._selected_row = None
            elif self._selected_row >= len(self._rows):
                self._selected_row = len(self._rows) - 1
            elif self._selected_row < 0:
                self._selected_row = 0
        if self._highlighted_row is not None:
            if not self._rows:
                self._highlighted_row = None
            elif self._highlighted_row >= len(self._rows):
                self._highlighted_row = len(self._rows) - 1
            elif self._highlighted_row < 0:
                self._highlighted_row = 0
        self._offset = max(0, min(self._offset, self._max_offset()))
        self.ensure_selected_visible()

    def _scrollbar_metrics(self):
        ih = self.window._ih
        if (
            self._virtual_total is None
            or self._virtual_offset is None
            or self._virtual_page is None
        ):
            total = len(self._rows)
            page = max(1, ih)
            offset = max(0, min(self._offset, max(0, total - page)))
            return total, offset, page
        total = max(1, int(self._virtual_total))
        page = max(1, min(int(self._virtual_page), total))
        offset = max(0, min(int(self._virtual_offset), total - 1))
        if offset > total - page:
            offset = total - page
        return total, offset, page

    def _draw_grid_scrollbar(self, total: int, offset: int, page: int):
        w = self.window
        if w._iw <= 0 or w._ih <= 0:
            return
        if total <= page:
            return

        track_h = w._ih
        max_offset = max(1, total - page)
        thumb_h = max(1, (track_h * page) // total)
        thumb_h = min(track_h, thumb_h)
        thumb_top = (offset * (track_h - thumb_h)) // max_offset

        x = w._iw - 1
        track_attr = Color.WINDOW_TITLE.attr()
        if w._screen is not None and w._screen.focused is w:
            thumb_attr = Color.FOCUS.attr()
        else:
            thumb_attr = Color.WINDOW_TITLE.attr()
        for y in range(track_h):
            if thumb_top <= y < thumb_top + thumb_h:
                w.put_char(x, y, "#", attr=thumb_attr)
            else:
                w.put_char(x, y, "|", attr=track_attr)


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
