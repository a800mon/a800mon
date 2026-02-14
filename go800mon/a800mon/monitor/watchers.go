package monitor

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	. "go800mon/a800mon"
	atari "go800mon/a800mon/atari"
)

type WatchersViewer struct {
	BaseWindowComponent
	rpc          *RpcClient
	grid         *GridWidget
	rows         []WatcherRow
	pending      *WatcherRow
	inputActive  bool
	lastSnapshot string
	searchInput  *InputWidget
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
			Comment:   atari.LookupSymbol(row.Addr),
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
			Comment:   atari.LookupSymbol(v.pending.Addr),
		}
		pending = &p
	}

	v.rows = rows
	v.pending = pending
	var selected *int
	if idx, ok := v.grid.SelectedRow(); ok {
		selected = &idx
	}

	snapshot := buildWatchersSnapshot(
		v.rows,
		v.pending,
		selected,
		v.inputActive,
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
	overlayRows := 0
	if v.inputActive {
		overlayRows++
	}
	if v.pending != nil {
		overlayRows++
	}
	v.grid.SetViewport(overlayRows, max(0, ih-overlayRows))
	rows := make([][]string, 0, len(v.rows))
	for _, row := range v.rows {
		rows = append(rows, v.watcherRowCells(row))
	}

	v.grid.SetData(rows)
	v.grid.Render()

	y := 0
	if v.inputActive {
		w.Cursor(0, y)
		text := v.searchInput.Buffer()
		if len([]rune(text)) > 8 {
			text = string([]rune(text)[:8])
		}
		w.Print(padRight(text, 8), ColorText.Attr()|AttrReverse(), false)
		w.ClearToEOL(false)
		y++
	}
	if v.pending != nil && y < ih {
		v.drawPendingRow(y, *v.pending)
	}
}

func (v *WatchersViewer) HandleInput(ch int) bool {
	if ch == '/' {
		v.inputActive = true
		v.searchInput.Activate("")
		v.clearPending()
		if app := v.App(); app != nil {
			app.DispatchAction(ActionSetInputFocus, v.handleSearchInput)
		}
		return true
	}

	if v.grid.HandleInput(ch) {
		return true
	}

	if ch == KeyDelete() || ch == 330 {
		v.deleteSelected()
		return true
	}

	return false
}

func (v *WatchersViewer) closeInput() {
	v.clearPending()
	v.inputActive = false
	v.searchInput.Deactivate()
	if app := v.App(); app != nil {
		app.DispatchAction(ActionSetInputFocus, nil)
	}
}

func (v *WatchersViewer) handleSearchInput(ch int) bool {
	if ch == 27 {
		v.closeInput()
		return true
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		if v.pending != nil {
			v.commitPending()
		}
		v.closeInput()
		return true
	}
	if v.searchInput.HandleKey(ch) {
		return true
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
			v.grid.SetSelectedRow(&idx)
			return
		}
	}
	v.rows = append([]WatcherRow{{Addr: addr, Value: 0, NextValue: 0, Comment: atari.LookupSymbol(addr)}}, v.rows...)
	v.grid.SetSelectedRow(nil)
}

func (v *WatchersViewer) deleteSelected() {
	idx, ok := v.grid.SelectedRow()
	if !ok {
		return
	}
	v.rows = append(v.rows[:idx], v.rows[idx+1:]...)
	v.grid.SetSelectedRow(&idx)
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

func (v *WatchersViewer) drawPendingRow(y int, row WatcherRow) {
	cells := v.watcherRowCells(row)
	attrs := []int{
		ColorAddress.Attr(),
		ColorText.Attr(),
		ColorAddress.Attr(),
		ColorText.Attr(),
		ColorText.Attr(),
		ColorComment.Attr(),
	}
	w := v.Window()
	w.Cursor(0, y)
	for i, cell := range cells {
		w.Print(cell, attrs[i], false)
	}
	w.ClearToEOL(false)
}

func (v *WatchersViewer) clearPending() {
	v.pending = nil
}

func (v *WatchersViewer) onSearchChange(text string) {
	addr, ok := atari.FindSymbolOrAddress(text)
	if !ok {
		v.clearPending()
		return
	}
	v.pending = &WatcherRow{Addr: addr, Value: 0, NextValue: 0, Comment: atari.LookupSymbol(addr)}
}

func buildWatchersSnapshot(rows []WatcherRow, pending *WatcherRow, selected *int, inputActive bool, inputText string) string {
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
	parts = append(parts, fmt.Sprintf("input:%t", inputActive))
	return strings.Join(parts, "|")
}
