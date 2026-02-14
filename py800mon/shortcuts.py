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


def _normalize_key(key: int) -> int:
    v = int(key)
    if ord("A") <= v <= ord("Z"):
        return v + 32
    return v


def key_as_text(key: int) -> str:
    key = _normalize_key(key)
    if key in KEYS_STR_MAP:
        return KEYS_STR_MAP[key]

    if key >= curses.KEY_F0 and key <= curses.KEY_F0 + 63:
        return f"F{key - curses.KEY_F0}"

    if key < 32:
        return "^" + chr(key + 64)

    if key > 126:
        return str(key)

    return chr(key).upper()


class Shortcut:
    def __init__(
        self,
        key,
        label: str,
        callback: callable,
        visible_in_global_bar: bool = True,
    ):
        if isinstance(key, str):
            self.key = _normalize_key(ord(key[0]))
        else:
            self.key = _normalize_key(int(key))
        self.label = label
        self.callback = callback
        self.visible_in_global_bar = visible_in_global_bar

    def key_as_text(self):
        return key_as_text(self.key)

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
        return self._shortcuts[_normalize_key(key)]

    def has(self, key):
        return _normalize_key(key) in self._shortcuts


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
        return _normalize_key(key) in self._globals

    def get_global(self, key: int):
        return self._globals[_normalize_key(key)]

    def global_shortcuts(self):
        return [s for s in self._globals.values() if s.visible_in_global_bar]

    def add(self, layer_id: str, layer: ShortcutLayer):
        if layer_id in self._layers:
            raise LayerAlreadyRegistered(layer_id)
        self._layers[layer_id] = layer
