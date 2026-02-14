package a800mon

import "fmt"

type Shortcut struct {
	Key                int
	Label              string
	Callback           func()
	VisibleInGlobalBar bool
}

func NewShortcut(key int, label string, callback func()) Shortcut {
	return Shortcut{
		Key:                normalizeShortcutKey(key),
		Label:              label,
		Callback:           callback,
		VisibleInGlobalBar: true,
	}
}

func (s Shortcut) KeyAsText() string {
	return shortcutKeyAsText(s.Key)
}

type ShortcutLayer struct {
	Name      string
	Color     Color
	shortcuts map[int]Shortcut
	order     []int
}

func NewShortcutLayer(name string, color Color) *ShortcutLayer {
	return &ShortcutLayer{Name: name, Color: color, shortcuts: map[int]Shortcut{}, order: []int{}}
}

func (l *ShortcutLayer) Add(shortcut Shortcut) error {
	key := normalizeShortcutKey(shortcut.Key)
	shortcut.Key = key
	if _, ok := l.shortcuts[key]; ok {
		return fmt.Errorf("shortcut already registered: %d", key)
	}
	l.shortcuts[key] = shortcut
	l.order = append(l.order, key)
	return nil
}

func (l *ShortcutLayer) Get(key int) (Shortcut, bool) {
	s, ok := l.shortcuts[normalizeShortcutKey(key)]
	return s, ok
}

func (l *ShortcutLayer) Has(key int) bool {
	_, ok := l.shortcuts[normalizeShortcutKey(key)]
	return ok
}

func (l *ShortcutLayer) List() []Shortcut {
	out := make([]Shortcut, 0, len(l.order))
	for _, key := range l.order {
		out = append(out, l.shortcuts[key])
	}
	return out
}

type ShortcutManager struct {
	globals      map[int]Shortcut
	globalsOrder []int
	layers       map[int]*ShortcutLayer
}

func NewShortcutManager() *ShortcutManager {
	return &ShortcutManager{
		globals:      map[int]Shortcut{},
		globalsOrder: []int{},
		layers:       map[int]*ShortcutLayer{},
	}
}

func (m *ShortcutManager) AddGlobal(shortcut Shortcut) error {
	key := normalizeShortcutKey(shortcut.Key)
	shortcut.Key = key
	if _, ok := m.globals[key]; ok {
		return fmt.Errorf("shortcut already registered: %d", key)
	}
	m.globals[key] = shortcut
	m.globalsOrder = append(m.globalsOrder, key)
	return nil
}

func (m *ShortcutManager) Add(mode int, layer *ShortcutLayer) error {
	if _, ok := m.layers[mode]; ok {
		return fmt.Errorf("layer already registered: %d", mode)
	}
	m.layers[mode] = layer
	return nil
}

func (m *ShortcutManager) Get(mode int) *ShortcutLayer {
	return m.layers[mode]
}

func (m *ShortcutManager) Global(key int) (Shortcut, bool) {
	s, ok := m.globals[normalizeShortcutKey(key)]
	return s, ok
}

func (m *ShortcutManager) HandleInput(mode, key int) bool {
	layer := m.Get(mode)
	if layer != nil {
		if shortcut, ok := layer.Get(key); ok {
			if shortcut.Callback != nil {
				shortcut.Callback()
			}
			return true
		}
	}
	if shortcut, ok := m.Global(key); ok {
		if shortcut.Callback != nil {
			shortcut.Callback()
		}
		return true
	}
	return false
}

func normalizeShortcutKey(key int) int {
	if key >= int('A') && key <= int('Z') {
		return key + 32
	}
	return key
}

func shortcutKeyAsText(key int) string {
	key = normalizeShortcutKey(key)
	if key == 27 {
		return "Esc"
	}
	if key == 9 {
		return "Tab"
	}
	if key >= KeyF0() && key <= KeyF0()+63 {
		return fmt.Sprintf("F%d", key-KeyF0())
	}
	if key < 32 {
		return "^" + string(rune(key+64))
	}
	if key > 126 {
		return fmt.Sprintf("%d", key)
	}
	if key >= int('a') && key <= int('z') {
		return string(rune(key - 32))
	}
	return string(rune(key))
}

func (m *ShortcutManager) Globals() []Shortcut {
	out := make([]Shortcut, 0, len(m.globalsOrder))
	for _, key := range m.globalsOrder {
		shortcut := m.globals[key]
		if !shortcut.VisibleInGlobalBar {
			continue
		}
		out = append(out, shortcut)
	}
	return out
}
