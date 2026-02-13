package a800mon

import (
	"context"
	"fmt"

	dl "go800mon/internal/displaylist"
)

const (
	DMACTLAddr   = dl.DMACTLAddr
	DMACTLHWAddr = dl.DMACTLHWAddr
	DLPTRSAddr   = dl.DLPTRSAddr
)

func DecodeDisplayList(startAddr uint16, data []byte) dl.DisplayList {
	return dl.Decode(startAddr, data)
}

type DisplayListViewer struct {
	BaseWindowComponent
	rpc          *RpcClient
	lastSnapshot string
	grid         *GridWidget
}

func NewDisplayListViewer(rpc *RpcClient, window *Window) *DisplayListViewer {
	grid := NewGridWidget(window)
	return &DisplayListViewer{
		BaseWindowComponent: NewBaseWindowComponent(grid.Window()),
		rpc:                 rpc,
		grid:                grid,
	}
}

func (v *DisplayListViewer) Update(ctx context.Context) (bool, error) {
	if State().InputFocus {
		return false, nil
	}
	startAddr, err := v.rpc.ReadVector(ctx, DLPTRSAddr)
	if err != nil {
		return false, nil
	}
	dump, err := v.rpc.ReadDisplayList(ctx)
	if err != nil {
		return false, nil
	}
	dmactl, err := v.rpc.ReadByte(ctx, DMACTLAddr)
	if err != nil {
		return false, nil
	}
	if (dmactl & 0x03) == 0 {
		if hw, err := v.rpc.ReadByte(ctx, DMACTLHWAddr); err == nil {
			dmactl = hw
		}
	}
	dlist := DecodeDisplayList(startAddr, dump)
	store.setDList(dlist, dmactl)
	snapshot := fmt.Sprintf("%04X|%02X|%d", startAddr, dmactl, len(dlist.Entries))
	if len(dlist.Entries) > 0 {
		first := dlist.Entries[0]
		last := dlist.Entries[len(dlist.Entries)-1]
		snapshot += fmt.Sprintf("|%02X-%04X|%02X-%04X", first.Command, first.Arg, last.Command, last.Arg)
	}
	if v.lastSnapshot == snapshot {
		return false, nil
	}
	v.lastSnapshot = snapshot
	return true, nil
}

func (v *DisplayListViewer) Render(_force bool) {
	st := State()
	g := v.grid
	rows := make([]GridRow, 0, len(st.DList.Entries))
	for _, c := range st.DList.Compacted() {
		addr := fmt.Sprintf("%04X:", c.Entry.Addr)
		desc := c.Entry.Description()
		if c.Count > 1 {
			desc = fmt.Sprintf("%dx %s", c.Count, c.Entry.Description())
		}
		rows = append(rows, GridRow{
			{Text: addr, Attr: ColorAddress.Attr()},
			{Text: desc, Attr: ColorText.Attr()},
		})
	}
	g.SetGridColumnWidths([]int{5, 0})
	g.SetGridRows(rows)
	if len(rows) > 0 {
		if _, ok := g.GridSelected(); !ok {
			idx := 0
			g.SetGridSelected(&idx)
		}
	} else {
		g.SetGridSelected(nil)
	}
	g.RenderGrid()
}

func (v *DisplayListViewer) HandleInput(ch int) bool {
	if State().InputFocus {
		return false
	}
	w := v.Window()
	if w.screen == nil || w.screen.Focused() != w {
		return false
	}
	return v.grid.HandleGridNavigationInput(ch)
}
