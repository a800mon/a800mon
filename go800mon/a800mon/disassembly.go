package a800mon

import (
	"context"
	"strconv"
	"strings"

	"go800mon/internal/disasm"
	"go800mon/internal/memory"
)

type DisassemblyViewer struct {
	BaseVisualComponent
	rpc                *RpcClient
	grid               *GridWidget
	screen             *Screen
	dispatcher         *ActionDispatcher
	follow             bool
	inputMode          string
	selectedAddr       uint16
	hasSelectedAddr    bool
	selectedRowHint    int
	hasSelectedRowHint bool
	inputSnapshot      string
	replaceOnNextInput bool
	currentAddr        uint16
	hasCurrentAddr     bool
	lastSnapshot       string
	pendingNav         navAction
	pendingSteps       int
	pendingWriteAddr   uint16
	pendingWriteData   []byte
	hasPendingWrite    bool
	editAddr           uint16
	hasEditAddr        bool
	editSnapshot       string
	editBytes          []byte
}

type navAction int

const (
	navNone navAction = iota
	navHome
	navEnd
	navDown
	navUp
)

const (
	inputModeAddr = "addr"
	inputModeEdit = "edit"
	asmEditX      = 15
	asmEditMaxLen = 48
)

func NewDisassemblyViewer(rpc *RpcClient, window *Window) *DisassemblyViewer {
	grid := NewGridWidget(window)
	grid.SetGridColumnGap(0)
	return &DisassemblyViewer{
		BaseVisualComponent: NewBaseVisualComponent(window),
		rpc:                 rpc,
		grid:                grid,
		follow:              true,
	}
}

func (d *DisassemblyViewer) BindInput(screen *Screen, dispatcher *ActionDispatcher) {
	d.screen = screen
	d.dispatcher = dispatcher
}

func (d *DisassemblyViewer) EnableFollow() {
	d.setFollow(true)
}

func (d *DisassemblyViewer) Update(ctx context.Context) (bool, error) {
	st := State()
	if !st.DisassemblyEnabled {
		if len(st.DisassemblyRows) > 0 {
			store.setDisassemblyRows(nil)
			return true, nil
		}
		return false, nil
	}
	if d.Window().Height() <= 0 {
		return false, nil
	}
	_ = d.applyPendingWrite(ctx)

	if !d.hasCurrentAddr {
		if st.DisassemblyAddr != nil {
			d.currentAddr = *st.DisassemblyAddr
		} else {
			d.currentAddr = st.CPU.PC
		}
		d.hasCurrentAddr = true
		d.selectedAddr = d.currentAddr
		d.hasSelectedAddr = true
		d.selectedRowHint = 0
		d.hasSelectedRowHint = true
	} else if !d.follow && st.DisassemblyAddr != nil && *st.DisassemblyAddr != d.currentAddr {
		d.currentAddr = *st.DisassemblyAddr
	}
	if err := d.applyPendingNav(ctx); err != nil {
		return false, nil
	}

	decoded, err := d.fetchRows(ctx, d.currentAddr)
	if err != nil {
		return false, nil
	}
	if d.follow {
		pc := st.CPU.PC
		ih := d.Window().Height()
		if ih < 1 {
			ih = 1
		}
		rowIdx := findAddrIndex(decoded, pc)
		if pc < d.currentAddr || rowIdx < 0 {
			d.currentAddr = pc
			decoded, err = d.fetchRows(ctx, d.currentAddr)
			if err != nil {
				return false, nil
			}
		} else if rowIdx >= ih {
			startIdx := rowIdx - (ih - 1)
			if startIdx < 0 {
				startIdx = 0
			}
			d.currentAddr = decoded[startIdx].Addr
			decoded, err = d.fetchRows(ctx, d.currentAddr)
			if err != nil {
				return false, nil
			}
		}
		d.hasSelectedAddr = false
		d.hasSelectedRowHint = false
	}

	rows := make([]DisasmRow, 0, len(decoded))
	for _, ins := range decoded {
		row := DisasmRow{
			Addr:     ins.Addr,
			Size:     ins.Size,
			RawText:  ins.RawText,
			AsmText:  ins.AsmText,
			Mnemonic: ins.Mnemonic,
			Operand:  ins.Operand,
			Comment:  ins.Comment,
		}
		if ins.FlowTarget != nil {
			v := *ins.FlowTarget
			row.FlowTarget = &v
		}
		if ins.OperandAddrPos != nil {
			row.HasOperandAddr = true
			row.OperandAddrPos = *ins.OperandAddrPos
		}
		rows = append(rows, row)
	}
	store.setDisassemblyRows(rows)
	addr := d.currentAddr
	store.setDisassemblyAddr(&addr)

	snapshot := buildDisasmSnapshot(st.CPU.PC, d.currentAddr, rows)
	if d.lastSnapshot == snapshot {
		return false, nil
	}
	d.lastSnapshot = snapshot
	return true, nil
}

func (d *DisassemblyViewer) fetchRows(ctx context.Context, addr uint16) ([]disasm.DecodedInstruction, error) {
	readLen := stLimit(d.Window().Height()*3, 3)
	data, err := d.rpc.ReadMemoryChunked(ctx, addr, readLen)
	if err != nil {
		return nil, err
	}
	decoded := disasm.Decode(addr, data)
	rows := make([]disasm.DecodedInstruction, 0, len(decoded))
	prev := uint16(0)
	for i, ins := range decoded {
		if i > 0 && ins.Addr < prev {
			break
		}
		rows = append(rows, ins)
		prev = ins.Addr
	}
	return rows, nil
}

func (d *DisassemblyViewer) Render(_force bool) {
	st := State()
	w := d.Window()
	w.SetTagActive("follow", d.follow)
	gridRows := make([]GridRow, 0, len(st.DisassemblyRows))
	activeRow := -1
	for i, row := range st.DisassemblyRows {
		if activeRow < 0 && row.Addr == st.CPU.PC && !(st.InputFocus && i == 0) {
			activeRow = i
		}
		cells := GridRow{
			{Text: formatHex16(row.Addr) + ":", Attr: ColorAddress.Attr()},
			{Text: " ", Attr: ColorText.Attr()},
			{Text: padRight(row.RawText, 8) + " ", Attr: ColorText.Attr()},
		}
		cells = append(cells, asmRowCells(row)...)
		gridRows = append(gridRows, cells)
	}
	d.grid.SetGridColumnWidths(nil)
	d.grid.SetGridRows(gridRows)
	visCount := min(len(st.DisassemblyRows), w.Height())
	selectedRow := -1
	if d.hasSelectedAddr {
		for i, row := range st.DisassemblyRows {
			if row.Addr == d.selectedAddr {
				selectedRow = i
				break
			}
		}
	}
	if selectedRow < 0 && d.hasSelectedRowHint && visCount > 0 {
		selectedRow = d.selectedRowHint
		if selectedRow < 0 {
			selectedRow = 0
		}
		if selectedRow >= visCount {
			selectedRow = visCount - 1
		}
	}
	if selectedRow < 0 {
		if d.follow && activeRow >= 0 {
			selectedRow = activeRow
		} else if visCount > 0 {
			selectedRow = 0
		}
	}
	if selectedRow >= 0 && visCount > 0 {
		if selectedRow < 0 {
			selectedRow = 0
		}
		if selectedRow >= visCount {
			selectedRow = visCount - 1
		}
		d.selectedRowHint = selectedRow
		d.hasSelectedRowHint = true
		d.selectedAddr = st.DisassemblyRows[selectedRow].Addr
		d.hasSelectedAddr = true
	}
	if selectedRow >= 0 && visCount > 0 {
		idx := selectedRow
		d.grid.SetGridSelected(&idx)
	} else {
		d.hasSelectedAddr = false
		d.hasSelectedRowHint = false
		d.grid.SetGridSelected(nil)
	}
	if activeRow >= 0 {
		idx := activeRow
		d.grid.SetGridActiveRow(&idx)
	} else {
		d.grid.SetGridActiveRow(nil)
	}
	if len(st.DisassemblyRows) > 0 {
		start := int(st.DisassemblyRows[0].Addr)
		anchor := start
		if activeRow >= 0 && activeRow < len(st.DisassemblyRows) {
			anchor = int(st.DisassemblyRows[activeRow].Addr)
		}
		viewCount := min(len(st.DisassemblyRows), w.Height())
		end := start + 1
		for i := 0; i < viewCount; i++ {
			size := st.DisassemblyRows[i].Size
			if size < 1 {
				size = 1
			}
			cand := int(st.DisassemblyRows[i].Addr) + size
			if cand > end {
				end = cand
			}
		}
		if end > 0x10000 {
			end = 0x10000
		}
		page := end - start
		if page < 1 {
			page = 1
		}
		d.grid.SetGridVirtualScroll(0x10000, anchor, page)
	} else {
		d.grid.SetGridVirtualScroll(0x10000, int(d.currentAddr), 1)
	}
	d.grid.SetGridOffset(0)
	d.grid.RenderGrid()
	if !st.InputFocus {
		return
	}
	if d.inputMode == inputModeEdit {
		d.renderEditInput(st.InputBuffer)
		return
	}
	text := strings.ToUpper(st.InputBuffer)
	if len(text) > 4 {
		text = text[len(text)-4:]
	}
	text = padLeft(text, 4, '0')
	w.Cursor(0, 0)
	w.Print(text+"  ", ColorAddress.Attr()|AttrReverse(), false)
}

func (d *DisassemblyViewer) HandleInput(ch int) bool {
	st := State()
	if st.InputFocus {
		if st.InputTarget != "disassembly" {
			return false
		}
		if d.inputMode == inputModeEdit {
			return d.handleEditInput(ch)
		}
		return d.handleAddressInput(ch)
	}
	if !d.Window().Visible() {
		return false
	}
	if d.screen == nil || d.screen.Focused() != d.Window() {
		return false
	}

	lower := ch
	if ch >= int('A') && ch <= int('Z') {
		lower = ch + 32
	}
	if ch == int(' ') || lower == int('f') {
		d.setFollow(!d.follow)
		return true
	}
	if ch == KeyHome() {
		d.setFollow(false)
		d.selectedRowHint = 0
		d.hasSelectedRowHint = true
		d.hasSelectedAddr = false
		d.queueNav(navHome, 0)
		return true
	}
	if ch == KeyDown() {
		d.setFollow(false)
		if !d.moveSelectedRows(1) {
			d.queueNav(navDown, 1)
		}
		return true
	}
	if ch == KeyPageDown() {
		d.setFollow(false)
		steps := d.Window().Height() - 1
		if steps < 1 {
			steps = 1
		}
		if !d.moveSelectedRows(steps) {
			d.queueNav(navDown, steps)
		}
		return true
	}
	if ch == KeyUp() {
		d.setFollow(false)
		if !d.moveSelectedRows(-1) {
			d.queueNav(navUp, 1)
		}
		return true
	}
	if ch == KeyPageUp() {
		d.setFollow(false)
		steps := d.Window().Height() - 1
		if steps < 1 {
			steps = 1
		}
		if !d.moveSelectedRows(-steps) {
			d.queueNav(navUp, steps)
		}
		return true
	}
	if ch == KeyEnd() {
		d.setFollow(false)
		d.selectedRowHint = max(0, d.Window().Height()-1)
		d.hasSelectedRowHint = true
		d.hasSelectedAddr = false
		d.queueNav(navEnd, 0)
		return true
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		return d.openEditInput()
	}
	if ch != int('/') {
		return false
	}
	addr := st.CPU.PC
	if d.hasCurrentAddr {
		addr = d.currentAddr
	} else if st.DisassemblyAddr != nil {
		addr = *st.DisassemblyAddr
	}
	d.inputSnapshot = formatHex16(addr)
	d.replaceOnNextInput = true
	d.inputMode = inputModeAddr
	_ = d.dispatcher.Dispatch(ActionSetInputBuffer, d.inputSnapshot)
	_ = d.dispatcher.Dispatch(ActionSetInputTarget, "disassembly")
	_ = d.dispatcher.Dispatch(ActionSetInputFocus, true)
	return true
}

func (d *DisassemblyViewer) queueNav(action navAction, steps int) {
	d.pendingNav = action
	d.pendingSteps = steps
}

func (d *DisassemblyViewer) applyPendingWrite(ctx context.Context) error {
	if !d.hasPendingWrite {
		return nil
	}
	addr := d.pendingWriteAddr
	payload := append([]byte(nil), d.pendingWriteData...)
	d.hasPendingWrite = false
	d.pendingWriteData = nil
	if len(payload) == 0 {
		return nil
	}
	if err := d.rpc.WriteMemory(ctx, addr, payload); err != nil {
		return err
	}
	d.lastSnapshot = ""
	return nil
}

func (d *DisassemblyViewer) applyPendingNav(ctx context.Context) error {
	if d.pendingNav == navNone {
		return nil
	}
	action := d.pendingNav
	steps := d.pendingSteps
	d.pendingNav = navNone
	d.pendingSteps = 0

	if !d.hasCurrentAddr {
		st := State()
		if st.DisassemblyAddr != nil {
			d.currentAddr = *st.DisassemblyAddr
		} else {
			d.currentAddr = st.CPU.PC
		}
		d.hasCurrentAddr = true
	}

	switch action {
	case navHome:
		d.currentAddr = 0
	case navEnd:
		addr, err := d.findEndStart(ctx)
		if err != nil {
			return err
		}
		d.currentAddr = addr
	case navDown:
		d.moveDown(steps)
		endStart, err := d.findEndStart(ctx)
		if err != nil {
			return err
		}
		if d.currentAddr > endStart {
			d.currentAddr = endStart
		}
	case navUp:
		addr, err := d.findPrevStartN(ctx, d.currentAddr, steps)
		if err != nil {
			return err
		}
		d.currentAddr = addr
	}
	d.hasCurrentAddr = true
	_ = d.dispatcher.Dispatch(ActionSetDisassemblyAddr, d.currentAddr)
	return nil
}

func (d *DisassemblyViewer) moveDown(steps int) {
	rows := State().DisassemblyRows
	if len(rows) == 0 {
		return
	}
	if steps <= 0 {
		steps = 1
	}
	idx := steps
	if idx >= len(rows) {
		idx = len(rows) - 1
	}
	d.currentAddr = rows[idx].Addr
}

func (d *DisassemblyViewer) findEndStart(ctx context.Context) (uint16, error) {
	targetRow := d.Window().Height() - 1
	if targetRow < 0 {
		targetRow = 0
	}
	lookbacks := []int{64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65535}
	for _, back := range lookbacks {
		low := 0xFFFF - back
		if low < 0 {
			low = 0
		}
		length := (0xFFFF - low) + 3
		data, err := d.rpc.ReadMemoryChunked(ctx, uint16(low), length)
		if err != nil {
			return 0, err
		}
		addrs := linearAddrs(disasm.Decode(uint16(low), data))
		if len(addrs) == 0 {
			if low == 0 {
				return 0, nil
			}
			continue
		}
		if len(addrs) > targetRow {
			return addrs[len(addrs)-(targetRow+1)], nil
		}
		if low == 0 {
			return addrs[0], nil
		}
	}
	return 0xFFFF, nil
}

func (d *DisassemblyViewer) findPrevStartN(ctx context.Context, addr uint16, steps int) (uint16, error) {
	if addr == 0 {
		return 0, nil
	}
	if steps <= 0 {
		return addr, nil
	}
	lookbacks := []int{
		steps*3 + 16,
		steps*6 + 32,
		steps*12 + 64,
		steps*24 + 128,
		1024,
		2048,
		4096,
		8192,
		16384,
		32768,
		65535,
	}
	for _, back := range lookbacks {
		low := int(addr) - back
		if low < 0 {
			low = 0
		}
		length := int(addr) - low + 3
		data, err := d.rpc.ReadMemoryChunked(ctx, uint16(low), length)
		if err != nil {
			return 0, err
		}
		addrs := linearAddrs(disasm.Decode(uint16(low), data))
		prev := make([]uint16, 0, len(addrs))
		for _, a := range addrs {
			if a < addr {
				prev = append(prev, a)
			}
		}
		if len(prev) == 0 {
			if low == 0 {
				return 0, nil
			}
			continue
		}
		if len(prev) >= steps {
			return prev[len(prev)-steps], nil
		}
		if low == 0 {
			return prev[0], nil
		}
	}
	return addr, nil
}

func linearAddrs(decoded []disasm.DecodedInstruction) []uint16 {
	if len(decoded) == 0 {
		return nil
	}
	out := make([]uint16, 0, len(decoded))
	var prev uint16
	for i, ins := range decoded {
		if i > 0 && ins.Addr < prev {
			break
		}
		out = append(out, ins.Addr)
		prev = ins.Addr
	}
	return out
}

func (d *DisassemblyViewer) handleAddressInput(ch int) bool {
	st := State()
	if ch == 27 {
		d.updateAddressInput(strings.ToUpper(d.inputSnapshot))
		d.closeInput()
		return true
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		text := strings.ToUpper(st.InputBuffer)
		if text != "" {
			d.updateAddressInput(text)
		}
		d.closeInput()
		return true
	}
	if ch == KeyBackspace() || ch == 127 || ch == 8 {
		d.replaceOnNextInput = false
		text := st.InputBuffer
		if len(text) > 0 {
			text = text[:len(text)-1]
		}
		d.updateAddressInput(strings.ToUpper(text))
		return true
	}
	if ch < 0 || ch > 255 {
		return true
	}
	char := strings.ToUpper(string(rune(ch)))
	if !((char >= "0" && char <= "9") || (char >= "A" && char <= "F")) {
		return true
	}
	text := st.InputBuffer
	if d.replaceOnNextInput {
		text = ""
		d.replaceOnNextInput = false
	}
	if len(text) >= 4 {
		return true
	}
	d.updateAddressInput(text + char)
	return true
}

func (d *DisassemblyViewer) handleEditInput(ch int) bool {
	st := State()
	if ch == 27 {
		_ = d.dispatcher.Dispatch(ActionSetInputBuffer, d.editSnapshot)
		d.closeInput()
		return true
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		if d.hasEditAddr && len(d.editBytes) > 0 {
			d.pendingWriteAddr = d.editAddr
			d.pendingWriteData = append([]byte(nil), d.editBytes...)
			d.hasPendingWrite = true
			d.selectedAddr = d.editAddr
			d.hasSelectedAddr = true
			d.hasSelectedRowHint = false
		}
		d.closeInput()
		return true
	}
	if ch == KeyBackspace() || ch == 127 || ch == 8 {
		text := trimLastRune(st.InputBuffer)
		d.updateEditBuffer(text)
		return true
	}
	if ch < 32 || ch > 126 {
		return true
	}
	text := st.InputBuffer
	if len([]rune(text)) >= asmEditMaxLen {
		return true
	}
	char := rune(ch)
	if char >= 'a' && char <= 'z' {
		char -= 32
	}
	d.updateEditBuffer(text + string(char))
	return true
}

func (d *DisassemblyViewer) updateAddressInput(text string) {
	_ = d.dispatcher.Dispatch(ActionSetInputBuffer, text)
	if text == "" {
		return
	}
	v, err := memory.ParseHex(text)
	if err != nil {
		return
	}
	d.setFollow(false)
	d.currentAddr = v
	d.hasCurrentAddr = true
	d.selectedAddr = d.currentAddr
	d.hasSelectedAddr = true
	d.selectedRowHint = 0
	d.hasSelectedRowHint = true
	d.pendingNav = navNone
	d.pendingSteps = 0
	d.lastSnapshot = ""
	_ = d.dispatcher.Dispatch(ActionSetDisassemblyAddr, d.currentAddr)
}

func (d *DisassemblyViewer) updateEditBuffer(text string) {
	_ = d.dispatcher.Dispatch(ActionSetInputBuffer, text)
	d.editBytes = d.assembleEditBuffer(text)
}

func (d *DisassemblyViewer) assembleEditBuffer(text string) []byte {
	if !d.hasEditAddr {
		return nil
	}
	stmt := strings.TrimSpace(text)
	if stmt == "" {
		return nil
	}
	encoded, err := disasm.AssembleOne(d.editAddr, strings.ToUpper(stmt))
	if err != nil || len(encoded) == 0 {
		return nil
	}
	return encoded
}

func (d *DisassemblyViewer) openEditInput() bool {
	st := State()
	row, ok := d.currentSelectedRow()
	if !ok || row < 0 || row >= len(st.DisassemblyRows) {
		return false
	}
	ins := st.DisassemblyRows[row]
	text := ins.Mnemonic
	if ins.Operand != "" {
		text += " " + ins.Operand
	}
	d.setFollow(false)
	d.selectedRowHint = row
	d.hasSelectedRowHint = true
	d.selectedAddr = ins.Addr
	d.hasSelectedAddr = true
	d.editAddr = ins.Addr
	d.hasEditAddr = true
	d.editSnapshot = text
	d.inputMode = inputModeEdit
	d.replaceOnNextInput = false
	d.updateEditBuffer(text)
	_ = d.dispatcher.Dispatch(ActionSetInputTarget, "disassembly")
	_ = d.dispatcher.Dispatch(ActionSetInputFocus, true)
	return true
}

func (d *DisassemblyViewer) closeInput() {
	d.replaceOnNextInput = false
	d.inputMode = ""
	d.hasEditAddr = false
	d.editAddr = 0
	d.editSnapshot = ""
	d.editBytes = nil
	_ = d.dispatcher.Dispatch(ActionSetInputTarget, "")
	_ = d.dispatcher.Dispatch(ActionSetInputFocus, false)
}

func (d *DisassemblyViewer) renderEditInput(input string) {
	row, ok := d.findRowByAddr(d.editAddr)
	if !ok {
		var rowOK bool
		row, rowOK = d.currentSelectedRow()
		if !rowOK {
			return
		}
	}
	w := d.Window()
	if row < 0 || row >= w.Height() {
		return
	}
	text := input
	if len([]rune(text)) > asmEditMaxLen {
		text = string([]rune(text)[:asmEditMaxLen])
	}
	valid := len(d.assembleEditBuffer(text)) > 0
	attr := ColorText.Attr()
	if !valid {
		attr = ColorInputInvalid.Attr()
	}
	attr |= AttrReverse()
	if asmEditX >= w.Width() {
		return
	}
	w.Cursor(asmEditX, row)
	w.Print(text, attr, false)
	w.FillToEOL(' ', attr)
}

func (d *DisassemblyViewer) findRowByAddr(addr uint16) (int, bool) {
	rows := State().DisassemblyRows
	for i, row := range rows {
		if row.Addr == addr {
			return i, true
		}
	}
	return 0, false
}

func (d *DisassemblyViewer) setFollow(enabled bool) {
	d.follow = enabled
	d.Window().SetTagActive("follow", enabled)
}

func (d *DisassemblyViewer) currentSelectedRow() (int, bool) {
	rows := State().DisassemblyRows
	visCount := min(len(rows), d.Window().Height())
	if visCount <= 0 {
		return 0, false
	}
	if d.hasSelectedAddr {
		for i, row := range rows {
			if row.Addr == d.selectedAddr {
				if i >= visCount {
					return visCount - 1, true
				}
				return i, true
			}
		}
	}
	if d.hasSelectedRowHint {
		idx := d.selectedRowHint
		if idx < 0 {
			idx = 0
		}
		if idx >= visCount {
			idx = visCount - 1
		}
		return idx, true
	}
	if sel, ok := d.grid.GridSelected(); ok {
		if sel < 0 {
			sel = 0
		}
		if sel >= visCount {
			sel = visCount - 1
		}
		return sel, true
	}
	return 0, true
}

func (d *DisassemblyViewer) moveSelectedRows(delta int) bool {
	rows := State().DisassemblyRows
	visCount := min(len(rows), d.Window().Height())
	if visCount <= 0 {
		d.hasSelectedAddr = false
		d.hasSelectedRowHint = false
		return false
	}
	cur, ok := d.currentSelectedRow()
	if !ok {
		return false
	}
	next := cur + delta
	if next < 0 {
		next = 0
	}
	if next >= visCount {
		next = visCount - 1
	}
	if next != cur {
		d.selectedRowHint = next
		d.hasSelectedRowHint = true
		d.selectedAddr = rows[next].Addr
		d.hasSelectedAddr = true
		idx := next
		d.grid.SetGridSelected(&idx)
		return true
	}
	d.selectedRowHint = cur
	d.hasSelectedRowHint = true
	d.hasSelectedAddr = false
	return false
}

func findAddrIndex(rows []disasm.DecodedInstruction, addr uint16) int {
	for i, r := range rows {
		if r.Addr == addr {
			return i
		}
	}
	return -1
}

func buildDisasmSnapshot(pc uint16, addr uint16, rows []DisasmRow) string {
	parts := make([]string, 0, len(rows)+2)
	parts = append(parts, formatHex16(pc), formatHex16(addr))
	for _, row := range rows {
		target := "-"
		if row.FlowTarget != nil {
			target = formatHex16(*row.FlowTarget)
		}
		operandAddr := "-"
		if row.HasOperandAddr {
			operandAddr = strconv.Itoa(row.OperandAddrPos[0]) + "," + strconv.Itoa(row.OperandAddrPos[1])
		}
		parts = append(parts, strings.Join([]string{
			formatHex16(row.Addr),
			row.RawText,
			row.AsmText,
			row.Mnemonic,
			row.Operand,
			row.Comment,
			target,
			operandAddr,
		}, ":"))
	}
	return strings.Join(parts, "|")
}

func stLimit(v, minV int) int {
	if v < minV {
		return minV
	}
	return v
}

func padLeft(text string, n int, fill rune) string {
	r := []rune(text)
	for len(r) < n {
		r = append([]rune{fill}, r...)
	}
	if len(r) > n {
		r = r[len(r)-n:]
	}
	return string(r)
}

func trimLastRune(text string) string {
	r := []rune(text)
	if len(r) == 0 {
		return ""
	}
	return string(r[:len(r)-1])
}
