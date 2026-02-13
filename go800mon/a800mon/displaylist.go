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
	BaseVisualComponent
	rpc          *RpcClient
	lastSnapshot string
	grid         *GridWindow
}

func NewDisplayListViewer(rpc *RpcClient, window *GridWindow) *DisplayListViewer {
	return &DisplayListViewer{
		BaseVisualComponent: NewBaseVisualComponent(window.Window),
		rpc:                 rpc,
		grid:                window,
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
	st := State()
	if st.DisplayListInspect {
		segs := dlist.ScreenSegments(dmactl)
		if len(segs) == 0 {
			store.setDListSelectedRegion(nil)
		} else if st.DListSelectedRegion == nil {
			idx := 0
			store.setDListSelectedRegion(&idx)
		} else if *st.DListSelectedRegion >= len(segs) {
			idx := len(segs) - 1
			store.setDListSelectedRegion(&idx)
		}
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
	if st.DisplayListInspect {
		segs := st.DList.ScreenSegments(st.DMACTL)
		rows := make([]GridRow, 0, len(segs))
		for _, seg := range segs {
			length := seg.End - seg.Start
			last := (seg.End - 1) & 0xFFFF
			rows = append(rows, GridRow{
				{Text: fmt.Sprintf("%04X-%04X", seg.Start&0xFFFF, last), Attr: ColorAddress.Attr()},
				{Text: fmt.Sprintf("len=%04X antic=%d", length, seg.Mode), Attr: ColorText.Attr()},
			})
		}
		g.SetGridColumnWidths([]int{9, 0})
		g.SetGridRows(rows)
		if st.DListSelectedRegion == nil || *st.DListSelectedRegion < 0 || *st.DListSelectedRegion >= len(rows) {
			g.SetGridSelected(nil)
		} else {
			g.SetGridSelected(st.DListSelectedRegion)
		}
		g.RenderGrid()
		return
	}
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
	st := State()
	if st.DisplayListInspect {
		segs := st.DList.ScreenSegments(st.DMACTL)
		if len(segs) == 0 {
			return true
		}
		cur := 0
		if st.DListSelectedRegion != nil {
			cur = *st.DListSelectedRegion
		}
		page := max(1, w.Height())
		switch ch {
		case KeyUp():
			cur = max(0, cur-1)
		case KeyDown():
			cur = min(len(segs)-1, cur+1)
		case KeyPageUp(), 339:
			cur = max(0, cur-page)
		case KeyPageDown(), 338:
			cur = min(len(segs)-1, cur+page)
		case KeyHome(), 262:
			cur = 0
		case KeyEnd(), 360:
			cur = len(segs) - 1
		default:
			return false
		}
		store.setDListSelectedRegion(&cur)
		return true
	}
	return v.grid.HandleGridNavigationInput(ch)
}
