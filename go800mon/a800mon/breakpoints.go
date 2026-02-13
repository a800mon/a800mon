package a800mon

import (
	"context"
	"fmt"
	"strings"

	"go800mon/internal/memory"
)

var bpConditionTypes = map[string]byte{
	"pc":     1,
	"a":      2,
	"x":      3,
	"y":      4,
	"s":      5,
	"read":   6,
	"write":  7,
	"access": 8,
}

var bpTypeNames = map[byte]string{
	1: "pc",
	2: "a",
	3: "x",
	4: "y",
	5: "s",
	6: "read",
	7: "write",
	8: "access",
	9: "mem",
}

var bpOpIDs = map[string]byte{
	"<":  1,
	"<=": 2,
	"=":  3,
	"==": 3,
	"!=": 4,
	">=": 5,
	">":  6,
}

var bpOpNames = map[byte]string{
	1: "<",
	2: "<=",
	3: "==",
	4: "!=",
	5: ">=",
	6: ">",
}

type BreakpointsViewer struct {
	BaseVisualComponent
	rpc          *RpcClient
	screen       *Screen
	dispatcher   *ActionDispatcher
	lastSnapshot string
	lastStateSeq uint64
	hasSnapshot  bool
}

func NewBreakpointsViewer(rpc *RpcClient, window *Window) *BreakpointsViewer {
	return &BreakpointsViewer{
		BaseVisualComponent: NewBaseVisualComponent(window),
		rpc:                 rpc,
	}
}

func (v *BreakpointsViewer) BindInput(screen *Screen, dispatcher *ActionDispatcher) {
	v.screen = screen
	v.dispatcher = dispatcher
}

func (v *BreakpointsViewer) Update(ctx context.Context) (bool, error) {
	st := State()
	if !st.BreakpointsSupported {
		return false, nil
	}
	if v.hasSnapshot && v.lastStateSeq == st.StateSeq {
		return false, nil
	}
	v.lastStateSeq = st.StateSeq

	list, err := v.rpc.BPList(ctx)
	if err != nil {
		return false, nil
	}
	clauses := make([]BreakpointClauseRow, 0, len(list.Clauses))
	for _, clause := range list.Clauses {
		conds := make([]BreakpointConditionRow, 0, len(clause))
		for _, cond := range clause {
			conds = append(conds, BreakpointConditionRow{
				CondType: cond.Type,
				Op:       cond.Op,
				Addr:     cond.Addr,
				Value:    cond.Value,
			})
		}
		clauses = append(clauses, BreakpointClauseRow{Conditions: conds})
	}
	snapshot := buildBreakpointsSnapshot(list.Enabled, clauses)
	if v.hasSnapshot && snapshot == v.lastSnapshot {
		return false, nil
	}
	v.hasSnapshot = true
	v.lastSnapshot = snapshot
	if v.dispatcher != nil {
		v.dispatcher.updateBreakpoints(list.Enabled, clauses)
	}
	return true, nil
}

func (v *BreakpointsViewer) Render(_force bool) {
	st := State()
	w := v.Window()
	ih := w.Height()
	if ih <= 0 {
		return
	}
	w.Cursor(0, 0)
	w.SetTagActive("bp_enabled", st.BreakpointsEnabled)

	maxRows := ih
	if len(st.Breakpoints) == 0 {
		if maxRows > 0 {
			w.Print("No breakpoint clauses.", ColorComment.Attr(), false)
			w.ClearToEOL(false)
			w.Newline()
			w.ClearToBottom()
		}
		return
	}
	drawn := 0
	for i := 0; i < len(st.Breakpoints) && i < maxRows; i++ {
		w.Print(fmt.Sprintf("#%02d ", i+1), ColorAddress.Attr(), false)
		v.printClause(st.Breakpoints[i])
		w.ClearToEOL(false)
		w.Newline()
		drawn++
	}
	if drawn < ih {
		w.ClearToBottom()
	}
}

func (v *BreakpointsViewer) HandleInput(ch int) bool {
	if v.screen == nil {
		return false
	}
	if v.screen.Focused() != v.Window() {
		return false
	}
	return false
}

func (v *BreakpointsViewer) printClause(clause BreakpointClauseRow) {
	for i, cond := range clause.Conditions {
		if i > 0 {
			v.Window().Print(" && ", ColorText.Attr(), false)
		}
		v.printCondition(cond)
	}
}

func (v *BreakpointsViewer) printCondition(cond BreakpointConditionRow) {
	op := bpOpSymbol(cond.Op)
	if cond.CondType == 9 {
		v.Window().Print("mem[", ColorText.Attr(), false)
		v.Window().Print(formatHex16(cond.Addr), ColorAddress.Attr(), false)
		v.Window().Print("]", ColorText.Attr(), false)
	} else {
		v.Window().Print(bpTypeName(cond.CondType), ColorText.Attr(), false)
	}
	v.Window().Print(" "+op+" ", ColorText.Attr(), false)
	if cond.CondType == 2 || cond.CondType == 3 || cond.CondType == 4 || cond.CondType == 5 {
		v.Window().Print(fmt.Sprintf("%02X", cond.Value), ColorAddress.Attr(), false)
		return
	}
	v.Window().Print(formatHex16(cond.Value), ColorAddress.Attr(), false)
}

func bpTypeName(condType byte) string {
	name := bpTypeNames[condType]
	if name != "" {
		return name
	}
	return fmt.Sprintf("type%d", condType)
}

func bpOpSymbol(op byte) string {
	name := bpOpNames[op]
	if name != "" {
		return name
	}
	return fmt.Sprintf("op%d", op)
}

func buildBreakpointsSnapshot(enabled bool, clauses []BreakpointClauseRow) string {
	parts := make([]string, 0, len(clauses)+1)
	parts = append(parts, fmt.Sprintf("enabled:%t", enabled))
	for _, clause := range clauses {
		items := make([]string, 0, len(clause.Conditions))
		for _, cond := range clause.Conditions {
			items = append(items, fmt.Sprintf("%d:%d:%04X:%04X", cond.CondType, cond.Op, cond.Addr, cond.Value))
		}
		parts = append(parts, strings.Join(items, ","))
	}
	return strings.Join(parts, "|")
}

func splitBPExpression(expr string) (string, string, string, bool) {
	text := strings.TrimSpace(expr)
	for _, op := range []string{"<=", ">=", "==", "!=", "=", "<", ">"} {
		pos := strings.Index(text, op)
		if pos <= 0 {
			continue
		}
		left := strings.TrimSpace(text[:pos])
		right := strings.TrimSpace(text[pos+len(op):])
		if right == "" {
			break
		}
		return left, op, right, true
	}
	return "", "", "", false
}

func parseBPCondition(expr string) (BreakpointCondition, error) {
	left, opText, valueText, ok := splitBPExpression(expr)
	if !ok {
		return BreakpointCondition{}, fmt.Errorf("Invalid breakpoint condition: %s", expr)
	}
	op, ok := bpOpIDs[opText]
	if !ok {
		return BreakpointCondition{}, fmt.Errorf("Invalid breakpoint operator in condition: %s", expr)
	}
	leftKey := strings.ToLower(strings.TrimSpace(left))
	cond := BreakpointCondition{
		Op:   op,
		Addr: 0,
	}
	if t, ok := bpConditionTypes[leftKey]; ok {
		cond.Type = t
	} else if strings.HasPrefix(leftKey, "mem[") && strings.HasSuffix(leftKey, "]") {
		addr, err := memory.ParseHex(leftKey[4 : len(leftKey)-1])
		if err != nil {
			return BreakpointCondition{}, fmt.Errorf("Invalid memory address in condition: %s", expr)
		}
		cond.Type = 9
		cond.Addr = addr
	} else if strings.HasPrefix(leftKey, "mem:") {
		addr, err := memory.ParseHex(leftKey[4:])
		if err != nil {
			return BreakpointCondition{}, fmt.Errorf("Invalid memory address in condition: %s", expr)
		}
		cond.Type = 9
		cond.Addr = addr
	} else {
		return BreakpointCondition{}, fmt.Errorf("Invalid breakpoint source in condition: %s", expr)
	}
	value, err := memory.ParseHex(valueText)
	if err != nil {
		return BreakpointCondition{}, fmt.Errorf("Invalid breakpoint value in condition: %s", expr)
	}
	cond.Value = value
	return cond, nil
}

func formatBPValue(condType byte, value uint16) string {
	if condType == 2 || condType == 3 || condType == 4 || condType == 5 {
		return fmt.Sprintf("$%02X", value)
	}
	return fmt.Sprintf("$%04X", value)
}

func formatBPCondition(cond BreakpointCondition) string {
	op := bpOpSymbol(cond.Op)
	if cond.Type == 9 {
		return fmt.Sprintf("mem[%04X] %s %s", cond.Addr, op, formatBPValue(cond.Type, cond.Value))
	}
	name := bpTypeName(cond.Type)
	return fmt.Sprintf("%s %s %s", name, op, formatBPValue(cond.Type, cond.Value))
}
