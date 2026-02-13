package a800mon

import "context"

type ShortcutsComponent struct {
	shortcuts  *ShortcutManager
	dispatcher *ActionDispatcher
}

func NewShortcutsComponent(shortcuts *ShortcutManager, dispatcher *ActionDispatcher) *ShortcutsComponent {
	return &ShortcutsComponent{shortcuts: shortcuts, dispatcher: dispatcher}
}

func (s *ShortcutsComponent) Update(ctx context.Context) (bool, error) { return false, nil }
func (s *ShortcutsComponent) Render(force bool)                        {}

func (s *ShortcutsComponent) HandleInput(ch int) bool {
	st := State()
	if st.InputFocus {
		return false
	}
	layer := s.shortcuts.Get(st.ActiveMode)
	if layer != nil {
		if shortcut, ok := layer.Get(ch); ok {
			if shortcut.Callback != nil {
				shortcut.Callback()
			}
			return true
		}
	}
	if shortcut, ok := s.shortcuts.Global(ch); ok {
		if shortcut.Callback != nil {
			shortcut.Callback()
		}
		return true
	}
	return false
}
