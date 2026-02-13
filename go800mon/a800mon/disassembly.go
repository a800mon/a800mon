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
	screen             *Screen
	dispatcher         *ActionDispatcher
	follow             bool
	inputSnapshot      string
	replaceOnNextInput bool
	currentAddr        uint16
	hasCurrentAddr     bool
	lastSnapshot       string
	pendingNav         navAction
	pendingSteps       int
}

type navAction int

const (
	navNone navAction = iota
	navHome
	navEnd
	navDown
	navUp
)

func NewDisassemblyViewer(rpc *RpcClient, window *Window) *DisassemblyViewer {
	return &DisassemblyViewer{
		BaseVisualComponent: NewBaseVisualComponent(window),
		rpc:                 rpc,
		follow:              true,
	}
}

func (d *DisassemblyViewer) BindInput(screen *Screen, dispatcher *ActionDispatcher) {
	d.screen = screen
	d.dispatcher = dispatcher
}

func (d *DisassemblyViewer) EnableFollow() {
	d.follow = true
	d.Window().SetTagActive("follow", true)
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

	if !d.hasCurrentAddr {
		if st.DisassemblyAddr != nil {
			d.currentAddr = *st.DisassemblyAddr
		} else {
			d.currentAddr = st.CPU.PC
		}
		d.hasCurrentAddr = true
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
		if pc < d.currentAddr || !containsAddr(decoded, pc) {
			d.currentAddr = pc
			decoded, err = d.fetchRows(ctx, d.currentAddr)
			if err != nil {
				return false, nil
			}
		}
	}

	rows := make([]DisasmRow, 0, len(decoded))
	for _, ins := range decoded {
		row := DisasmRow{
			Addr:     ins.Addr,
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
		if len(rows) >= d.Window().Height() {
			break
		}
	}
	return rows, nil
}

func (d *DisassemblyViewer) Render(_force bool) {
	st := State()
	w := d.Window()
	w.SetTagActive("follow", d.follow)
	w.Cursor(0, 0)
	rowCount := 0
	for i, row := range st.DisassemblyRows {
		rev := 0
		if row.Addr == st.CPU.PC && !(st.InputFocus && i == 0) {
			rev = AttrReverse()
		}
		w.Print(formatHex16(row.Addr)+":", ColorAddress.Attr()|rev, false)
		w.Print(" ", rev, false)
		w.Print(padRight(row.RawText, 8)+" ", rev, false)
		printAsmRow(w, row, rev)
		w.FillToEOL(' ', rev)
		w.Newline()
		rowCount++
	}
	if rowCount < w.Height() {
		w.Cursor(0, rowCount)
		w.ClearToBottom()
	}
	if st.InputFocus {
		text := strings.ToUpper(st.InputBuffer)
		if len(text) > 4 {
			text = text[len(text)-4:]
		}
		text = padLeft(text, 4, '0')
		w.Cursor(0, 0)
		w.Print(text+"  ", ColorAddress.Attr()|AttrReverse(), false)
	}
}

func (d *DisassemblyViewer) HandleInput(ch int) bool {
	st := State()
	if st.InputFocus {
		if st.InputTarget != "disassembly" {
			return false
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
	if lower == int('f') {
		d.follow = !d.follow
		d.Window().SetTagActive("follow", d.follow)
		return true
	}
	if ch == KeyHome() {
		d.follow = false
		d.queueNav(navHome, 0)
		return true
	}
	if ch == KeyDown() || ch == KeyPageDown() {
		d.follow = false
		steps := 1
		if ch == KeyPageDown() {
			steps = d.Window().Height() - 1
			if steps < 1 {
				steps = 1
			}
		}
		d.queueNav(navDown, steps)
		return true
	}
	if ch == KeyUp() || ch == KeyPageUp() {
		d.follow = false
		steps := 1
		if ch == KeyPageUp() {
			steps = d.Window().Height() - 1
			if steps < 1 {
				steps = 1
			}
		}
		d.queueNav(navUp, steps)
		return true
	}
	if ch == KeyEnd() {
		d.follow = false
		d.queueNav(navEnd, 0)
		return true
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
	_ = d.dispatcher.Dispatch(ActionSetInputBuffer, d.inputSnapshot)
	_ = d.dispatcher.Dispatch(ActionSetInputTarget, "disassembly")
	_ = d.dispatcher.Dispatch(ActionSetInputFocus, true)
	return true
}

func (d *DisassemblyViewer) queueNav(action navAction, steps int) {
	d.pendingNav = action
	d.pendingSteps = steps
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
		_ = d.dispatcher.Dispatch(ActionSetInputTarget, "")
		_ = d.dispatcher.Dispatch(ActionSetInputFocus, false)
		return true
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		text := strings.ToUpper(st.InputBuffer)
		if text != "" {
			d.updateAddressInput(text)
		}
		_ = d.dispatcher.Dispatch(ActionSetInputTarget, "")
		_ = d.dispatcher.Dispatch(ActionSetInputFocus, false)
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

func (d *DisassemblyViewer) updateAddressInput(text string) {
	_ = d.dispatcher.Dispatch(ActionSetInputBuffer, text)
	if text == "" {
		return
	}
	v, err := memory.ParseHex(text)
	if err != nil {
		return
	}
	d.follow = false
	d.currentAddr = v
	d.hasCurrentAddr = true
	d.pendingNav = navNone
	d.pendingSteps = 0
	d.lastSnapshot = ""
	_ = d.dispatcher.Dispatch(ActionSetDisassemblyAddr, d.currentAddr)
}

func containsAddr(rows []disasm.DecodedInstruction, addr uint16) bool {
	for _, r := range rows {
		if r.Addr == addr {
			return true
		}
	}
	return false
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
