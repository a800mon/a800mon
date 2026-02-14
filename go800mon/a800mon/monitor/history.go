package monitor

import (
	"context"
	"fmt"
	"strings"

	. "go800mon/a800mon"
	"go800mon/internal/disasm"
)

var historyFlowMnemonics = map[string]struct{}{
	"JMP": {}, "JSR": {}, "BCC": {}, "BCS": {}, "BEQ": {}, "BMI": {},
	"BNE": {}, "BPL": {}, "BVC": {}, "BVS": {}, "BRA": {},
}

type HistoryViewer struct {
	BaseWindowComponent
	rpc          *RpcClient
	grid         *GridWidget
	reverseOrder bool
	lastSnapshot string
	nextRow      *DisasmRow
	decodeCache  map[string]DisasmRow
	followLive   bool
}

func NewHistoryViewer(rpc *RpcClient, window *Window, reverseOrder bool) *HistoryViewer {
	grid := NewGridWidget(window)
	grid.SetColumnGap(1)
	grid.AddColumn("address", 5, ColorAddress.Attr(), nil)
	grid.AddColumn("opcode1", 2, ColorText.Attr(), nil)
	grid.AddColumn("opcode2", 2, ColorText.Attr(), nil)
	grid.AddColumn("opcode3", 2, ColorText.Attr(), nil)
	grid.AddColumn("mnemonic", 4, ColorMnemonic.Attr(), nil)
	grid.AddColumn("argument", 14, ColorText.Attr(), historyArgumentAttr)
	grid.AddColumn("comment", 0, ColorComment.Attr(), nil)
	return &HistoryViewer{
		BaseWindowComponent: NewBaseWindowComponent(grid.Window()),
		rpc:                 rpc,
		grid:                grid,
		reverseOrder:        reverseOrder,
		decodeCache:         map[string]DisasmRow{},
		followLive:          true,
	}
}

func (h *HistoryViewer) Update(ctx context.Context) (bool, error) {
	entries, err := h.rpc.History(ctx)
	if err != nil {
		return false, nil
	}
	if app := h.App(); app != nil {
		app.DispatchAction(ActionSetHistory, entries)
	}
	st := State()
	if code, err := h.rpc.ReadMemory(ctx, st.CPU.PC, 3); err == nil {
		if ins := disasm.DecodeOne(st.CPU.PC, code); ins != nil {
			row := disasmToRow(*ins)
			h.nextRow = &row
		}
	}
	snap := buildHistorySnapshot(st.CPU.PC, entries, h.nextRow)
	if h.lastSnapshot == snap {
		return false, nil
	}
	h.lastSnapshot = snap
	return true, nil
}

func buildHistorySnapshot(pc uint16, entries []CpuHistoryEntry, next *DisasmRow) string {
	parts := make([]string, 0, len(entries)+2)
	parts = append(parts, fmt.Sprintf("pc:%04X", pc))
	for _, e := range entries {
		parts = append(parts, fmt.Sprintf("%04X:%02X:%02X:%02X", e.PC, e.Op0, e.Op1, e.Op2))
	}
	if next != nil {
		parts = append(parts, fmt.Sprintf("next:%04X:%s:%s", next.Addr, next.RawText, next.AsmText))
	}
	return strings.Join(parts, "|")
}

func (h *HistoryViewer) Render(_force bool) {
	st := State()
	next := h.nextRow
	if next == nil {
		row := DisasmRow{Addr: st.CPU.PC, RawText: "", Comment: st.CPUDisasm}
		next = &row
	}
	rows := make([][]string, 0, len(st.History)+1)
	selected := 0
	if h.reverseOrder {
		for _, e := range reverseHistory(st.History) {
			rows = append(rows, h.historyRowCells(e))
		}
		rows = append(rows, h.decodedRowCells(*next))
		selected = len(rows) - 1
	} else {
		rows = append(rows, h.decodedRowCells(*next))
		for _, e := range st.History {
			rows = append(rows, h.historyRowCells(e))
		}
		selected = 0
	}
	h.grid.SetData(rows)
	if len(rows) == 0 {
		h.grid.SetSelectedRow(nil)
	} else if h.followLive {
		h.grid.SetSelectedRow(&selected)
	} else if _, ok := h.grid.SelectedRow(); !ok {
		h.grid.SetSelectedRow(&selected)
	}
	h.grid.Render()
}

func (h *HistoryViewer) HandleInput(ch int) bool {
	if !h.grid.HandleInput(ch) {
		return false
	}
	if h.reverseOrder {
		h.followLive = ch == KeyEnd() || ch == 360
	} else {
		h.followLive = ch == KeyHome() || ch == 262
	}
	return true
}

func (h *HistoryViewer) decodeHistoryRow(entry CpuHistoryEntry) DisasmRow {
	key := fmt.Sprintf("%04X-%02X-%02X-%02X", entry.PC, entry.Op0, entry.Op1, entry.Op2)
	row, ok := h.decodeCache[key]
	if !ok {
		if ins := disasm.DecodeOne(entry.PC, entry.OpBytes()); ins != nil {
			row = disasmToRow(*ins)
		} else {
			row = DisasmRow{Addr: entry.PC}
		}
		h.decodeCache[key] = row
		if len(h.decodeCache) > 4096 {
			h.decodeCache = map[string]DisasmRow{}
		}
	}
	return row
}

func (h *HistoryViewer) historyRowCells(entry CpuHistoryEntry) []string {
	return h.decodedRowCells(h.decodeHistoryRow(entry))
}

func (h *HistoryViewer) decodedRowCells(row DisasmRow) []string {
	op1, op2, op3 := opcodeColumns(row.RawText)
	return []string{
		formatHex16(row.Addr) + ":",
		op1,
		op2,
		op3,
		row.Mnemonic,
		row.Operand,
		row.Comment,
	}
}

func disasmToRow(ins disasm.DecodedInstruction) DisasmRow {
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
	return row
}

func reverseHistory(entries []CpuHistoryEntry) []CpuHistoryEntry {
	n := len(entries)
	out := make([]CpuHistoryEntry, 0, n)
	for i := n - 1; i >= 0; i-- {
		out = append(out, entries[i])
	}
	return out
}

func opcodeColumns(rawText string) (string, string, string) {
	parts := strings.Fields(rawText)
	op1 := ""
	op2 := ""
	op3 := ""
	if len(parts) > 0 {
		op1 = parts[0]
	}
	if len(parts) > 1 {
		op2 = parts[1]
	}
	if len(parts) > 2 {
		op3 = parts[2]
	}
	return op1, op2, op3
}

func historyArgumentAttr(_value string, row []string) int {
	if len(row) <= 4 {
		return ColorText.Attr()
	}
	if _, ok := historyFlowMnemonics[strings.ToUpper(strings.TrimSpace(row[4]))]; ok {
		return ColorAddress.Attr()
	}
	return ColorText.Attr()
}
