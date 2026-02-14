import curses

from .color import init_color_pairs


class Screen:
    def __init__(self, scr, shortcuts, layout_initializer=None):
        self.scr = scr
        self.shortcuts = shortcuts
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
        if not handler:
            self._window_input_handlers.pop(window, None)
            return
        self._window_input_handlers[window] = handler

    def register_window_hotkey(
        self,
        window,
        key,
        label: str,
        callback,
        visible_in_global_bar: bool = False,
    ):
        from ..shortcuts import Shortcut

        shortcut = Shortcut(
            key,
            label,
            callback,
            visible_in_global_bar=visible_in_global_bar,
        )
        self.shortcuts.add_global(shortcut)
        window._set_hotkey_label(shortcut.key_as_text())

    def set_focus_order(self, windows):
        self._focus_order = [window for window in windows if window]
        self._focus_index = -1

    def focus(self, window):
        if window and not window.visible:
            return
        old = self.focused
        if old is window:
            return
        self.focused = window
        order = self._focus_cycle_windows()
        if not window:
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
        if not self._input_handler:
            if not self.focused:
                return False
            handler = self._window_input_handlers.get(self.focused)
            if not handler:
                return False
            return handler(ch)
        return self._input_handler(ch)

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
