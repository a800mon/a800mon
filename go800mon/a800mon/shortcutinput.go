package a800mon

import "context"

type ShortcutInput struct {
	shortcuts  *ShortcutManager
	dispatcher *ActionDispatcher
}

func NewShortcutInput(shortcuts *ShortcutManager, dispatcher *ActionDispatcher) *ShortcutInput {
	return &ShortcutInput{shortcuts: shortcuts, dispatcher: dispatcher}
}

func (s *ShortcutInput) Update(ctx context.Context) (bool, error) { return false, nil }
func (s *ShortcutInput) PostRender(ctx context.Context) error     { return nil }

func (s *ShortcutInput) HandleInput(ch int) bool {
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
