import curses
import dataclasses

from .color import Color


@dataclasses.dataclass
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
        self._show_scrollbar = show_scrollbar
        self._selection_enabled = True
        self._virtual_total = None
        self._virtual_offset = None
        self._virtual_page = None
        self._viewport_y = 0
        self._viewport_h = None
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
        if idx is None or not self._rows:
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
        if idx is None or not self._rows:
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
        new_value = enabled
        if new_value == self._show_scrollbar:
            return
        self._show_scrollbar = new_value
        self.window._dirty = True

    def set_selection_enabled(self, enabled: bool):
        new_value = enabled
        if new_value == self._selection_enabled:
            return
        self._selection_enabled = new_value
        self.window._dirty = True

    def set_viewport(self, y: int = 0, height: int | None = None):
        new_y = max(0, int(y))
        new_h = None if height is None else max(0, int(height))
        if new_y == self._viewport_y and new_h == self._viewport_h:
            return
        self._viewport_y = new_y
        self._viewport_h = new_h
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

    def set_virtual_scroll(self, total: int, offset: int, page: int | None = None):
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
        _y, viewport_h = self._viewport_metrics()
        page = max(1, viewport_h)
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
        _y, viewport_h = self._viewport_metrics()
        page = max(1, viewport_h)
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
        if not callback:
            return
        callback(int(x), int(y), value)

    def ensure_row_visible(self, idx: int):
        _y, ih = self._viewport_metrics()
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
        viewport_y, ih = self._viewport_metrics()
        if ih <= 0:
            return
        self._clamp_state()
        has_focus = (not w._screen) or w._screen.focused is w
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
            if self._selection_enabled and has_focus and self._selected_row == row_idx:
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
                        w.cursor = (x, viewport_y + drawn)
                        w.print(
                            text[:cut],
                            attr=self._cell_attr(col_idx, row_idx) | row_attr,
                        )
                        x += cut
                if col_idx < col_count - 1 and self._col_gap > 0 and x < content_w:
                    gap = min(self._col_gap, content_w - x)
                    if gap > 0:
                        w.cursor = (x, viewport_y + drawn)
                        w.print(" " * gap, attr=row_attr)
                        x += gap
            if x < content_w:
                w.cursor = (x, viewport_y + drawn)
                fill = " " * (content_w - x)
                w.print(fill, attr=row_attr)
            if x < w._iw:
                w.cursor = (x, viewport_y + drawn)
                w.clear_to_eol()
            drawn += 1
        if drawn < ih:
            start_y = viewport_y + drawn
            end_y = viewport_y + ih
            for y in range(start_y, end_y):
                w.cursor = (0, y)
                w.clear_to_eol()
        if show_scrollbar:
            self._draw_grid_scrollbar(
                total,
                scroll_offset,
                scroll_page,
                viewport_y,
                ih,
            )
        self._render_edit_overlay(start, content_w, viewport_y, ih)

    def _max_offset(self) -> int:
        _y, ih = self._viewport_metrics()
        return max(0, len(self._rows) - ih)

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
        if not callback:
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

    def _render_edit_overlay(
        self,
        start_row: int,
        content_w: int,
        viewport_y: int,
        viewport_h: int,
    ):
        if (
            not self._editing_active
            or self._edit_row is None
            or self.editable_column is None
        ):
            return
        row_idx = int(self._edit_row)
        if row_idx < start_row or row_idx >= start_row + viewport_h:
            return
        y = viewport_y + (row_idx - start_row)
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
        _y, ih = self._viewport_metrics()
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

    def _draw_grid_scrollbar(
        self,
        total: int,
        offset: int,
        page: int,
        viewport_y: int,
        viewport_h: int,
    ):
        w = self.window
        if w._iw <= 0 or viewport_h <= 0:
            return
        if total <= page:
            return

        track_h = viewport_h
        max_offset = max(1, total - page)
        thumb_h = max(1, (track_h * page) // total)
        thumb_h = min(track_h, thumb_h)
        thumb_top = (offset * (track_h - thumb_h)) // max_offset

        x = w._iw - 1
        track_attr = Color.WINDOW_TITLE.attr()
        if w._screen and w._screen.focused is w:
            thumb_attr = Color.FOCUS.attr()
        else:
            thumb_attr = Color.WINDOW_TITLE.attr()
        for y in range(track_h):
            py = viewport_y + y
            if thumb_top <= y < thumb_top + thumb_h:
                w.put_char(x, py, "#", attr=thumb_attr)
            else:
                w.put_char(x, py, "|", attr=track_attr)

    def _viewport_metrics(self):
        ih_total = self.window._ih
        if ih_total <= 0:
            return 0, 0
        y = max(0, min(int(self._viewport_y), ih_total))
        if self._viewport_h is None:
            h = ih_total - y
        else:
            h = max(0, min(int(self._viewport_h), ih_total - y))
        return y, h
