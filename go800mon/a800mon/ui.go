package a800mon

/*
#cgo pkg-config: ncursesw
#include <stdlib.h>
#include <locale.h>
#include <ncurses.h>
#include <sys/ioctl.h>
#include <unistd.h>

static void g_setlocale() { setlocale(LC_ALL, ""); }
static WINDOW* g_stdscr() { return stdscr; }
static void g_getmaxyx(WINDOW* w, int* y, int* x) { int yy, xx; getmaxyx(w, yy, xx); *y = yy; *x = xx; }
static int g_has_colors() { return has_colors(); }
static int g_color_pair(int n) { return COLOR_PAIR(n); }
static int g_key_f(int n) { return KEY_F(n); }
static int g_key_resize() { return KEY_RESIZE; }
static int g_key_up() { return KEY_UP; }
static int g_key_down() { return KEY_DOWN; }
static int g_key_ppage() { return KEY_PPAGE; }
static int g_key_npage() { return KEY_NPAGE; }
static int g_key_home() { return KEY_HOME; }
static int g_key_end() { return KEY_END; }
static int g_key_enter() { return KEY_ENTER; }
static int g_key_backspace() { return KEY_BACKSPACE; }
static int g_key_dc() { return KEY_DC; }
static int g_key_btab() { return KEY_BTAB; }
static int g_attr_reverse() { return A_REVERSE; }
static int g_attr_bold() { return A_BOLD; }
static int g_attr_dim() { return A_DIM; }
static int g_attr_blink() { return A_BLINK; }
static int g_acs_hline() { return ACS_HLINE; }

static void g_waddnstr_attr(WINDOW* w, const char* s, int n, int attr) {
  wattron(w, attr);
  waddnstr(w, s, n);
  wattroff(w, attr);
}
static void g_mvwaddnstr_attr(WINDOW* w, int y, int x, const char* s, int n, int attr) {
  wattron(w, attr);
  mvwaddnstr(w, y, x, s, n);
  wattroff(w, attr);
}
static int g_sync_resize() {
  struct winsize ws;
  if (ioctl(STDOUT_FILENO, TIOCGWINSZ, &ws) == -1) return 0;
  if (ws.ws_row <= 0 || ws.ws_col <= 0) return 0;
  if (is_term_resized(ws.ws_row, ws.ws_col)) {
    resize_term(ws.ws_row, ws.ws_col);
    clearok(stdscr, TRUE);
    return 1;
  }
  return 0;
}
*/
import "C"

import (
	"strings"
	"unsafe"
)

type Screen struct {
	scr               *C.WINDOW
	windows           []*Window
	focusOrder        []*Window
	layoutInitializer func(*Screen)
	initialized       bool
	focused           *Window
	focusIndex        int
}

type Window struct {
	x, y, w, h  int
	iw, ih      int
	title       string
	hotkeyLabel string
	border      bool
	visible     bool
	dirty       bool
	screen      *Screen
	parent      *C.WINDOW
	outer       *C.WINDOW
	inner       *C.WINDOW
	tags        []windowTag
	tagsByID    map[string]int
	onFocus     func()
	onBlur      func()
}

type windowTag struct {
	id     string
	label  string
	active bool
}

type DialogInputResult int

const (
	DialogInputNone DialogInputResult = iota
	DialogInputCancel
	DialogInputConfirm
	DialogInputConsume
)

type DialogWidget struct {
	window        *Window
	title         string
	decision      string
	decisionColor Color
	active        bool
}

type Color int

const (
	ColorAddress Color = iota + 1
	ColorText
	ColorWindowTitle
	ColorError
	ColorTopbar
	ColorFocus
	ColorAppMode
	ColorAppModeDebug
	ColorAppModeShutdown
	ColorShortcut
	ColorTagEnabled
	ColorMnemonic
	ColorComment
	ColorUnused
	ColorInputInvalid
)

func NewScreen(layoutInitializer func(*Screen)) *Screen {
	return &Screen{layoutInitializer: layoutInitializer, focusIndex: -1}
}

func (s *Screen) Initialize() {
	if s.initialized {
		return
	}
	C.g_setlocale()
	C.initscr()
	s.scr = C.g_stdscr()
	C.noecho()
	C.cbreak()
	C.set_escdelay(25)
	_ = C.curs_set(0)
	C.keypad(s.scr, C.bool(true))
	if C.g_has_colors() != 0 {
		C.start_color()
		initColorPairs()
	}
	s.initialized = true
}

func (s *Screen) End() {
	if !s.initialized {
		return
	}
	_ = C.endwin()
	s.initialized = false
}

func (s *Screen) Size() (int, int) {
	var h, w C.int
	C.g_getmaxyx(s.scr, &h, &w)
	return int(w), int(h)
}

func (s *Screen) Add(window *Window) {
	window.parent = s.scr
	window.screen = s
	s.windows = append(s.windows, window)
}

func (s *Screen) SetFocusOrder(windows ...*Window) {
	order := make([]*Window, 0, len(windows))
	for _, window := range windows {
		if window == nil {
			continue
		}
		order = append(order, window)
	}
	s.focusOrder = order
	s.focusIndex = -1
}

func (s *Screen) Focus(window *Window) {
	old := s.focused
	if old == window {
		return
	}
	s.focused = window
	order := s.focusCycleWindows()
	if window == nil {
		s.focusIndex = -1
	} else {
		s.focusIndex = -1
		for i, candidate := range order {
			if candidate == window {
				s.focusIndex = i
				break
			}
		}
	}
	if old != nil && old.onBlur != nil {
		old.onBlur()
	}
	if window != nil && window.onFocus != nil {
		window.onFocus()
	}
	if old != nil {
		old.Redraw()
	}
	if window != nil {
		window.Redraw()
	}
}

func (s *Screen) FocusNext() {
	s.focusStep(1)
}

func (s *Screen) FocusPrev() {
	s.focusStep(-1)
}

func (s *Screen) focusStep(step int) {
	order := s.focusCycleWindows()
	total := len(order)
	if total <= 0 {
		return
	}
	idx := s.focusIndex
	if idx < 0 || idx >= total {
		if step > 0 {
			idx = -1
		} else {
			idx = 0
		}
	}
	for i := 0; i < total; i++ {
		idx = (idx + step + total) % total
		window := order[idx]
		if !window.visible {
			continue
		}
		s.Focus(window)
		return
	}
	s.Focus(nil)
}

func (s *Screen) focusCycleWindows() []*Window {
	if len(s.focusOrder) > 0 {
		return s.focusOrder
	}
	return s.windows
}

func (s *Screen) Focused() *Window {
	return s.focused
}

func (s *Screen) SetInputTimeoutMS(timeoutMS int) {
	if timeoutMS < 0 {
		C.nodelay(s.scr, C.bool(true))
		return
	}
	C.wtimeout(s.scr, C.int(timeoutMS))
}

func (s *Screen) GetInputChar() int {
	return int(C.wgetch(s.scr))
}

func (s *Screen) SyncResize() bool {
	if s.scr == nil {
		return false
	}
	return C.g_sync_resize() != 0
}

func (s *Screen) Rebuild() {
	if s.scr == nil {
		return
	}
	C.wclear(s.scr)
	C.touchwin(s.scr)
	if s.layoutInitializer != nil {
		s.layoutInitializer(s)
	}
	for _, w := range s.windows {
		if w.visible {
			w.initialize()
		}
	}
}

func (s *Screen) Update() {
	for _, w := range s.windows {
		if !w.visible {
			continue
		}
		w.refreshIfDirty()
	}
	C.wrefresh(s.scr)
	C.doupdate()
}

func NewWindow(title string, border bool) *Window {
	return &Window{
		title:    title,
		border:   border,
		visible:  true,
		dirty:    true,
		tagsByID: map[string]int{},
		w:        1,
		h:        1,
	}
}

func NewDialogWidget(window *Window) *DialogWidget {
	return &DialogWidget{
		window:        window,
		decision:      "YES",
		decisionColor: ColorInputInvalid,
	}
}

func (d *DialogWidget) Activate(title, decision string) {
	d.title = strings.TrimSpace(title)
	dec := strings.TrimSpace(decision)
	if dec == "" {
		dec = "YES"
	}
	d.decision = dec
	d.active = true
}

func (d *DialogWidget) Deactivate() {
	d.active = false
}

func (d *DialogWidget) Active() bool {
	return d.active
}

func (d *DialogWidget) HandleInput(ch int) DialogInputResult {
	if !d.active {
		return DialogInputNone
	}
	if ch == 27 {
		d.Deactivate()
		return DialogInputCancel
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		d.Deactivate()
		return DialogInputConfirm
	}
	return DialogInputConsume
}

func (d *DialogWidget) Render() {
	if !d.active || d.window == nil {
		return
	}
	baseAttr := ColorText.Attr() | AttrReverse()
	decisionAttr := d.decisionColor.Attr() | AttrReverse()
	d.window.Cursor(0, 0)
	d.window.FillToEOL(' ', baseAttr)
	if d.title != "" {
		d.window.Cursor(0, 0)
		d.window.Print(d.title, baseAttr, false)
	}
	decision := " " + strings.TrimSpace(d.decision) + " "
	start := d.window.Width() - runeLen(decision)
	if start < 0 {
		start = 0
	}
	d.window.Cursor(start, 0)
	d.window.Print(decision, decisionAttr, false)
}

func (w *Window) WindowCallbacks(onFocus, onBlur func()) {
	w.onFocus = onFocus
	w.onBlur = onBlur
}

func (w *Window) Visible() bool { return w.visible }
func (w *Window) SetVisible(v bool) {
	if w.visible == v {
		return
	}
	w.visible = v
	w.dirty = true
}

func (w *Window) Dirty() bool { return w.dirty }
func (w *Window) Width() int  { return w.iw }
func (w *Window) Height() int { return w.ih }
func (w *Window) X() int      { return w.x }
func (w *Window) Y() int      { return w.y }

func (w *Window) Reshape(x, y, width, height int) {
	w.x = x
	w.y = y
	w.w = width
	w.h = height
	if !w.visible {
		return
	}
	w.initialize()
	w.Redraw()
}

func (w *Window) SetTitle(title string) {
	if w.title == title {
		return
	}
	w.title = title
	w.redrawTitle()
}

func (w *Window) SetHotkeyLabel(label string) {
	text := strings.TrimSpace(label)
	if w.hotkeyLabel == text {
		return
	}
	w.hotkeyLabel = text
	w.redrawTitle()
}

func (w *Window) AddTag(label, tagID string, active bool) {
	if tagID == "" {
		tagID = label
	}
	if _, ok := w.tagsByID[tagID]; ok {
		return
	}
	w.tagsByID[tagID] = len(w.tags)
	w.tags = append(w.tags, windowTag{id: tagID, label: label, active: active})
	w.redrawTitle()
}

func (w *Window) SetTagActive(tagID string, active bool) {
	idx, ok := w.tagsByID[tagID]
	if !ok {
		return
	}
	if w.tags[idx].active == active {
		return
	}
	w.tags[idx].active = active
	w.redrawTitle()
}

func (w *Window) initialize() {
	if w.parent == nil {
		return
	}
	var ph, pw C.int
	C.g_getmaxyx(w.parent, &ph, &pw)
	rw := min(int(pw)-w.x, w.w)
	rh := min(int(ph)-w.y, w.h)
	if rw < 1 {
		rw = 1
	}
	if rh < 1 {
		rh = 1
	}
	if w.inner != nil {
		C.delwin(w.inner)
		w.inner = nil
	}
	if w.outer != nil {
		C.delwin(w.outer)
		w.outer = nil
	}
	if w.border && rh >= 2 && rw >= 2 {
		w.outer = C.subwin(w.parent, C.int(rh), C.int(rw), C.int(w.y), C.int(w.x))
		w.inner = C.derwin(w.outer, C.int(rh-2), C.int(rw-2), 1, 1)
	} else {
		w.outer = nil
		w.inner = C.subwin(w.parent, C.int(rh), C.int(rw), C.int(w.y), C.int(w.x))
	}
	var ih, iw C.int
	C.g_getmaxyx(w.inner, &ih, &iw)
	w.ih = int(ih)
	w.iw = int(iw)
	w.Redraw()
}

func (w *Window) frameAttr() int {
	attr := ColorWindowTitle.Attr()
	if w.screen != nil && w.screen.focused == w {
		attr = ColorFocus.Attr()
	}
	return attr
}

func (w *Window) Redraw() {
	if w.inner == nil {
		return
	}
	if w.border && w.outer != nil {
		attr := w.frameAttr()
		C.wattron(w.outer, C.int(attr))
		C.box(w.outer, 0, 0)
		C.wattroff(w.outer, C.int(attr))
		w.drawTitleAndTags(attr)
	}
	w.dirty = true
}

func (w *Window) redrawTitle() {
	if !w.border || w.outer == nil {
		w.dirty = true
		return
	}
	attr := w.frameAttr()
	C.wattron(w.outer, C.int(attr))
	if w.iw > 0 {
		C.mvwhline(w.outer, 0, 1, C.chtype(C.g_acs_hline()), C.int(w.iw))
	}
	w.drawTitleAndTags(attr)
	C.wattroff(w.outer, C.int(attr))
	w.dirty = true
}

func (w *Window) drawTitleAndTags(baseAttr int) {
	if w.outer == nil {
		return
	}
	var h, ww C.int
	C.g_getmaxyx(w.outer, &h, &ww)
	width := int(ww)
	leftX := 2
	if w.hotkeyLabel != "" && width > 2 {
		hotkey := "[ " + w.hotkeyLabel + " ]"
		maxHotkey := max(0, width-3)
		if maxHotkey > 0 {
			hotkey = cutTo(hotkey, maxHotkey)
			cw := C.CString(hotkey)
			C.g_mvwaddnstr_attr(w.outer, 0, 1, cw, C.int(len(hotkey)), C.int(baseAttr))
			C.free(unsafe.Pointer(cw))
			leftX = 1 + runeLen(hotkey) + 1
		}
	}
	if w.title != "" {
		if leftX < width-1 {
			maxTitle := max(0, width-1-leftX)
			if maxTitle > 0 {
				title := cutTo(" "+w.title+" ", maxTitle)
				cw := C.CString(title)
				C.g_mvwaddnstr_attr(w.outer, 0, C.int(leftX), cw, C.int(len(title)), C.int(baseAttr))
				C.free(unsafe.Pointer(cw))
			}
		}
	}
	if len(w.tags) == 0 {
		return
	}
	x := width - 3
	for i := len(w.tags) - 1; i >= 0; i-- {
		tag := w.tags[i]
		label := " " + strings.TrimSpace(tag.label) + " "
		tw := runeLen(label)
		start := x - tw + 1
		if start <= 1 {
			break
		}
		attr := baseAttr
		if tag.active {
			attr = ColorTagEnabled.Attr()
		}
		cw := C.CString(label)
		C.g_mvwaddnstr_attr(w.outer, 0, C.int(start), cw, C.int(len(label)), C.int(attr))
		C.free(unsafe.Pointer(cw))
		x = start - 1
	}
}

func (w *Window) Erase() {
	if w.inner == nil {
		return
	}
	C.werase(w.inner)
	w.Cursor(0, 0)
	w.dirty = true
}

func (w *Window) refreshIfDirty() {
	if !w.dirty {
		return
	}
	if w.border && w.outer != nil {
		C.wnoutrefresh(w.outer)
	}
	if w.inner != nil {
		C.wnoutrefresh(w.inner)
	}
	w.Cursor(0, 0)
	w.dirty = false
}

func (w *Window) Cursor(x, y int) {
	if w.inner == nil {
		return
	}
	if x < 0 {
		x = 0
	}
	if y < 0 {
		y = 0
	}
	if w.iw > 0 && x >= w.iw {
		x = w.iw - 1
	}
	if w.ih > 0 && y >= w.ih {
		y = w.ih - 1
	}
	C.wmove(w.inner, C.int(y), C.int(x))
}

func (w *Window) CursorPos() (int, int) {
	if w.inner == nil {
		return 0, 0
	}
	y := int(C.getcury(w.inner))
	x := int(C.getcurx(w.inner))
	return x, y
}

func (w *Window) Print(text string, attr int, wrap bool) {
	if w.inner == nil {
		return
	}
	w.dirty = true
	if text == "" {
		return
	}
	iw := w.iw
	ih := w.ih
	if iw <= 0 || ih <= 0 {
		return
	}
	x, y := w.CursorPos()
	chars := []rune(text)
	c := 0
	for c < len(chars) && y < ih {
		cut := min(iw-x, len(chars)-c)
		if cut <= 0 {
			if wrap && y < ih-1 {
				x = 0
				y++
				continue
			}
			break
		}
		chunk := string(chars[c : c+cut])
		cw := C.CString(chunk)
		C.g_mvwaddnstr_attr(w.inner, C.int(y), C.int(x), cw, C.int(len(chunk)), C.int(attr))
		C.free(unsafe.Pointer(cw))
		x += cut
		if x >= iw {
			x = 0
			if y < ih-1 {
				y++
			}
		}
		if !wrap {
			break
		}
		c += cut
	}
	w.Cursor(x, y)
}

func (w *Window) PrintLine(text string, attr int, wrap bool) {
	w.Print(text, attr, wrap)
	w.Newline()
}

func (w *Window) Newline() {
	x, y := w.CursorPos()
	_ = x
	if y < w.ih-1 {
		w.Cursor(0, y+1)
	}
}

func (w *Window) ClearToBottom() {
	if w.inner == nil {
		return
	}
	C.wclrtobot(w.inner)
	w.dirty = true
}

func (w *Window) FillToEOL(ch rune, attr int) {
	x, y := w.CursorPos()
	if w.iw <= x {
		return
	}
	text := strings.Repeat(string(ch), w.iw-x)
	w.Print(text, attr, false)
	w.Cursor(x, y)
}

func (w *Window) ClearToEOL(inverse bool) {
	if w.inner == nil {
		return
	}
	if inverse {
		C.wattron(w.inner, C.int(AttrReverse()))
	}
	C.wclrtoeol(w.inner)
	if inverse {
		C.wattroff(w.inner, C.int(AttrReverse()))
	}
	w.dirty = true
}

func (w *Window) InvertChar(x, y int) {
	if w.inner == nil {
		return
	}
	v := C.mvwinch(w.inner, C.int(y), C.int(x))
	attr := int(v & C.A_ATTRIBUTES)
	if attr&AttrReverse() != 0 {
		attr &^= AttrReverse()
	} else {
		attr |= AttrReverse()
	}
	C.mvwchgat(w.inner, C.int(y), C.int(x), 1, C.attr_t(attr), 0, nil)
	w.dirty = true
}

func initColorPairs() {
	C.init_pair(1, C.COLOR_CYAN, C.COLOR_BLACK)
	C.init_pair(2, C.COLOR_WHITE, C.COLOR_RED)
	C.init_pair(3, C.COLOR_YELLOW, C.COLOR_BLACK)
	C.init_pair(4, C.COLOR_GREEN, C.COLOR_BLACK)
	C.init_pair(5, C.COLOR_RED, C.COLOR_BLACK)
	C.init_pair(6, C.COLOR_YELLOW, C.COLOR_BLACK)
	C.init_pair(7, C.COLOR_WHITE, C.COLOR_BLACK)
	C.init_pair(8, C.COLOR_BLUE, C.COLOR_BLACK)
}

func (c Color) Attr() int {
	switch c {
	case ColorAddress:
		return int(C.g_color_pair(1)) | AttrBold() | AttrDim()
	case ColorText:
		return 0
	case ColorWindowTitle:
		return AttrDim()
	case ColorError:
		return int(C.g_color_pair(2)) | AttrBlink()
	case ColorTopbar:
		return AttrReverse()
	case ColorFocus:
		return int(C.g_color_pair(3)) | AttrBold()
	case ColorAppMode:
		return int(C.g_color_pair(4)) | AttrBold() | AttrReverse() | AttrDim()
	case ColorAppModeDebug:
		return int(C.g_color_pair(6)) | AttrBold() | AttrReverse() | AttrDim()
	case ColorAppModeShutdown:
		return int(C.g_color_pair(5)) | AttrBold() | AttrReverse() | AttrDim()
	case ColorShortcut:
		return AttrReverse()
	case ColorTagEnabled:
		return int(C.g_color_pair(4)) | AttrReverse()
	case ColorMnemonic:
		return int(C.g_color_pair(4)) | AttrBold()
	case ColorComment:
		return int(C.g_color_pair(7)) | AttrDim()
	case ColorUnused:
		return int(C.g_color_pair(8)) | AttrDim()
	case ColorInputInvalid:
		return int(C.g_color_pair(5)) | AttrBold()
	default:
		return 0
	}
}

func AttrReverse() int { return int(C.g_attr_reverse()) }
func AttrBold() int    { return int(C.g_attr_bold()) }
func AttrDim() int     { return int(C.g_attr_dim()) }
func AttrBlink() int   { return int(C.g_attr_blink()) }

func KeyF(n int) int    { return int(C.g_key_f(C.int(n))) }
func KeyF0() int        { return KeyF(0) }
func KeyResize() int    { return int(C.g_key_resize()) }
func KeyUp() int        { return int(C.g_key_up()) }
func KeyDown() int      { return int(C.g_key_down()) }
func KeyPageUp() int    { return int(C.g_key_ppage()) }
func KeyPageDown() int  { return int(C.g_key_npage()) }
func KeyHome() int      { return int(C.g_key_home()) }
func KeyEnd() int       { return int(C.g_key_end()) }
func KeyEnter() int     { return int(C.g_key_enter()) }
func KeyBackspace() int { return int(C.g_key_backspace()) }
func KeyDelete() int    { return int(C.g_key_dc()) }
func KeyBackTab() int   { return int(C.g_key_btab()) }

func runeLen(s string) int {
	return len([]rune(s))
}

func cutTo(s string, n int) string {
	if n <= 0 {
		return ""
	}
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
