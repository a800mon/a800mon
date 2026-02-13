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
	BaseWindowComponent
	rpc              *RpcClient
	grid             *GridWidget
	screen           *Screen
	dispatcher       *ActionDispatcher
	enabled          bool
	clauses          []BreakpointClauseRow
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
	pendingClear     bool
	refreshRequested bool
	clearDialog      *DialogWidget
	inputWidget      *InputWidget
}

func NewBreakpointsViewer(rpc *RpcClient, window *Window) *BreakpointsViewer {
	grid := NewGridWidget(window)
	grid.SetGridColumnGap(0)
	v := &BreakpointsViewer{
		BaseWindowComponent: NewBaseWindowComponent(grid.Window()),
		rpc:                 rpc,
		grid:                grid,
	}
	v.clearDialog = NewDialogWidget(grid.Window())
	v.inputWidget = NewInputWidget(grid.Window())
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
	if v.pendingClear {
		v.pendingClear = false
		if err := v.rpc.BPClear(ctx); err == nil {
			v.selected = nil
			v.refreshRequested = true
			changed = true
		}
	}
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
	v.enabled = list.Enabled
	v.clauses = clauses
	return true, nil
}

func (v *BreakpointsViewer) Render(_force bool) {
	st := State()
	w := v.Window()
	g := v.grid
	ih := w.Height()
	if ih <= 0 {
		return
	}
	dialogActive := v.clearDialog != nil && v.clearDialog.Active()
	inputActive := st.InputFocus && st.InputTarget == "breakpoints"
	rowBase := 0
	if inputActive || dialogActive {
		rowBase = 1
	}
	w.SetTagActive("bp_enabled", v.enabled)
	rows := make([]GridRow, 0, len(v.clauses)+2)
	if rowBase > 0 {
		rows = append(rows, GridRow{{Text: "", Attr: ColorText.Attr()}})
	}

	if len(v.clauses) == 0 {
		rows = append(rows, GridRow{{Text: "No breakpoint clauses.", Attr: ColorComment.Attr()}})
		g.SetGridSelected(nil)
	} else {
		for i, clause := range v.clauses {
			cells := make([]GridCell, 0, 16)
			cells = append(cells, GridCell{Text: fmt.Sprintf("#%02d ", i+1), Attr: ColorAddress.Attr()})
			cells = append(cells, v.clauseCells(clause)...)
			rows = append(rows, cells)
		}
		if v.selected == nil {
			g.SetGridSelected(nil)
		} else {
			idx := *v.selected + rowBase
			g.SetGridSelected(&idx)
		}
	}
	g.SetGridColumnWidths(nil)
	g.SetGridRows(rows)
	g.RenderGrid()

	if dialogActive {
		v.clearDialog.Render()
	} else if inputActive {
		v.inputWidget.Render(false)
	}
}

func (v *BreakpointsViewer) HandleInput(ch int) bool {
	st := State()
	if v.screen == nil {
		return false
	}
	if v.clearDialog != nil && v.clearDialog.Active() {
		result := v.clearDialog.HandleInput(ch)
		if result == DialogInputConfirm {
			v.pendingClear = true
		}
		return !(result == DialogInputNone)
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
	if v.grid.HandleGridNavigationInput(ch) {
		idx, ok := v.grid.GridSelected()
		if !ok {
			v.selected = nil
		} else {
			v.selected = &idx
			v.clampSelected(len(v.clauses))
		}
		return true
	}
	if ch == KeyDelete() || ch == 330 {
		v.queueDeleteSelected()
		return true
	}
	if ch == int('c') || ch == int('C') {
		v.clearDialog.Activate("Clear all breakpoints?", "YES")
		return true
	}
	if ch == int(' ') || ch == int('e') || ch == int('E') {
		enabled := !v.enabled
		v.pendingEnabled = &enabled
		return true
	}
	return false
}

func (v *BreakpointsViewer) clauseCells(clause BreakpointClauseRow) []GridCell {
	cells := make([]GridCell, 0, len(clause.Conditions)*4)
	for i, cond := range clause.Conditions {
		if i > 0 {
			cells = append(cells, GridCell{Text: " AND ", Attr: ColorText.Attr()})
		}
		cells = append(cells, v.conditionCells(cond)...)
	}
	return cells
}

func (v *BreakpointsViewer) conditionCells(cond BreakpointConditionRow) []GridCell {
	cells := make([]GridCell, 0, 5)
	op := bpOpSymbol(cond.Op)
	if cond.CondType == 9 {
		cells = append(cells, GridCell{Text: "mem[", Attr: ColorText.Attr()})
		cells = append(cells, GridCell{Text: formatHex16(cond.Addr), Attr: ColorAddress.Attr()})
		cells = append(cells, GridCell{Text: "]", Attr: ColorText.Attr()})
	} else {
		cells = append(cells, GridCell{Text: bpTypeName(cond.CondType), Attr: ColorText.Attr()})
	}
	cells = append(cells, GridCell{Text: " " + op + " ", Attr: ColorText.Attr()})
	if cond.CondType == 2 || cond.CondType == 3 || cond.CondType == 4 || cond.CondType == 5 {
		cells = append(cells, GridCell{Text: fmt.Sprintf("%02X", cond.Value), Attr: ColorAddress.Attr()})
		return cells
	}
	cells = append(cells, GridCell{Text: formatHex16(cond.Value), Attr: ColorAddress.Attr()})
	return cells
}

func (v *BreakpointsViewer) queueDeleteSelected() {
	if v.selected == nil {
		return
	}
	idx := *v.selected
	if idx < 0 || idx >= len(v.clauses) {
		return
	}
	v.pendingDelete = &idx
	if idx >= len(v.clauses)-1 {
		if len(v.clauses) <= 1 {
			v.selected = nil
		} else {
			next := len(v.clauses) - 2
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
