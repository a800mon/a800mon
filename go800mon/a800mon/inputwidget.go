package a800mon

import "context"

type InputWidget struct {
	BaseVisualComponent
	buffer    string
	maxLength int
	onChange  func(string)
	invalid   bool
}

func NewInputWidget(window *Window) *InputWidget {
	return &InputWidget{
		BaseVisualComponent: NewBaseVisualComponent(window),
		maxLength:           -1,
	}
}

func (i *InputWidget) Update(ctx context.Context) (bool, error) { return false, nil }
func (i *InputWidget) Render(force bool)                        {}
func (i *InputWidget) HandleInput(ch int) bool                  { return false }
func (i *InputWidget) PostRender(ctx context.Context) error     { return nil }

func (i *InputWidget) SetMaxLength(n int) {
	if n <= 0 {
		i.maxLength = -1
		return
	}
	i.maxLength = n
}

func (i *InputWidget) SetOnChange(cb func(string)) {
	i.onChange = cb
}

func (i *InputWidget) Buffer() string {
	return i.buffer
}

func (i *InputWidget) Activate(initial string) {
	_ = i.SetBuffer(initial)
}

func (i *InputWidget) Deactivate() {
	i.invalid = false
	_ = i.SetBuffer("")
}

func (i *InputWidget) SetBuffer(text string) bool {
	out := []rune(text)
	if i.maxLength > 0 && len(out) > i.maxLength {
		out = out[:i.maxLength]
	}
	normalized := string(out)
	if normalized == i.buffer {
		return false
	}
	i.buffer = normalized
	i.emitChange()
	return true
}

func (i *InputWidget) AppendChar(ch int) bool {
	if ch < 0 || ch > 255 {
		return false
	}
	r := rune(ch)
	if r < 32 || r > 126 {
		return false
	}
	if i.maxLength > 0 && len([]rune(i.buffer)) >= i.maxLength {
		return false
	}
	i.buffer += string(r)
	i.emitChange()
	return true
}

func (i *InputWidget) Backspace() bool {
	r := []rune(i.buffer)
	if len(r) == 0 {
		return false
	}
	i.buffer = string(r[:len(r)-1])
	i.emitChange()
	return true
}

func (i *InputWidget) SetInvalid(invalid bool) {
	i.invalid = invalid
}

func (i *InputWidget) Invalid() bool {
	return i.invalid
}

func (i *InputWidget) emitChange() {
	if i.onChange == nil {
		return
	}
	i.onChange(i.buffer)
}
