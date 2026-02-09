from .app import VisualComponent
from .appstate import shortcuts, state
from .shortcuts import Shortcut
from .ui import Color


class ShortcutBar(VisualComponent):
    def __init__(self, window, shortcut_width=16, mode_width=16):
        super().__init__(window)
        self._last_mode = None
        self._shortcut_width = shortcut_width
        self._mode_width = mode_width

    def _print_slot(self, shortcut: Shortcut):
        key_text = f" {shortcut.key_as_text()} "
        label_text = " " + shortcut.label.ljust(self._shortcut_width)
        self.window.print(key_text, attr=Color.SHORTCUT.attr())
        self.window.print(label_text, attr=Color.TEXT.attr())

    def render(self, force_redraw=False):
        if force_redraw or not self._last_mode == state.active_mode:
            self.window.cursor = 0, 0

            layer = shortcuts.get(state.active_mode)
            if layer:
                self._last_mode = state.active_mode
                layer_text = layer.name[: self._mode_width].ljust(
                    self._mode_width)
                self.window.print(layer_text, layer.color.attr())

                for shortcut in layer.get_shortcuts():
                    self._print_slot(shortcut)
                self.window.fill_to_eol(attr=Color.TEXT.attr())

                globals_len = 0
                globals_list = shortcuts.global_shortcuts()
                for shortcut in globals_list:
                    globals_len += (
                        len(shortcut.key_as_text()) + 3 + self._shortcut_width
                    )
                right_start = self.window._iw - globals_len
                if right_start > 0:
                    self.window.cursor = right_start, 0
                    for shortcut in globals_list:
                        self._print_slot(shortcut)
            else:
                self._last_mode = None
