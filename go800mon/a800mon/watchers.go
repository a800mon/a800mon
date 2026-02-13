package a800mon

import (
	"context"
	"fmt"
	"strconv"
	"strings"
)

type WatchersViewer struct {
	BaseWindowComponent
	rpc               *RpcClient
	grid              *GridWidget
	screen            *Screen
	dispatcher        *ActionDispatcher
	rows              []WatcherRow
	pending           *WatcherRow
	selected          *int
	inputSnapshot     string
	inputMode         string
	lastSnapshot      string
	searchInput       *InputWidget
	gridSelectedShift int
}

func NewWatchersViewer(rpc *RpcClient, window *Window) *WatchersViewer {
	grid := NewGridWidget(window)
	grid.SetGridColumnGap(0)
	v := &WatchersViewer{
		BaseWindowComponent: NewBaseWindowComponent(grid.Window()),
		rpc:                 rpc,
		grid:                grid,
	}
	v.searchInput = NewInputWidget(grid.Window())
	v.searchInput.SetMaxLength(8)
	v.searchInput.SetOnChange(v.onSearchChange)
	return v
}

func (v *WatchersViewer) BindInput(screen *Screen, dispatcher *ActionDispatcher) {
	v.screen = screen
	v.dispatcher = dispatcher
	v.Window().WindowCallbacks(func() {
		v.grid.SetGridSelected(nil)
		v.selected = nil
	}, nil)
}

func (v *WatchersViewer) Update(ctx context.Context) (bool, error) {
	rows := make([]WatcherRow, 0, len(v.rows))
	for _, row := range v.rows {
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
	if v.pending != nil {
		value := v.pending.Value
		nextValue := v.pending.NextValue
		data, err := v.rpc.ReadMemory(ctx, v.pending.Addr, 2)
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
			Addr:      v.pending.Addr,
			Value:     value,
			NextValue: nextValue,
			Comment:   LookupSymbol(v.pending.Addr),
		}
		pending = &p
	}

	v.rows = rows
	v.pending = pending
	v.clampSelected(len(v.rows))

	st := State()
	snapshot := buildWatchersSnapshot(v.rows, v.pending, v.selected, st.InputFocus, st.InputTarget, st.InputBuffer, v.inputMode)
	if snapshot == v.lastSnapshot {
		return false, nil
	}
	v.lastSnapshot = snapshot
	return true, nil
}

func (v *WatchersViewer) Render(_force bool) {
	st := State()
	w := v.Window()
	ih := w.Height()
	if ih <= 0 {
		return
	}
	inputActive := st.InputFocus && st.InputTarget == "watchers"
	rows := make([]GridRow, 0, len(v.rows)+2)
	rowBase := 0
	if inputActive {
		rowBase = 1
		rows = append(rows, GridRow{{Text: "", Attr: ColorText.Attr()}})
	}
	pendingOffset := 0
	if v.pending != nil {
		pendingOffset = 1
		rows = append(rows, v.watcherRowCells(*v.pending))
	}
	for _, row := range v.rows {
		rows = append(rows, v.watcherRowCells(row))
	}

	v.gridSelectedShift = rowBase + pendingOffset
	v.grid.SetGridColumnWidths(nil)
	v.grid.SetGridRows(rows)
	if v.selected == nil {
		v.grid.SetGridSelected(nil)
	} else {
		idx := *v.selected + v.gridSelectedShift
		v.grid.SetGridSelected(&idx)
	}
	v.grid.RenderGrid()

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
		v.pending = nil
		return true
	}

	if v.grid.HandleGridNavigationInput(ch) {
		offset := 0
		if st.InputFocus && st.InputTarget == "watchers" {
			offset++
		}
		if v.pending != nil {
			offset++
		}
		v.syncSelectedFromGrid(offset)
		return true
	}

	if ch == KeyDelete() || ch == 330 {
		v.deleteSelected()
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
	if ch == 27 {
		_ = v.dispatcher.Dispatch(ActionSetInputBuffer, v.inputSnapshot)
		v.pending = nil
		v.closeInput()
		return true
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		if v.pending != nil {
			v.commitPending()
		} else {
			v.pending = nil
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

func (v *WatchersViewer) commitPending() {
	if v.pending == nil {
		return
	}
	addr := v.pending.Addr
	for i, row := range v.rows {
		if row.Addr == addr {
			idx := i
			v.selected = &idx
			v.pending = nil
			return
		}
	}
	v.rows = append([]WatcherRow{{Addr: addr, Value: 0, NextValue: 0, Comment: LookupSymbol(addr)}}, v.rows...)
	v.selected = nil
	v.pending = nil
}

func (v *WatchersViewer) deleteSelected() {
	if v.selected == nil {
		return
	}
	idx := *v.selected
	if idx < 0 || idx >= len(v.rows) {
		return
	}
	rows := make([]WatcherRow, 0, len(v.rows)-1)
	rows = append(rows, v.rows[:idx]...)
	rows = append(rows, v.rows[idx+1:]...)
	v.rows = rows
	if len(v.rows) == 0 {
		v.selected = nil
		return
	}
	if idx >= len(v.rows) {
		idx = len(v.rows) - 1
	}
	v.selected = &idx
}

func (v *WatchersViewer) syncSelectedFromGrid(offset int) {
	idx, ok := v.grid.GridSelected()
	if !ok {
		v.selected = nil
		return
	}
	idx -= offset
	if idx < 0 || idx >= len(v.rows) {
		v.selected = nil
		return
	}
	v.selected = &idx
}

func (v *WatchersViewer) clampSelected(rowCount int) {
	if rowCount <= 0 {
		v.selected = nil
		return
	}
	if v.selected == nil {
		return
	}
	idx := *v.selected
	if idx < 0 {
		idx = 0
	}
	if idx >= rowCount {
		idx = rowCount - 1
	}
	v.selected = &idx
}

func (v *WatchersViewer) watcherRowCells(row WatcherRow) GridRow {
	word := (uint16(row.NextValue) << 8) | uint16(row.Value)
	return GridRow{
		{Text: formatHex16(row.Addr) + ":", Attr: ColorAddress.Attr()},
		{Text: fmt.Sprintf(" %02X ", row.Value), Attr: ColorText.Attr()},
		{Text: fmt.Sprintf("%04X", word), Attr: ColorAddress.Attr()},
		{Text: fmt.Sprintf(" %3d %08b ", row.Value, row.Value), Attr: ColorText.Attr()},
		{Text: ";", Attr: ColorText.Attr()},
		{Text: row.Comment, Attr: ColorComment.Attr()},
	}
}

func (v *WatchersViewer) onSearchChange(text string) {
	addr, ok := FindSymbolOrAddress(text)
	if !ok {
		v.pending = nil
		return
	}
	v.pending = &WatcherRow{Addr: addr, Value: 0, NextValue: 0, Comment: LookupSymbol(addr)}
}

func buildWatchersSnapshot(rows []WatcherRow, pending *WatcherRow, selected *int, inputFocus bool, inputTarget string, inputBuffer string, inputMode string) string {
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
	parts = append(parts, fmt.Sprintf("in:%t:%s:%s", inputFocus, inputTarget, inputBuffer))
	parts = append(parts, "mode:"+inputMode)
	return strings.Join(parts, "|")
}
