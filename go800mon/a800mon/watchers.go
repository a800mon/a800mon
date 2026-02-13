package a800mon

import (
	"context"
	"fmt"
	"strconv"
	"strings"
)

type WatchersViewer struct {
	BaseWindowComponent
	rpc           *RpcClient
	grid          *GridWidget
	screen        *Screen
	dispatcher    *ActionDispatcher
	inputSnapshot string
	inputMode     string
	lastSnapshot  string
	searchInput   *InputWidget
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
	inputActive := st.InputFocus && st.InputTarget == "watchers"
	rows := make([]GridRow, 0, len(st.Watchers)+2)
	rowBase := 0
	if inputActive {
		rowBase = 1
		rows = append(rows, GridRow{{Text: "", Attr: ColorText.Attr()}})
	}
	selectedOffset := rowBase
	if st.WatcherPending != nil {
		rows = append(rows, v.watcherRowCells(*st.WatcherPending))
		selectedOffset++
	}
	for _, row := range st.Watchers {
		rows = append(rows, v.watcherRowCells(row))
	}

	v.grid.SetGridColumnWidths(nil)
	v.grid.SetGridRows(rows)
	if st.WatcherSelected == nil {
		v.grid.SetGridSelected(nil)
	} else {
		idx := *st.WatcherSelected + selectedOffset
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
		_ = v.dispatcher.Dispatch(ActionSetWatcherPendingAddr, nil)
		return true
	}

	if v.grid.HandleGridNavigationInput(ch) {
		v.syncSelectedFromGrid()
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

func (v *WatchersViewer) syncSelectedFromGrid() {
	if v.dispatcher == nil {
		return
	}
	st := State()
	idx, ok := v.grid.GridSelected()
	if !ok {
		_ = v.dispatcher.Dispatch(ActionSetWatcherSelected, nil)
		return
	}
	offset := 0
	if st.InputFocus && st.InputTarget == "watchers" {
		offset++
	}
	if st.WatcherPending != nil {
		offset++
	}
	idx -= offset
	if idx < 0 || idx >= len(st.Watchers) {
		_ = v.dispatcher.Dispatch(ActionSetWatcherSelected, nil)
		return
	}
	_ = v.dispatcher.Dispatch(ActionSetWatcherSelected, idx)
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
