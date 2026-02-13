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
	grid.SetColumnGap(0)
	grid.AddColumn("addr", 0, ColorAddress.Attr(), nil)
	grid.AddColumn("value", 0, ColorText.Attr(), nil)
	grid.AddColumn("next", 0, ColorAddress.Attr(), nil)
	grid.AddColumn("bits", 0, ColorText.Attr(), nil)
	grid.AddColumn("sep", 0, ColorText.Attr(), nil)
	grid.AddColumn("comment", 0, ColorComment.Attr(), nil)
	v := &WatchersViewer{
		BaseWindowComponent: NewBaseWindowComponent(grid.Window()),
		rpc:                 rpc,
		grid:                grid,
	}
	v.searchInput = NewInputWidget(grid.Window())
	v.searchInput.SetMaxLength(8)
	v.searchInput.SetOnChange(v.onSearchChange)
	v.Window().WindowCallbacks(func() {
		v.grid.SetSelectedRow(nil)
		v.selected = nil
	}, nil)
	return v
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

	snapshot := buildWatchersSnapshot(
		v.rows,
		v.pending,
		v.selected,
		v.inputMode,
		v.searchInput.Buffer(),
	)
	if snapshot == v.lastSnapshot {
		return false, nil
	}
	v.lastSnapshot = snapshot
	return true, nil
}

func (v *WatchersViewer) Render(_force bool) {
	w := v.Window()
	ih := w.Height()
	if ih <= 0 {
		return
	}
	inputActive := v.inputMode == "search"
	rows := make([][]string, 0, len(v.rows)+2)
	rowBase := 0
	if inputActive {
		rowBase = 1
		rows = append(rows, []string{""})
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
	v.grid.SetData(rows)
	if v.selected == nil {
		v.grid.SetSelectedRow(nil)
	} else {
		idx := *v.selected + v.gridSelectedShift
		v.grid.SetSelectedRow(&idx)
	}
	v.grid.Render()

	if inputActive {
		w.Cursor(0, 0)
		text := v.searchInput.Buffer()
		if len([]rune(text)) > 8 {
			text = string([]rune(text)[:8])
		}
		w.Print(padRight(text, 8), ColorText.Attr()|AttrReverse(), false)
		w.ClearToEOL(false)
	}
}

func (v *WatchersViewer) HandleInput(ch int) bool {
	if ch == int('/') {
		v.inputMode = "search"
		v.inputSnapshot = ""
		v.searchInput.Activate(v.inputSnapshot)
		v.pending = nil
		if app := v.App(); app != nil {
			app.DispatchAction(ActionSetInputFocus, v.handleSearchInput)
		}
		return true
	}

	if v.grid.HandleInput(ch) {
		offset := 0
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
	if app := v.App(); app != nil {
		app.DispatchAction(ActionSetInputFocus, nil)
	}
}

func (v *WatchersViewer) handleSearchInput(ch int) bool {
	if ch == 27 {
		_ = v.searchInput.SetBuffer(v.inputSnapshot)
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
		v.searchInput.Backspace()
		return true
	}
	v.searchInput.AppendChar(ch)
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
	idx, ok := v.grid.SelectedRow()
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

func (v *WatchersViewer) watcherRowCells(row WatcherRow) []string {
	word := (uint16(row.NextValue) << 8) | uint16(row.Value)
	return []string{
		formatHex16(row.Addr) + ":",
		fmt.Sprintf(" %02X ", row.Value),
		fmt.Sprintf("%04X", word),
		fmt.Sprintf(" %3d %08b ", row.Value, row.Value),
		";",
		row.Comment,
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

func buildWatchersSnapshot(rows []WatcherRow, pending *WatcherRow, selected *int, inputMode string, inputText string) string {
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
	parts = append(parts, "in:"+inputText)
	parts = append(parts, "mode:"+inputMode)
	return strings.Join(parts, "|")
}
