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
	shortcuts         *ShortcutManager
	shortcutMode      func() int
	windows           []*Window
	windowInput       map[*Window]func(int) bool
	focusOrder        []*Window
	layoutInitializer func(*Screen)
	initialized       bool
	focused           *Window
	focusIndex        int
	inputHandler      func(int) bool
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
	outer       *C.WINDOW
	inner       *C.WINDOW
	tags        []windowTag
	tagsByID    map[string]int
	onFocus     func()
	onBlur      func()
}

type GridAttrCallback func(value string, row []string) int

type GridColumn struct {
	Name         string
	Width        int
	Attr         int
	AttrCallback GridAttrCallback
}

type GridWidget struct {
	window            *Window
	columns           []GridColumn
	data              [][]string
	rows              [][]string
	offset            int
	selectedRow       int
	selectedRowSet    bool
	highlightedRow    int
	highlightedRowSet bool
	colGap            int
	showScrollbar     bool
	selectionEnabled  bool
	virtualSet        bool
	virtualTotal      int
	virtualOffset     int
	virtualPage       int
	editableSet       bool
	editableStart     int
	editableEnd       int
	onCellInputChange func(x int, y int, value string)
	editingActive     bool
	editRow           int
	editValue         string
	viewportSet       bool
	viewportY         int
	viewportH         int
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

func NewScreen(layoutInitializer func(*Screen), shortcuts *ShortcutManager) *Screen {
	return &Screen{
		layoutInitializer: layoutInitializer,
		shortcuts:         shortcuts,
		shortcutMode:      func() int { return 0 },
		focusIndex:        -1,
		windowInput:       map[*Window]func(int) bool{},
	}
}

func (s *Screen) SetLayoutInitializer(layoutInitializer func(*Screen)) {
	s.layoutInitializer = layoutInitializer
}

func (s *Screen) SetShortcutModeProvider(mode func() int) {
	if mode == nil {
		s.shortcutMode = func() int { return 0 }
		return
	}
	s.shortcutMode = mode
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
	window.attachScreen(s)
	s.windows = append(s.windows, window)
}

func (s *Screen) SetWindowInputHandler(window *Window, handler func(int) bool) {
	if handler == nil {
		delete(s.windowInput, window)
		return
	}
	s.windowInput[window] = handler
}

func (s *Screen) RegisterWindowHotkey(
	window *Window,
	key int,
	label string,
	callback func(),
	visibleInGlobalBar bool,
) {
	shortcut := NewShortcut(key, label, callback)
	shortcut.VisibleInGlobalBar = visibleInGlobalBar
	_ = s.shortcuts.AddGlobal(shortcut)
	window.setHotkeyLabel(shortcut.KeyAsText())
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
	if window != nil && !window.visible {
		return
	}
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

func (s *Screen) SetInputFocus(handler func(int) bool) {
	s.inputHandler = handler
}

func (s *Screen) HasInputFocus() bool {
	return s.inputHandler != nil
}

func (s *Screen) HandleInput(ch int) bool {
	if s.inputHandler != nil {
		return s.inputHandler(ch)
	}
	if s.focused != nil {
		handler := s.windowInput[s.focused]
		if handler != nil && handler(ch) {
			return true
		}
	}
	if s.shortcuts != nil {
		mode := 0
		if s.shortcutMode != nil {
			mode = s.shortcutMode()
		}
		if s.shortcuts.HandleInput(mode, ch) {
			return true
		}
	}
	return false
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

func NewGridWidget(window *Window) *GridWidget {
	return &GridWidget{
		window:           window,
		colGap:           1,
		showScrollbar:    true,
		selectionEnabled: true,
	}
}

func (g *GridWidget) Window() *Window {
	return g.window
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
func (w *Window) OuterWidth() int {
	return w.w
}

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

func (w *Window) setHotkeyLabel(label string) {
	text := strings.TrimSpace(label)
	if w.hotkeyLabel == text {
		return
	}
	w.hotkeyLabel = text
	w.redrawTitle()
}

func (w *Window) AddHotkey(
	key int,
	label string,
	callback func(),
	visibleInGlobalBar bool,
) {
	if w.screen == nil {
		return
	}
	w.screen.RegisterWindowHotkey(w, key, label, callback, visibleInGlobalBar)
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

func (w *Window) attachScreen(screen *Screen) {
	w.screen = screen
}

func (w *Window) initialize() {
	if w.screen == nil || w.screen.scr == nil {
		return
	}
	parent := w.screen.scr
	var ph, pw C.int
	C.g_getmaxyx(parent, &ph, &pw)
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
		w.outer = C.subwin(parent, C.int(rh), C.int(rw), C.int(w.y), C.int(w.x))
		w.inner = C.derwin(w.outer, C.int(rh-2), C.int(rw-2), 1, 1)
	} else {
		w.outer = nil
		w.inner = C.subwin(parent, C.int(rh), C.int(rw), C.int(w.y), C.int(w.x))
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

func (g *GridWidget) ClearColumns() {
	if len(g.columns) == 0 {
		return
	}
	g.columns = nil
	g.editableSet = false
	g.editingActive = false
	g.editRow = 0
	g.editValue = ""
	g.window.dirty = true
}

func (g *GridWidget) AddColumn(name string, width int, attr int, attrCallback GridAttrCallback) {
	if width < 0 {
		width = 0
	}
	g.columns = append(g.columns, GridColumn{
		Name:         name,
		Width:        width,
		Attr:         attr,
		AttrCallback: attrCallback,
	})
	g.rebuildRows()
}

func (g *GridWidget) SetData(rows [][]string) {
	data := make([][]string, len(rows))
	for i, row := range rows {
		cp := make([]string, len(row))
		copy(cp, row)
		data[i] = cp
	}
	g.data = data
	g.editingActive = false
	g.editRow = 0
	g.editValue = ""
	g.rebuildRows()
}

func (g *GridWidget) SetRow(y int, values []string) {
	rowIdx := y
	if rowIdx < 0 {
		return
	}
	data := make([][]string, len(g.data))
	for i, row := range g.data {
		cp := make([]string, len(row))
		copy(cp, row)
		data[i] = cp
	}
	for len(data) <= rowIdx {
		data = append(data, nil)
	}
	cp := make([]string, len(values))
	copy(cp, values)
	data[rowIdx] = cp
	g.SetData(data)
}

func (g *GridWidget) SetCell(x int, y int, value string) {
	rowIdx := y
	colIdx := x
	if rowIdx < 0 || colIdx < 0 {
		return
	}
	data := make([][]string, len(g.data))
	for i, row := range g.data {
		cp := make([]string, len(row))
		copy(cp, row)
		data[i] = cp
	}
	for len(data) <= rowIdx {
		data = append(data, nil)
	}
	row := data[rowIdx]
	for len(row) <= colIdx {
		row = append(row, "")
	}
	row[colIdx] = value
	data[rowIdx] = row
	g.SetData(data)
}

func (g *GridWidget) SetEditableColumnsRange(start, end int) {
	if start > end {
		start, end = end, start
	}
	g.editableSet = true
	g.editableStart = start
	g.editableEnd = end
	g.editingActive = false
	g.editRow = 0
	g.editValue = ""
	g.window.dirty = true
}

func (g *GridWidget) BeginEdit(row int, initialValue string) bool {
	if !g.editableSet {
		return false
	}
	if row < 0 || row >= len(g.rows) {
		return false
	}
	g.editRow = row
	g.editValue = initialValue
	g.editingActive = true
	g.window.dirty = true
	return true
}

func (g *GridWidget) EndEdit() {
	if !g.editingActive {
		return
	}
	g.editingActive = false
	g.editRow = 0
	g.editValue = ""
	g.window.dirty = true
}

func (g *GridWidget) EditingValue() string {
	return g.editValue
}

func (g *GridWidget) SetOnCellInputChange(callback func(x int, y int, value string)) {
	g.onCellInputChange = callback
}

func (g *GridWidget) SetSelectedRow(idx *int) {
	if idx == nil || len(g.rows) == 0 {
		if !g.selectedRowSet {
			return
		}
		g.selectedRowSet = false
		g.selectedRow = 0
		g.editingActive = false
		g.window.dirty = true
		return
	}
	value := *idx
	if value < 0 {
		value = 0
	}
	if value >= len(g.rows) {
		value = len(g.rows) - 1
	}
	if g.selectedRowSet && g.selectedRow == value {
		return
	}
	g.selectedRow = value
	g.selectedRowSet = true
	g.editingActive = false
	g.ensureRowVisible(value)
	g.window.dirty = true
}

func (g *GridWidget) SetHighlightedRow(idx *int) {
	if idx == nil || len(g.rows) == 0 {
		if !g.highlightedRowSet {
			return
		}
		g.highlightedRowSet = false
		g.highlightedRow = 0
		g.window.dirty = true
		return
	}
	value := *idx
	if value < 0 {
		value = 0
	}
	if value >= len(g.rows) {
		value = len(g.rows) - 1
	}
	if g.highlightedRowSet && g.highlightedRow == value {
		return
	}
	g.highlightedRow = value
	g.highlightedRowSet = true
	g.window.dirty = true
}

func (g *GridWidget) SelectedRow() (int, bool) {
	if !g.selectedRowSet {
		return 0, false
	}
	return g.selectedRow, true
}

func (g *GridWidget) SetOffset(offset int) {
	maxOffset := g.maxOffset()
	value := offset
	if value < 0 {
		value = 0
	}
	if value > maxOffset {
		value = maxOffset
	}
	if value == g.offset {
		return
	}
	g.offset = value
	g.window.dirty = true
}

func (g *GridWidget) SetShowScrollbar(enabled bool) {
	if g.showScrollbar == enabled {
		return
	}
	g.showScrollbar = enabled
	g.window.dirty = true
}

func (g *GridWidget) SetSelectionEnabled(enabled bool) {
	if g.selectionEnabled == enabled {
		return
	}
	g.selectionEnabled = enabled
	g.window.dirty = true
}

func (g *GridWidget) SetViewport(y int, height int) {
	if y < 0 {
		y = 0
	}
	if height < 0 {
		height = 0
	}
	if g.viewportSet && g.viewportY == y && g.viewportH == height {
		return
	}
	g.viewportSet = true
	g.viewportY = y
	g.viewportH = height
	g.window.dirty = true
}

func (g *GridWidget) ClearViewport() {
	if !g.viewportSet {
		return
	}
	g.viewportSet = false
	g.viewportY = 0
	g.viewportH = 0
	g.window.dirty = true
}

func (g *GridWidget) SetVirtualScroll(total, offset, page int) {
	totalValue := total
	if totalValue < 1 {
		totalValue = 1
	}
	pageValue := page
	if pageValue < 1 {
		pageValue = 1
	}
	if pageValue > totalValue {
		pageValue = totalValue
	}
	offsetValue := offset
	if offsetValue < 0 {
		offsetValue = 0
	}
	maxOffset := totalValue - pageValue
	if offsetValue > maxOffset {
		offsetValue = maxOffset
	}
	if g.virtualSet &&
		g.virtualTotal == totalValue &&
		g.virtualOffset == offsetValue &&
		g.virtualPage == pageValue {
		return
	}
	g.virtualSet = true
	g.virtualTotal = totalValue
	g.virtualOffset = offsetValue
	g.virtualPage = pageValue
	g.window.dirty = true
}

func (g *GridWidget) ClearVirtualScroll() {
	if !g.virtualSet {
		return
	}
	g.virtualSet = false
	g.virtualTotal = 0
	g.virtualOffset = 0
	g.virtualPage = 0
	g.window.dirty = true
}

func (g *GridWidget) SetColumnGap(gap int) {
	if gap < 0 {
		gap = 0
	}
	if g.colGap == gap {
		return
	}
	g.colGap = gap
	g.window.dirty = true
}

func (g *GridWidget) moveSelected(delta int) {
	count := len(g.rows)
	if count <= 0 {
		g.SetSelectedRow(nil)
		return
	}
	cur, ok := g.SelectedRow()
	if !ok {
		if delta < 0 {
			idx := count - 1
			g.SetSelectedRow(&idx)
		} else {
			idx := 0
			g.SetSelectedRow(&idx)
		}
		return
	}
	next := cur + delta
	if next < 0 {
		next = 0
	}
	if next >= count {
		next = count - 1
	}
	g.SetSelectedRow(&next)
}

func (g *GridWidget) moveSelectedPage(direction int) {
	_, viewportH := g.viewportMetrics()
	page := max(1, viewportH)
	g.moveSelected(direction * page)
}

func (g *GridWidget) selectHome() {
	if len(g.rows) <= 0 {
		g.SetSelectedRow(nil)
		return
	}
	idx := 0
	g.SetSelectedRow(&idx)
}

func (g *GridWidget) selectEnd() {
	if len(g.rows) <= 0 {
		g.SetSelectedRow(nil)
		return
	}
	idx := len(g.rows) - 1
	g.SetSelectedRow(&idx)
}

func (g *GridWidget) HandleNavigationInput(ch int) bool {
	if ch == KeyUp() {
		if g.selectionEnabled {
			g.moveSelected(-1)
		} else {
			g.SetOffset(g.offset - 1)
		}
		return true
	}
	if ch == KeyDown() {
		if g.selectionEnabled {
			g.moveSelected(1)
		} else {
			g.SetOffset(g.offset + 1)
		}
		return true
	}
	if ch == KeyPageUp() || ch == 339 {
		if g.selectionEnabled {
			g.moveSelectedPage(-1)
		} else {
			_, viewportH := g.viewportMetrics()
			g.SetOffset(g.offset - max(1, viewportH))
		}
		return true
	}
	if ch == KeyPageDown() || ch == 338 {
		if g.selectionEnabled {
			g.moveSelectedPage(1)
		} else {
			_, viewportH := g.viewportMetrics()
			g.SetOffset(g.offset + max(1, viewportH))
		}
		return true
	}
	if ch == KeyHome() || ch == 262 {
		if g.selectionEnabled {
			g.selectHome()
		} else {
			g.SetOffset(0)
		}
		return true
	}
	if ch == KeyEnd() || ch == 360 {
		if g.selectionEnabled {
			g.selectEnd()
		} else {
			g.SetOffset(g.maxOffset())
		}
		return true
	}
	return false
}

func (g *GridWidget) HandleInput(ch int) bool {
	if g.handleEditInput(ch) {
		return true
	}
	return g.HandleNavigationInput(ch)
}

func (g *GridWidget) Render() {
	w := g.window
	viewportY, ih := g.viewportMetrics()
	if ih <= 0 {
		return
	}
	g.clampState()
	hasFocus := w.screen == nil || w.screen.focused == w
	total, scrollOffset, scrollPage := g.scrollbarMetrics()
	showScrollbar := g.showScrollbar && w.iw > 0 && total > scrollPage
	contentW := w.iw
	if showScrollbar {
		contentW--
	}
	if contentW < 0 {
		contentW = 0
	}
	start := g.offset
	end := min(len(g.rows), start+ih)
	drawn := 0
	for rowIdx := start; rowIdx < end; rowIdx++ {
		row := g.rows[rowIdx]
		rowAttr := 0
		if g.highlightedRowSet && g.highlightedRow == rowIdx {
			rowAttr |= AttrReverse()
		}
		if g.selectionEnabled && hasFocus && g.selectedRowSet && g.selectedRow == rowIdx {
			rowAttr |= AttrReverse()
		}
		x := 0
		colCount := max(len(g.columns), len(row))
		for colIdx := 0; colIdx < colCount; colIdx++ {
			text := g.cellText(colIdx, rowIdx)
			width := g.columnWidth(colIdx)
			if width > 0 {
				text = padRight(cutTo(text, width), width)
			}
			if x >= contentW {
				break
			}
			if text != "" {
				cut := contentW - x
				if runeLen(text) > cut {
					text = cutTo(text, cut)
				}
				if text != "" {
					w.Cursor(x, viewportY+drawn)
					w.Print(text, g.cellAttr(colIdx, rowIdx)|rowAttr, false)
					x += runeLen(text)
				}
			}
			if colIdx < colCount-1 && g.colGap > 0 && x < contentW {
				gap := min(g.colGap, contentW-x)
				if gap > 0 {
					w.Cursor(x, viewportY+drawn)
					w.Print(strings.Repeat(" ", gap), rowAttr, false)
					x += gap
				}
			}
		}
		if x < contentW {
			w.Cursor(x, viewportY+drawn)
			w.Print(strings.Repeat(" ", contentW-x), rowAttr, false)
		}
		w.Cursor(contentW, viewportY+drawn)
		w.ClearToEOL(false)
		drawn++
	}
	if drawn < ih {
		for y := viewportY + drawn; y < viewportY+ih; y++ {
			w.Cursor(0, y)
			w.ClearToEOL(false)
		}
	}
	if showScrollbar {
		g.drawGridScrollbar(total, scrollOffset, scrollPage, viewportY, ih)
	}
	g.renderEditOverlay(start, contentW, viewportY, ih)
}

func (g *GridWidget) rebuildRows() {
	rows := make([][]string, len(g.data))
	for i, row := range g.data {
		cp := make([]string, len(row))
		copy(cp, row)
		rows[i] = cp
	}
	g.rows = rows
	g.clampState()
	g.window.dirty = true
}

func (g *GridWidget) columnWidth(colIdx int) int {
	if colIdx < 0 || colIdx >= len(g.columns) {
		return 0
	}
	width := g.columns[colIdx].Width
	if width < 0 {
		return 0
	}
	return width
}

func (g *GridWidget) columnAttr(colIdx int) int {
	if colIdx < 0 || colIdx >= len(g.columns) {
		return 0
	}
	return g.columns[colIdx].Attr
}

func (g *GridWidget) cellText(colIdx int, rowIdx int) string {
	if rowIdx < 0 || rowIdx >= len(g.rows) {
		return ""
	}
	row := g.rows[rowIdx]
	if colIdx < 0 || colIdx >= len(row) {
		return ""
	}
	return row[colIdx]
}

func (g *GridWidget) cellAttr(colIdx int, rowIdx int) int {
	base := g.columnAttr(colIdx)
	if rowIdx < 0 || rowIdx >= len(g.data) {
		return base
	}
	if colIdx < 0 || colIdx >= len(g.columns) {
		return base
	}
	cb := g.columns[colIdx].AttrCallback
	if cb == nil {
		return base
	}
	row := g.data[rowIdx]
	value := ""
	if colIdx < len(row) {
		value = row[colIdx]
	}
	return cb(value, row)
}

func (g *GridWidget) editableInputWidth(rowIdx int) int {
	if !g.editableSet {
		return 0
	}
	total := 0
	for colIdx := g.editableStart; colIdx <= g.editableEnd; colIdx++ {
		width := g.columnWidth(colIdx)
		if width <= 0 {
			width = runeLen(g.cellText(colIdx, rowIdx))
		}
		if width < 1 {
			width = 1
		}
		total += width
		if colIdx < g.editableEnd {
			total += g.colGap
		}
	}
	if total < 0 {
		return 0
	}
	return total
}

func (g *GridWidget) editableStartX(rowIdx int) int {
	if !g.editableSet {
		return 0
	}
	x := 0
	for colIdx := 0; colIdx < g.editableStart; colIdx++ {
		width := g.columnWidth(colIdx)
		if width <= 0 {
			width = runeLen(g.cellText(colIdx, rowIdx))
		}
		x += width
		if g.colGap > 0 {
			x += g.colGap
		}
	}
	if x < 0 {
		return 0
	}
	return x
}

func (g *GridWidget) emitCellInputChange(x int, y int, value string) {
	if g.onCellInputChange == nil {
		return
	}
	g.onCellInputChange(x, y, value)
}

func (g *GridWidget) handleEditInput(ch int) bool {
	if !g.editableSet || !g.editingActive {
		return false
	}
	y := g.editRow
	if y < 0 || y >= len(g.data) {
		g.editingActive = false
		return false
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		g.EndEdit()
		return true
	}
	if ch == 27 {
		g.EndEdit()
		return true
	}
	if ch == KeyBackspace() || ch == 127 || ch == 8 {
		if g.editValue == "" {
			return true
		}
		g.editValue = trimLastRune(g.editValue)
		g.emitCellInputChange(g.editableStart, y, g.editValue)
		g.window.dirty = true
		return true
	}
	if ch < 32 || ch > 126 {
		return true
	}
	width := g.editableInputWidth(y)
	if width <= 0 {
		return true
	}
	if runeLen(g.editValue) >= width {
		return true
	}
	g.editValue += string(rune(ch))
	g.emitCellInputChange(g.editableStart, y, g.editValue)
	g.window.dirty = true
	return true
}

func (g *GridWidget) renderEditOverlay(startRow int, contentW int, viewportY int, viewportH int) {
	if !g.editingActive || !g.editableSet {
		return
	}
	rowIdx := g.editRow
	if rowIdx < startRow || rowIdx >= startRow+viewportH {
		return
	}
	y := viewportY + (rowIdx - startRow)
	x := g.editableStartX(rowIdx)
	width := g.editableInputWidth(rowIdx)
	if width <= 0 || x >= contentW {
		return
	}
	if x+width > contentW {
		width = contentW - x
	}
	if width <= 0 {
		return
	}
	text := padRight(cutTo(g.editValue, width), width)
	attr := ColorText.Attr() | AttrReverse()
	g.window.Cursor(x, y)
	g.window.Print(text, attr, false)
	cursorX := min(runeLen(g.editValue), max(0, width-1))
	g.window.Cursor(x+cursorX, y)
}

func (g *GridWidget) drawGridScrollbar(total, offset, page int, viewportY int, viewportH int) {
	w := g.window
	if w.iw <= 0 || viewportH <= 0 {
		return
	}
	if total <= page {
		return
	}
	trackH := viewportH
	maxOffset := max(1, total-page)
	thumbH := max(1, (trackH*page)/total)
	if thumbH > trackH {
		thumbH = trackH
	}
	thumbTop := (offset * (trackH - thumbH)) / maxOffset
	x := w.iw - 1
	trackAttr := ColorWindowTitle.Attr()
	thumbAttr := trackAttr
	if w.screen != nil && w.screen.focused == w {
		thumbAttr = ColorFocus.Attr()
	}
	for y := 0; y < trackH; y++ {
		ch := "|"
		attr := trackAttr
		if y >= thumbTop && y < thumbTop+thumbH {
			ch = "#"
			attr = thumbAttr
		}
		w.Cursor(x, viewportY+y)
		w.Print(ch, attr, false)
	}
}

func (g *GridWidget) scrollbarMetrics() (int, int, int) {
	_, ih := g.viewportMetrics()
	page := max(1, ih)
	if g.virtualSet {
		total := g.virtualTotal
		if total < 1 {
			total = 1
		}
		virtualPage := g.virtualPage
		if virtualPage < 1 {
			virtualPage = 1
		}
		if virtualPage > total {
			virtualPage = total
		}
		offset := g.virtualOffset
		if offset < 0 {
			offset = 0
		}
		maxOffset := total - virtualPage
		if offset > maxOffset {
			offset = maxOffset
		}
		return total, offset, virtualPage
	}
	total := len(g.rows)
	offset := g.offset
	if offset < 0 {
		offset = 0
	}
	maxOffset := max(0, total-page)
	if offset > maxOffset {
		offset = maxOffset
	}
	return total, offset, page
}

func (g *GridWidget) maxOffset() int {
	_, ih := g.viewportMetrics()
	return max(0, len(g.rows)-ih)
}

func (g *GridWidget) clampState() {
	if g.selectedRowSet {
		if len(g.rows) == 0 {
			g.selectedRowSet = false
			g.selectedRow = 0
		} else {
			if g.selectedRow < 0 {
				g.selectedRow = 0
			}
			if g.selectedRow >= len(g.rows) {
				g.selectedRow = len(g.rows) - 1
			}
		}
	}
	if g.highlightedRowSet {
		if len(g.rows) == 0 {
			g.highlightedRowSet = false
			g.highlightedRow = 0
		} else {
			if g.highlightedRow < 0 {
				g.highlightedRow = 0
			}
			if g.highlightedRow >= len(g.rows) {
				g.highlightedRow = len(g.rows) - 1
			}
		}
	}
	maxOffset := g.maxOffset()
	if g.offset < 0 {
		g.offset = 0
	}
	if g.offset > maxOffset {
		g.offset = maxOffset
	}
	if g.selectedRowSet {
		g.ensureRowVisible(g.selectedRow)
	}
}

func (g *GridWidget) ensureRowVisible(idx int) {
	_, ih := g.viewportMetrics()
	if ih <= 0 || len(g.rows) <= 0 {
		return
	}
	row := idx
	if row < 0 {
		row = 0
	}
	if row >= len(g.rows) {
		row = len(g.rows) - 1
	}
	if row < g.offset {
		g.offset = row
		g.window.dirty = true
		return
	}
	maxVisible := g.offset + ih - 1
	if row > maxVisible {
		g.offset = row - ih + 1
		g.window.dirty = true
	}
}

func (g *GridWidget) viewportMetrics() (int, int) {
	ihTotal := g.window.ih
	if ihTotal <= 0 {
		return 0, 0
	}
	if !g.viewportSet {
		return 0, ihTotal
	}
	y := g.viewportY
	if y < 0 {
		y = 0
	}
	if y > ihTotal {
		y = ihTotal
	}
	h := g.viewportH
	maxH := ihTotal - y
	if h < 0 {
		h = 0
	}
	if h > maxH {
		h = maxH
	}
	return y, h
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
