import curses

from .ui import Color


class ShortcutLayerNotFound(Exception):
    pass


class ShortcutAlreadyRegistered(Exception):
    pass


class LayerAlreadyRegistered(Exception):
    pass


KEYS_STR_MAP = {
    27: "Esc",
    9: "Tab",
}


class Shortcut:
    def __init__(self, key, label: str, callback: callable):
        if isinstance(key, str):
            self.key = ord(key[0])
        else:
            self.key = int(key)
        self.label = label
        self.callback = callback

    def key_as_text(self):
        if self.key in KEYS_STR_MAP:
            return KEYS_STR_MAP[self.key]

        if self.key >= curses.KEY_F0 and self.key <= curses.KEY_F0 + 63:
            return f"F{self.key - curses.KEY_F0}"

        if self.key < 32:
            return "^" + chr(self.key + 64)

        if self.key > 126:
            return str(self.key)

        return chr(self.key).upper()

    def __repr__(self):
        return f'<Shortcut key="{self.key_as_text()}" label="{self.label}">'


class ShortcutLayer:
    def __init__(self, name="", color: Color = Color.APPMODE):
        self.name = name
        self.color = color
        self._shortcuts = {}

    def add(self, shortcut: Shortcut):
        if shortcut.key in self._shortcuts:
            raise ShortcutAlreadyRegistered(shortcut)
        self._shortcuts[shortcut.key] = shortcut

    def get_shortcuts(self):
        return self._shortcuts.values()

    def get(self, key):
        return self._shortcuts[key]

    def has(self, key):
        return key in self._shortcuts


class ShortcutManager:
    def __init__(self, initial=None):
        self._globals = {}
        self._layers = {}

    def get(self, layer: str):
        return self._layers.get(layer)

    def add_global(self, shortcut: Shortcut):
        if shortcut.key in self._globals:
            raise ShortcutAlreadyRegistered(shortcut)
        self._globals[shortcut.key] = shortcut

    def has_global(self, key: int):
        return key in self._globals

    def get_global(self, key: int):
        return self._globals[key]

    def global_shortcuts(self):
        return self._globals.values()

    def add(self, layer_id: str, layer: ShortcutLayer):
        if layer_id in self._layers:
            raise LayerAlreadyRegistered(layer_id)
        self._layers[layer_id] = layer
