package a800mon

import (
	"context"
	"fmt"
	"strconv"
	"strings"
)

type WatchersViewer struct {
	BaseVisualComponent
	rpc           *RpcClient
	screen        *Screen
	dispatcher    *ActionDispatcher
	inputSnapshot string
	inputMode     string
	lastSnapshot  string
	searchInput   *InputWidget
}

func NewWatchersViewer(rpc *RpcClient, window *Window) *WatchersViewer {
	v := &WatchersViewer{
		BaseVisualComponent: NewBaseVisualComponent(window),
		rpc:                 rpc,
	}
	v.searchInput = NewInputWidget(window)
	v.searchInput.SetMaxLength(8)
	v.searchInput.SetOnChange(v.onSearchChange)
	return v
}

func (v *WatchersViewer) BindInput(screen *Screen, dispatcher *ActionDispatcher) {
	v.screen = screen
	v.dispatcher = dispatcher
	v.Window().WindowCallbacks(func() {
		if v.dispatcher != nil {
			_ = v.dispatcher.Dispatch(ActionSetWatcherSelected, nil)
		}
	}, nil)
}

func (v *WatchersViewer) Update(ctx context.Context) (bool, error) {
	st := State()
	rows := make([]WatcherRow, 0, len(st.Watchers))
	for _, row := range st.Watchers {
		value := row.Value
		nextValue := row.NextValue
		data, err := v.rpc.ReadMemory(ctx, row.Addr, 2)
		if err != nil {
			return false, nil
		}
		if len(data) > 0 {
			value = data[0]
		}
		if len(data) > 1 {
			nextValue = data[1]
		}
		rows = append(rows, WatcherRow{
			Addr:      row.Addr,
			Value:     value,
			NextValue: nextValue,
			Comment:   LookupSymbol(row.Addr),
		})
	}

	var pending *WatcherRow
	if st.WatcherPending != nil {
		value := st.WatcherPending.Value
		nextValue := st.WatcherPending.NextValue
		data, err := v.rpc.ReadMemory(ctx, st.WatcherPending.Addr, 2)
		if err != nil {
			return false, nil
		}
		if len(data) > 0 {
			value = data[0]
		}
		if len(data) > 1 {
			nextValue = data[1]
		}
		p := WatcherRow{
			Addr:      st.WatcherPending.Addr,
			Value:     value,
			NextValue: nextValue,
			Comment:   LookupSymbol(st.WatcherPending.Addr),
		}
		pending = &p
	}

	snapshot := buildWatchersSnapshot(
		rows,
		pending,
		st.WatcherSelected,
		st.InputFocus,
		st.InputTarget,
		st.InputBuffer,
		st.UseATASCII,
		v.inputMode,
	)
	if snapshot == v.lastSnapshot {
		return false, nil
	}
	v.lastSnapshot = snapshot
	v.dispatcher.updateWatchers(rows, pending)
	return true, nil
}

func (v *WatchersViewer) Render(_force bool) {
	st := State()
	w := v.Window()
	ih := w.Height()
	if ih <= 0 {
		return
	}
	hasFocus := v.screen != nil && v.screen.Focused() == v.Window()
	inputActive := st.InputFocus && st.InputTarget == "watchers"
	rowBase := 0
	if inputActive {
		rowBase = 1
	}
	maxRows := ih - rowBase
	if maxRows < 0 {
		maxRows = 0
	}
	w.Cursor(0, rowBase)

	rows := make([]WatcherRow, 0, len(st.Watchers)+1)
	selectedOffset := 0
	if st.WatcherPending != nil {
		rows = append(rows, *st.WatcherPending)
		selectedOffset = 1
	}
	rows = append(rows, st.Watchers...)

	committedLen := len(st.Watchers)
	drawn := 0
	for i := 0; i < len(rows) && i < maxRows; i++ {
		row := rows[i]
		rev := 0
		if hasFocus && st.WatcherSelected != nil && i >= selectedOffset && i-selectedOffset < committedLen && *st.WatcherSelected == i-selectedOffset {
			rev = AttrReverse()
		}
		word := (uint16(row.NextValue) << 8) | uint16(row.Value)
		w.Print(formatHex16(row.Addr)+":", ColorAddress.Attr()|rev, false)
		w.Print(fmt.Sprintf(" %02X ", row.Value), ColorText.Attr()|rev, false)
		w.Print(fmt.Sprintf("%04X", word), ColorAddress.Attr()|rev, false)
		w.Print(fmt.Sprintf(" %3d %08b ", row.Value, row.Value), ColorText.Attr()|rev, false)
		w.Print(";", ColorText.Attr()|rev, false)
		w.Print(row.Comment, ColorComment.Attr()|rev, false)
		w.FillToEOL(' ', rev)
		w.Newline()
		drawn++
	}
	if rowBase+drawn < ih {
		w.Cursor(0, rowBase+drawn)
		w.ClearToBottom()
	}

	if inputActive {
		w.Cursor(0, 0)
		text := st.InputBuffer
		if len([]rune(text)) > 8 {
			text = string([]rune(text)[:8])
		}
		w.Print(padRight(text, 8), ColorText.Attr()|AttrReverse(), false)
		w.ClearToEOL(false)
	}
}

func (v *WatchersViewer) HandleInput(ch int) bool {
	st := State()
	if st.InputFocus {
		if st.InputTarget != "watchers" {
			return false
		}
		return v.handleSearchInput(ch)
	}
	if v.screen == nil || v.dispatcher == nil {
		return false
	}
	if v.screen.Focused() != v.Window() {
		return false
	}

	if ch == int('/') {
		v.inputMode = "search"
		v.inputSnapshot = ""
		v.searchInput.Activate(v.inputSnapshot)
		_ = v.dispatcher.Dispatch(ActionSetInputBuffer, v.searchInput.Buffer())
		_ = v.dispatcher.Dispatch(ActionSetInputTarget, "watchers")
		_ = v.dispatcher.Dispatch(ActionSetInputFocus, true)
		_ = v.dispatcher.Dispatch(ActionSetWatcherPendingAddr, nil)
		return true
	}

	if ch == KeyUp() || ch == KeyDown() {
		if len(st.Watchers) == 0 {
			return true
		}
		if st.WatcherSelected == nil {
			idx := 0
			if ch == KeyUp() {
				idx = len(st.Watchers) - 1
			}
			_ = v.dispatcher.Dispatch(ActionSetWatcherSelected, idx)
			return true
		}
		idx := *st.WatcherSelected
		if ch == KeyUp() && idx > 0 {
			idx--
			_ = v.dispatcher.Dispatch(ActionSetWatcherSelected, idx)
		}
		if ch == KeyDown() && idx < len(st.Watchers)-1 {
			idx++
			_ = v.dispatcher.Dispatch(ActionSetWatcherSelected, idx)
		}
		return true
	}

	if ch == KeyDelete() || ch == 330 {
		_ = v.dispatcher.Dispatch(ActionRemoveSelectedWatcher, nil)
		return true
	}

	return false
}

func (v *WatchersViewer) closeInput() {
	v.inputMode = ""
	v.searchInput.Deactivate()
	_ = v.dispatcher.Dispatch(ActionSetInputFocus, false)
	_ = v.dispatcher.Dispatch(ActionSetInputTarget, "")
}

func (v *WatchersViewer) handleSearchInput(ch int) bool {
	st := State()
	if ch == 27 {
		_ = v.dispatcher.Dispatch(ActionSetInputBuffer, v.inputSnapshot)
		_ = v.dispatcher.Dispatch(ActionSetWatcherPendingAddr, nil)
		v.closeInput()
		return true
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		if st.WatcherPending != nil {
			_ = v.dispatcher.Dispatch(ActionCommitWatcherPending, nil)
		} else {
			_ = v.dispatcher.Dispatch(ActionSetWatcherPendingAddr, nil)
		}
		v.closeInput()
		return true
	}
	if ch == KeyBackspace() || ch == 127 || ch == 8 {
		if v.searchInput.Backspace() {
			_ = v.dispatcher.Dispatch(ActionSetInputBuffer, v.searchInput.Buffer())
		}
		return true
	}
	if v.searchInput.AppendChar(ch) {
		_ = v.dispatcher.Dispatch(ActionSetInputBuffer, v.searchInput.Buffer())
	}
	return true
}

func (v *WatchersViewer) onSearchChange(text string) {
	if v.dispatcher == nil {
		return
	}
	addr, ok := FindSymbolOrAddress(text)
	if !ok {
		_ = v.dispatcher.Dispatch(ActionSetWatcherPendingAddr, nil)
		return
	}
	_ = v.dispatcher.Dispatch(ActionSetWatcherPendingAddr, int(addr))
}

func buildWatchersSnapshot(rows []WatcherRow, pending *WatcherRow, selected *int, inputFocus bool, inputTarget string, inputBuffer string, useATASCII bool, inputMode string) string {
	parts := make([]string, 0, len(rows)+8)
	for _, row := range rows {
		parts = append(parts, fmt.Sprintf("%04X:%02X:%02X:%s", row.Addr, row.Value, row.NextValue, row.Comment))
	}
	if pending != nil {
		parts = append(parts, fmt.Sprintf("pending:%04X:%02X:%02X:%s", pending.Addr, pending.Value, pending.NextValue, pending.Comment))
	}
	if selected == nil {
		parts = append(parts, "sel:-")
	} else {
		parts = append(parts, "sel:"+strconv.Itoa(*selected))
	}
	parts = append(parts, fmt.Sprintf("in:%t:%s:%s:%t", inputFocus, inputTarget, inputBuffer, useATASCII))
	parts = append(parts, "mode:"+inputMode)
	return strings.Join(parts, "|")
}
