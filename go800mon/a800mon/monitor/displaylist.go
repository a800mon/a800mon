package monitor

import (
	"context"
	"fmt"

	. "go800mon/a800mon"
	atari "go800mon/a800mon/atari"
)

type DisplayListViewer struct {
	BaseWindowComponent
	rpc          *RpcClient
	lastSnapshot string
	grid         *GridWidget
}

func NewDisplayListViewer(rpc *RpcClient, window *Window) *DisplayListViewer {
	grid := NewGridWidget(window)
	grid.AddColumn("address", 5, ColorAddress.Attr(), nil)
	grid.AddColumn("description", 0, ColorText.Attr(), nil)
	return &DisplayListViewer{
		BaseWindowComponent: NewBaseWindowComponent(grid.Window()),
		rpc:                 rpc,
		grid:                grid,
	}
}

func (v *DisplayListViewer) Update(ctx context.Context) (bool, error) {
	startAddr, err := v.rpc.ReadVector(ctx, atari.DLPTRSAddr)
	if err != nil {
		return false, nil
	}
	dump, err := v.rpc.ReadDisplayList(ctx)
	if err != nil {
		return false, nil
	}
	dmactl, err := v.rpc.ReadByte(ctx, atari.DMACTLAddr)
	if err != nil {
		return false, nil
	}
	if (dmactl & 0x03) == 0 {
		if hw, err := v.rpc.ReadByte(ctx, atari.DMACTLHWAddr); err == nil {
			dmactl = hw
		}
	}
	dlist := atari.DecodeDisplayList(startAddr, dump)
	if app := v.App(); app != nil {
		app.DispatchAction(
			ActionSetDList,
			DListUpdate{DList: dlist, DMACTL: dmactl},
		)
	}
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
	rows := make([][]string, 0, len(st.DList.Entries))
	for _, c := range st.DList.Compacted() {
		addr := fmt.Sprintf("%04X:", c.Entry.Addr)
		desc := c.Entry.Description()
		if c.Count > 1 {
			desc = fmt.Sprintf("%dx %s", c.Count, c.Entry.Description())
		}
		rows = append(rows, []string{addr, desc})
	}
	g.SetData(rows)
	if len(rows) > 0 {
		if _, ok := g.SelectedRow(); !ok {
			idx := 0
			g.SetSelectedRow(&idx)
		}
	} else {
		g.SetSelectedRow(nil)
	}
	g.Render()
}

func (v *DisplayListViewer) HandleInput(ch int) bool {
	return v.grid.HandleInput(ch)
}
