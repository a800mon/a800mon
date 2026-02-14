package monitor

import (
	"context"

	. "go800mon/a800mon"
)

type ShortcutBar struct {
	BaseWindowComponent
	shortcuts *ShortcutManager
	lastMode  AppMode
}

func NewShortcutBar(window *Window, shortcuts *ShortcutManager) *ShortcutBar {
	return &ShortcutBar{
		BaseWindowComponent: NewBaseWindowComponent(window),
		shortcuts:           shortcuts,
	}
}

func (s *ShortcutBar) Update(_ctx context.Context) (bool, error) {
	mode := State().ActiveMode
	if s.lastMode == mode {
		return false, nil
	}
	s.lastMode = mode
	return true, nil
}

func (s *ShortcutBar) Render(_force bool) {
	st := State()
	w := s.Window()
	w.Cursor(0, 0)
	layer := s.shortcuts.Get(int(st.ActiveMode))
	if layer != nil {
		layerText := padRight(layer.Name, 16)
		w.Print(layerText, layer.Color.Attr(), false)
		for _, sh := range layer.List() {
			s.printSlot(sh)
		}
		w.FillToEOL(' ', ColorText.Attr())
	}
	globals := s.shortcuts.Globals()
	globalW := 0
	for _, sh := range globals {
		globalW += len([]rune(sh.KeyAsText())) + 3 + 16
	}
	rightStart := w.Width() - globalW
	if rightStart > 0 {
		w.Cursor(rightStart, 0)
		for _, sh := range globals {
			s.printSlot(sh)
		}
	}
}

func (s *ShortcutBar) printSlot(shortcut Shortcut) {
	w := s.Window()
	keyText := " " + shortcut.KeyAsText() + " "
	label := " " + padRight(shortcut.Label, 16)
	w.Print(keyText, ColorShortcut.Attr(), false)
	w.Print(label, ColorText.Attr(), false)
}

func padRight(s string, n int) string {
	r := []rune(s)
	if len(r) >= n {
		return string(r[:n])
	}
	for len(r) < n {
		r = append(r, ' ')
	}
	return string(r)
}
