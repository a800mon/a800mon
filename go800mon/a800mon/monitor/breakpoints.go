package monitor

import (
	"context"
	"fmt"
	"strings"

	. "go800mon/a800mon"
)

type BreakpointsViewer struct {
	BaseWindowComponent
	rpc              *RpcClient
	grid             *GridWidget
	enabled          bool
	clauses          []BreakpointClauseRow
	lastSnapshot     string
	lastStateSeq     uint64
	hasSnapshot      bool
	pendingAdd       [][]BreakpointCondition
	hasPendingAdd    bool
	pendingDelete    *int
	pendingEnabled   *bool
	pendingClear     bool
	refreshRequested bool
	clearDialog      *DialogWidget
	inputWidget      *InputWidget
	inputActive      bool
}

func NewBreakpointsViewer(rpc *RpcClient, window *Window) *BreakpointsViewer {
	grid := NewGridWidget(window)
	grid.SetColumnGap(0)
	grid.AddColumn("index", 0, ColorAddress.Attr(), nil)
	grid.AddColumn("condition", 0, ColorText.Attr(), nil)
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

func (v *BreakpointsViewer) Update(ctx context.Context) (bool, error) {
	st := State()
	if !st.BreakpointsSupported {
		return false, nil
	}
	changed := false
	if v.pendingClear {
		v.pendingClear = false
		if err := v.rpc.BPClear(ctx); err == nil {
			v.grid.SetSelectedRow(nil)
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
	w := v.Window()
	g := v.grid
	ih := w.Height()
	if ih <= 0 {
		return
	}
	overlayRows := 0
	if v.inputActive || (v.clearDialog != nil && v.clearDialog.Active()) {
		overlayRows = 1
	}
	w.SetTagActive("bp_enabled", v.enabled)
	g.SetViewport(overlayRows, max(0, ih-overlayRows))
	rows := make([][]string, 0, len(v.clauses)+1)

	if len(v.clauses) == 0 {
		rows = append(rows, []string{"", "No breakpoint clauses."})
		g.SetSelectedRow(nil)
	} else {
		for i, clause := range v.clauses {
			rows = append(rows, []string{
				fmt.Sprintf("#%02d ", i+1),
				v.formatClauseText(clause),
			})
		}
	}
	g.SetData(rows)
	g.Render()

	if v.clearDialog != nil && v.clearDialog.Active() {
		v.clearDialog.Render()
	} else if v.inputActive {
		v.inputWidget.Render(false)
	}
}

func (v *BreakpointsViewer) HandleInput(ch int) bool {
	if v.clearDialog != nil && v.clearDialog.Active() {
		result := v.clearDialog.HandleInput(ch)
		if result == DialogInputConfirm {
			v.pendingClear = true
		}
		return !(result == DialogInputNone)
	}
	if ch == '/' {
		v.openInput("")
		return true
	}
	if v.grid.HandleInput(ch) {
		return true
	}
	if ch == KeyDelete() || ch == 330 {
		v.queueDeleteSelected()
		return true
	}
	if ch == 'c' || ch == 'C' {
		v.clearDialog.Activate("Clear all breakpoints?", "YES")
		return true
	}
	if ch == ' ' || ch == 'e' || ch == 'E' {
		enabled := !v.enabled
		v.pendingEnabled = &enabled
		return true
	}
	return false
}

func (v *BreakpointsViewer) formatClauseText(clause BreakpointClauseRow) string {
	parts := make([]string, 0, len(clause.Conditions))
	for i, cond := range clause.Conditions {
		_ = i
		parts = append(parts, v.formatConditionText(cond))
	}
	return strings.Join(parts, " AND ")
}

func (v *BreakpointsViewer) formatConditionText(cond BreakpointConditionRow) string {
	op := BPOpSymbol(cond.Op)
	if cond.CondType == 9 {
		if cond.CondType == 2 || cond.CondType == 3 || cond.CondType == 4 || cond.CondType == 5 {
			return fmt.Sprintf("mem[%s] %s %02X", formatHex16(cond.Addr), op, cond.Value)
		}
		return fmt.Sprintf("mem[%s] %s %s", formatHex16(cond.Addr), op, formatHex16(cond.Value))
	}
	left := BPTypeName(cond.CondType)
	if cond.CondType == 2 || cond.CondType == 3 || cond.CondType == 4 || cond.CondType == 5 {
		return fmt.Sprintf("%s %s %02X", left, op, cond.Value)
	}
	return fmt.Sprintf("%s %s %s", left, op, formatHex16(cond.Value))
}

func (v *BreakpointsViewer) queueDeleteSelected() {
	idx, ok := v.grid.SelectedRow()
	if !ok {
		return
	}
	v.pendingDelete = &idx
	if idx >= len(v.clauses)-1 {
		if len(v.clauses) <= 1 {
			v.grid.SetSelectedRow(nil)
		} else {
			next := len(v.clauses) - 2
			v.grid.SetSelectedRow(&next)
		}
	}
}

func (v *BreakpointsViewer) openInput(initial string) {
	v.inputActive = true
	v.inputWidget.Activate(initial)
	v.inputWidget.SetInvalid(false)
	if app := v.App(); app != nil {
		app.DispatchAction(ActionSetInputFocus, v.handleTextInput)
	}
}

func (v *BreakpointsViewer) closeInput() {
	v.inputActive = false
	v.inputWidget.SetInvalid(false)
	v.inputWidget.Deactivate()
	if app := v.App(); app != nil {
		app.DispatchAction(ActionSetInputFocus, nil)
	}
}

func (v *BreakpointsViewer) onInputChange(text string) {
	trimmed := strings.TrimSpace(text)
	if trimmed == "" {
		v.inputWidget.SetInvalid(false)
		return
	}
	if _, err := ParseBPClauses(trimmed); err != nil {
		v.inputWidget.SetInvalid(true)
		return
	}
	v.inputWidget.SetInvalid(false)
}

func (v *BreakpointsViewer) handleTextInput(ch int) bool {
	if ch == 27 {
		v.closeInput()
		return true
	}
	if ch == 10 || ch == 13 || ch == KeyEnter() {
		if v.inputWidget.Invalid() {
			return true
		}
		trimmed := strings.TrimSpace(v.inputWidget.Buffer())
		if trimmed != "" {
			clauses, err := ParseBPClauses(trimmed)
			if err != nil {
				v.inputWidget.SetInvalid(true)
				return true
			}
			v.pendingAdd = append([][]BreakpointCondition(nil), clauses...)
			v.hasPendingAdd = true
		}
		v.closeInput()
		return true
	}
	if v.inputWidget.HandleKey(ch) {
		return true
	}
	return true
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
