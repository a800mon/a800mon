package a800mon

import (
	"context"
	"fmt"
	"regexp"
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
	"<>": 4,
	"!=": 4,
	">=": 5,
	">":  6,
}

var bpOpNames = map[byte]string{
	1: "<",
	2: "<=",
	3: "==",
	4: "<>",
	5: ">=",
	6: ">",
}

var bpAndWordRe = regexp.MustCompile(`(?i)\bAND\b`)
var bpOrWordRe = regexp.MustCompile(`(?i)\bOR\b`)

type BreakpointsViewer struct {
	BaseVisualComponent
	rpc              *RpcClient
	screen           *Screen
	dispatcher       *ActionDispatcher
	lastSnapshot     string
	lastStateSeq     uint64
	hasSnapshot      bool
	selected         *int
	inputSnapshot    string
	inputInvalid     bool
	parsedClauses    [][]BreakpointCondition
	hasParsedClauses bool
	pendingAdd       [][]BreakpointCondition
	hasPendingAdd    bool
	pendingDelete    *int
	pendingEnabled   *bool
	refreshRequested bool
	inputWidget      *InputWidget
}

func NewBreakpointsViewer(rpc *RpcClient, window *Window) *BreakpointsViewer {
	v := &BreakpointsViewer{
		BaseVisualComponent: NewBaseVisualComponent(window),
		rpc:                 rpc,
	}
	v.inputWidget = NewInputWidget(window)
	v.inputWidget.SetOnChange(v.onInputChange)
	return v
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
	changed := false
	if v.pendingDelete != nil {
		idx := *v.pendingDelete
		v.pendingDelete = nil
		if err := v.rpc.BPDeleteClause(ctx, uint16(idx)); err == nil {
			v.refreshRequested = true
			changed = true
		}
	}
	if v.hasPendingAdd {
		clauses := append([][]BreakpointCondition(nil), v.pendingAdd...)
		v.pendingAdd = nil
		v.hasPendingAdd = false
		for _, clause := range clauses {
			conds := append([]BreakpointCondition(nil), clause...)
			if _, err := v.rpc.BPAddClause(ctx, conds); err == nil {
				v.refreshRequested = true
				changed = true
				continue
			}
			break
		}
	}
	if v.pendingEnabled != nil {
		enabled := *v.pendingEnabled
		v.pendingEnabled = nil
		if _, err := v.rpc.BPSetEnabled(ctx, enabled); err == nil {
			v.refreshRequested = true
			changed = true
		}
	}
	if v.hasSnapshot && !v.refreshRequested && v.lastStateSeq == st.StateSeq {
		return changed, nil
	}
	v.lastStateSeq = st.StateSeq

	list, err := v.rpc.BPList(ctx)
	if err != nil {
		return changed, nil
	}
	v.refreshRequested = false
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
	v.clampSelected(len(clauses))
	snapshot := buildBreakpointsSnapshot(list.Enabled, clauses)
	if v.hasSnapshot && snapshot == v.lastSnapshot {
		return changed, nil
	}
	v.hasSnapshot = true
	v.lastSnapshot = snapshot
	if v.dispatcher != nil {
		v.dispatcher.updateBreakpoints(list.Enabled, clauses)
		return true, nil
	}
	return changed, nil
}

func (v *BreakpointsViewer) Render(_force bool) {
	st := State()
	w := v.Window()
	ih := w.Height()
	if ih <= 0 {
		return
	}
	hasFocus := v.screen != nil && v.screen.Focused() == v.Window()
	inputActive := st.InputFocus && st.InputTarget == "breakpoints"
	rowBase := 0
	if inputActive {
		rowBase = 1
	}
	maxRows := ih - rowBase
	if maxRows < 0 {
		maxRows = 0
	}
	w.Cursor(0, rowBase)
	w.SetTagActive("bp_enabled", st.BreakpointsEnabled)

	if inputActive {
		w.Cursor(0, 0)
		color := ColorText
		if v.inputInvalid {
			color = ColorInputInvalid
		}
		attr := color.Attr() | AttrReverse()
		w.Print(st.InputBuffer, attr, false)
		w.FillToEOL(' ', attr)
		w.Cursor(0, rowBase)
	}

	if len(st.Breakpoints) == 0 {
		if maxRows > 0 {
			w.Cursor(0, rowBase)
			w.Print("No breakpoint clauses.", ColorComment.Attr(), false)
			w.ClearToEOL(false)
			w.Newline()
			w.ClearToBottom()
		}
		return
	}
	drawn := 0
	for i := 0; i < len(st.Breakpoints) && i < maxRows; i++ {
		rev := 0
		if hasFocus && v.selected != nil && *v.selected == i {
			rev = AttrReverse()
		}
		w.Print(fmt.Sprintf("#%02d ", i+1), ColorAddress.Attr()|rev, false)
		v.printClause(st.Breakpoints[i], rev)
		w.ClearToEOL(false)
		w.Newline()
		drawn++
	}
	if drawn < maxRows {
		w.ClearToBottom()
	}
}

func (v *BreakpointsViewer) HandleInput(ch int) bool {
	st := State()
	if v.screen == nil {
		return false
	}
	if st.InputFocus {
		if st.InputTarget != "breakpoints" {
			return false
		}
		return v.handleTextInput(ch)
	}
	if v.screen.Focused() != v.Window() {
		return false
	}
	if ch == int('/') {
		v.openInput("")
		return true
	}
	if ch == KeyUp() || ch == KeyDown() {
		if len(st.Breakpoints) == 0 {
			return true
		}
		if v.selected == nil {
			idx := 0
			if ch == KeyUp() {
				idx = len(st.Breakpoints) - 1
			}
			v.selected = &idx
			return true
		}
		idx := *v.selected
		if ch == KeyUp() && idx > 0 {
			idx--
			v.selected = &idx
		}
		if ch == KeyDown() && idx < len(st.Breakpoints)-1 {
			idx++
			v.selected = &idx
		}
		return true
	}
	if ch == KeyDelete() || ch == 330 {
		v.queueDeleteSelected()
		return true
	}
	if ch == int('e') || ch == int('E') {
		enabled := !st.BreakpointsEnabled
		v.pendingEnabled = &enabled
		return true
	}
	return false
}

func (v *BreakpointsViewer) printClause(clause BreakpointClauseRow, rev int) {
	for i, cond := range clause.Conditions {
		if i > 0 {
			v.Window().Print(" AND ", ColorText.Attr()|rev, false)
		}
		v.printCondition(cond, rev)
	}
}

func (v *BreakpointsViewer) printCondition(cond BreakpointConditionRow, rev int) {
	op := bpOpSymbol(cond.Op)
	if cond.CondType == 9 {
		v.Window().Print("mem[", ColorText.Attr()|rev, false)
		v.Window().Print(formatHex16(cond.Addr), ColorAddress.Attr()|rev, false)
		v.Window().Print("]", ColorText.Attr()|rev, false)
	} else {
		v.Window().Print(bpTypeName(cond.CondType), ColorText.Attr()|rev, false)
	}
	v.Window().Print(" "+op+" ", ColorText.Attr()|rev, false)
	if cond.CondType == 2 || cond.CondType == 3 || cond.CondType == 4 || cond.CondType == 5 {
		v.Window().Print(fmt.Sprintf("%02X", cond.Value), ColorAddress.Attr()|rev, false)
		return
	}
	v.Window().Print(formatHex16(cond.Value), ColorAddress.Attr()|rev, false)
}

func (v *BreakpointsViewer) queueDeleteSelected() {
	st := State()
	if v.selected == nil {
		return
	}
	idx := *v.selected
	if idx < 0 || idx >= len(st.Breakpoints) {
		return
	}
	v.pendingDelete = &idx
	if idx >= len(st.Breakpoints)-1 {
		if len(st.Breakpoints) <= 1 {
			v.selected = nil
		} else {
			next := len(st.Breakpoints) - 2
			v.selected = &next
		}
	}
}

func (v *BreakpointsViewer) openInput(initial string) {
	if v.dispatcher == nil {
		return
	}
	v.inputSnapshot = initial
	v.inputInvalid = false
	v.parsedClauses = nil
	v.hasParsedClauses = false
	v.inputWidget.Activate(initial)
	v.inputWidget.SetInvalid(false)
	_ = v.dispatcher.Dispatch(ActionSetInputBuffer, v.inputWidget.Buffer())
	_ = v.dispatcher.Dispatch(ActionSetInputTarget, "breakpoints")
	_ = v.dispatcher.Dispatch(ActionSetInputFocus, true)
}

func (v *BreakpointsViewer) closeInput() {
	if v.dispatcher == nil {
		return
	}
	v.inputInvalid = false
	v.parsedClauses = nil
	v.hasParsedClauses = false
	v.inputWidget.SetInvalid(false)
	v.inputWidget.Deactivate()
	_ = v.dispatcher.Dispatch(ActionSetInputFocus, false)
	_ = v.dispatcher.Dispatch(ActionSetInputTarget, "")
}

func (v *BreakpointsViewer) onInputChange(text string) {
	trimmed := strings.TrimSpace(text)
	if trimmed == "" {
		v.inputInvalid = false
		v.parsedClauses = nil
		v.hasParsedClauses = false
		v.inputWidget.SetInvalid(false)
		return
	}
	clauses, err := parseBPClauses(trimmed)
	if err != nil {
		v.inputInvalid = true
		v.parsedClauses = nil
		v.hasParsedClauses = false
		v.inputWidget.SetInvalid(true)
		return
	}
	v.inputInvalid = false
	v.parsedClauses = clauses
	v.hasParsedClauses = true
	v.inputWidget.SetInvalid(false)
}

func (v *BreakpointsViewer) handleTextInput(ch int) bool {
	if v.dispatcher == nil {
		return false
	}
	if ch == 27 {
		_ = v.inputWidget.SetBuffer(v.inputSnapshot)
		_ = v.dispatcher.Dispatch(ActionSetInputBuffer, v.inputSnapshot)
		v.closeInput()
		return true
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		if v.inputInvalid {
			return true
		}
		if v.hasParsedClauses {
			v.pendingAdd = append([][]BreakpointCondition(nil), v.parsedClauses...)
			v.hasPendingAdd = true
		}
		v.closeInput()
		return true
	}
	if ch == KeyBackspace() || ch == 127 || ch == 8 {
		if v.inputWidget.Backspace() {
			_ = v.dispatcher.Dispatch(ActionSetInputBuffer, v.inputWidget.Buffer())
		}
		return true
	}
	if v.inputWidget.AppendChar(ch) {
		_ = v.dispatcher.Dispatch(ActionSetInputBuffer, v.inputWidget.Buffer())
		return true
	}
	return true
}

func (v *BreakpointsViewer) clampSelected(rowCount int) {
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
	for _, op := range []string{"<=", ">=", "==", "<>", "!=", "=", "<", ">"} {
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

func parseBPClause(expr string) ([]BreakpointCondition, error) {
	clauses, err := parseBPClauses(expr)
	if err != nil {
		return nil, err
	}
	if len(clauses) != 1 {
		return nil, fmt.Errorf("Use a single OR clause in this context.")
	}
	return clauses[0], nil
}

func normalizeBPLogic(expr string) string {
	text := bpAndWordRe.ReplaceAllString(expr, "&&")
	return bpOrWordRe.ReplaceAllString(text, "||")
}

func parseBPClauses(expr string) ([][]BreakpointCondition, error) {
	text := strings.TrimSpace(normalizeBPLogic(expr))
	if text == "" {
		return nil, fmt.Errorf("Breakpoint clause is empty.")
	}
	rawClauses := strings.Split(text, "||")
	if len(rawClauses) == 0 {
		return nil, fmt.Errorf("Invalid breakpoint clause.")
	}
	clauses := make([][]BreakpointCondition, 0, len(rawClauses))
	for _, rawClause := range rawClauses {
		clauseText := strings.TrimSpace(rawClause)
		if clauseText == "" {
			return nil, fmt.Errorf("Invalid breakpoint clause.")
		}
		parts := strings.Split(clauseText, "&&")
		if len(parts) == 0 {
			return nil, fmt.Errorf("Invalid breakpoint clause.")
		}
		conds := make([]BreakpointCondition, 0, len(parts))
		for _, part := range parts {
			item := strings.TrimSpace(part)
			if item == "" {
				return nil, fmt.Errorf("Invalid breakpoint clause.")
			}
			cond, err := parseBPCondition(item)
			if err != nil {
				return nil, err
			}
			conds = append(conds, cond)
		}
		clauses = append(clauses, conds)
	}
	return clauses, nil
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
