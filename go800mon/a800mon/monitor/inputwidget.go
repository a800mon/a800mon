package monitor

import (
	"strings"

	. "go800mon/a800mon"
)

type InputWidget struct {
	BaseWindowComponent
	color     Color
	buffer    string
	maxLength int
	onChange  func(string)
	invalid   bool
	normalize func(rune) rune
	validate  func(rune) bool
}

func NewInputWidget(window *Window) *InputWidget {
	return &InputWidget{
		BaseWindowComponent: NewBaseWindowComponent(window),
		color:               ColorText,
		maxLength:           -1,
		normalize:           normalizeRuneIdentity,
		validate:            validatePrintableASCII,
	}
}

func (i *InputWidget) Render(_force bool) {
	w := i.Window()
	w.Cursor(0, 0)
	color := i.color
	if i.invalid {
		color = ColorInputInvalid
	}
	attr := color.Attr() | AttrReverse()
	text := i.buffer
	w.Print(text, attr, false)
	w.FillToEOL(' ', attr)
	cursorX := len([]rune(text))
	width := w.Width()
	if width <= 0 {
		cursorX = 0
	} else if cursorX > width-1 {
		cursorX = width - 1
	}
	if cursorX < 0 {
		cursorX = 0
	}
	w.Cursor(cursorX, 0)
}

func (i *InputWidget) SetColor(color Color) {
	i.color = color
}

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

func (i *InputWidget) SetCharNormalizer(normalize func(rune) rune) {
	if normalize == nil {
		i.normalize = normalizeRuneIdentity
		return
	}
	i.normalize = normalize
}

func (i *InputWidget) SetCharValidator(validate func(rune) bool) {
	if validate == nil {
		i.validate = validatePrintableASCII
		return
	}
	i.validate = validate
}

func (i *InputWidget) AcceptsChar(ch int) bool {
	_, ok := i.normalizeChecked(ch)
	return ok
}

func (i *InputWidget) Buffer() string {
	return i.buffer
}

func (i *InputWidget) Activate(initial string) {
	i.SetBuffer(initial)
}

func (i *InputWidget) Deactivate() {
	i.invalid = false
	i.SetBuffer("")
}

func (i *InputWidget) SetBuffer(text string) {
	out := []rune(text)
	if i.maxLength > 0 && len(out) > i.maxLength {
		out = out[:i.maxLength]
	}
	normalized := string(out)
	if normalized == i.buffer {
		return
	}
	i.buffer = normalized
	i.emitChange()
}

func (i *InputWidget) backspace() {
	r := []rune(i.buffer)
	if len(r) == 0 {
		return
	}
	i.buffer = string(r[:len(r)-1])
	i.emitChange()
}

func (i *InputWidget) HandleKey(ch int) bool {
	if ch == KeyBackspace() || ch == 127 || ch == 8 {
		i.backspace()
		return true
	}
	r, ok := i.normalizeChecked(ch)
	if !ok {
		return false
	}
	if i.maxLength > 0 && len([]rune(i.buffer)) >= i.maxLength {
		return false
	}
	i.buffer += string(r)
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

func (i *InputWidget) normalizeChecked(ch int) (rune, bool) {
	if ch < 0 || ch > 255 {
		return 0, false
	}
	r := i.normalize(rune(ch))
	if !i.validate(r) {
		return 0, false
	}
	return r, true
}

type AddressInputWidget struct {
	*InputWidget
}

func NewAddressInputWidget(window *Window) *AddressInputWidget {
	w := NewInputWidget(window)
	w.SetMaxLength(4)
	w.SetCharNormalizer(func(r rune) rune {
		if r >= 'a' && r <= 'z' {
			return r - 32
		}
		return r
	})
	w.SetCharValidator(func(r rune) bool {
		return (r >= '0' && r <= '9') || (r >= 'A' && r <= 'F')
	})
	return &AddressInputWidget{InputWidget: w}
}

func (a *AddressInputWidget) Render(_force bool) {
	w := a.Window()
	w.Cursor(0, 0)
	color := a.color
	if a.invalid {
		color = ColorInputInvalid
	}
	attr := color.Attr() | AttrReverse()
	text := addressInputDisplayText(a.buffer)
	w.Print(text, attr, false)
	w.FillToEOL(' ', attr)
	w.Cursor(4, 0)
}

func normalizeRuneIdentity(r rune) rune {
	return r
}

func validatePrintableASCII(r rune) bool {
	return r >= 32 && r <= 126
}

func addressInputDisplayText(text string) string {
	upper := strings.ToUpper(text)
	runes := []rune(upper)
	if len(runes) > 4 {
		runes = runes[len(runes)-4:]
	}
	for len(runes) < 4 {
		runes = append([]rune{'0'}, runes...)
	}
	return string(runes)
}
