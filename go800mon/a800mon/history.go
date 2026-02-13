package a800mon

import (
	"context"
	"fmt"
	"strings"

	"go800mon/internal/disasm"
)

type HistoryViewer struct {
	BaseVisualComponent
	rpc          *RpcClient
	reverseOrder bool
	lastSnapshot string
	nextRow      *DisasmRow
	decodeCache  map[string]DisasmRow
}

func NewHistoryViewer(rpc *RpcClient, window *Window, reverseOrder bool) *HistoryViewer {
	return &HistoryViewer{
		BaseVisualComponent: NewBaseVisualComponent(window),
		rpc:                 rpc,
		reverseOrder:        reverseOrder,
		decodeCache:         map[string]DisasmRow{},
	}
}

func (h *HistoryViewer) Update(ctx context.Context) (bool, error) {
	if State().InputFocus {
		return false, nil
	}
	entries, err := h.rpc.History(ctx)
	if err != nil {
		return false, nil
	}
	store.setHistory(entries)
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
	w := h.Window()
	ih := w.Height()
	if ih <= 0 {
		return
	}
	w.Cursor(0, 0)

	next := h.nextRow
	if next == nil {
		row := DisasmRow{Addr: st.CPU.PC, RawText: "", AsmText: st.CPUDisasm}
		next = &row
	}

	if h.reverseOrder {
		limit := ih - 1
		if limit < 0 {
			limit = 0
		}
		rows := st.History
		if len(rows) > limit {
			rows = rows[:limit]
		}
		rows = reverseHistory(rows)
		for _, e := range rows {
			h.printHistoryRow(e)
		}
		h.printDecodedRow(*next, AttrReverse())
		w.FillToEOL(' ', AttrReverse())
		w.Newline()
	} else {
		h.printDecodedRow(*next, AttrReverse())
		w.FillToEOL(' ', AttrReverse())
		w.Newline()
		rows := st.History
		if len(rows) > ih-1 {
			rows = rows[:ih-1]
		}
		for _, e := range rows {
			h.printHistoryRow(e)
		}
	}
	w.ClearToBottom()
}

func (h *HistoryViewer) printHistoryRow(entry CpuHistoryEntry) {
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
	h.printDecodedRow(row, 0)
	h.Window().ClearToEOL(false)
	h.Window().Newline()
}

func (h *HistoryViewer) printDecodedRow(row DisasmRow, rev int) {
	w := h.Window()
	w.Print(formatHex16(row.Addr)+":", ColorAddress.Attr()|rev, false)
	w.Print(" ", rev, false)
	w.Print(padRight(row.RawText, 8)+" ", rev, false)
	printAsmRow(w, row, rev)
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
