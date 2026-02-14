package monitor

import (
	"context"
	"fmt"

	. "go800mon/a800mon"
)

const (
	topbarTitle      = "Atari800 Monitor"
	topbarCopyright  = "(c) 2026 Marcin Nowak"
	topbarRightWidth = 43
)

type TopBar struct {
	BaseWindowComponent
	lastSnapshot string
}

type topbarSegment struct {
	text  string
	color Color
}

func NewTopBar(window *Window) *TopBar {
	return &TopBar{BaseWindowComponent: NewBaseWindowComponent(window)}
}

func (t *TopBar) Update(_ctx context.Context) (bool, error) {
	st := State()
	snap := fmt.Sprintf("%s|%t|%d|%d|%d|%t", st.LastRPCError, st.Crashed, st.EmuMS, st.ResetMS, st.MonitorFrameTimeMS, st.UIFrozen)
	if t.lastSnapshot == snap {
		return false, nil
	}
	t.lastSnapshot = snap
	return true, nil
}

func (t *TopBar) Render(_force bool) {
	st := State()
	w := t.Window()
	w.Cursor(0, 0)
	if st.LastRPCError != "" {
		w.Print(topbarTitle+" ", ColorTopbar.Attr(), false)
		w.Print(" "+st.LastRPCError+" ", ColorError.Attr(), false)
		w.FillToEOL(' ', ColorError.Attr())
	} else {
		w.Print(topbarTitle+"     "+topbarCopyright, ColorTopbar.Attr(), false)
		if st.UIFrozen {
			w.Print("   ", ColorTopbar.Attr(), false)
			w.Print(" FREEZE ", ColorError.Attr(), false)
		}
		w.FillToEOL(' ', ColorTopbar.Attr())
	}
	start := w.Width() - topbarRightWidth
	if start < 0 {
		start = 0
	}
	w.Cursor(start, 0)
	segments := []topbarSegment{
		{text: crashLabel(st.Crashed), color: crashColor(st.Crashed)},
		{text: " UP ", color: ColorText},
		{text: fmt.Sprintf(" %s ", FormatHMS(st.EmuMS)), color: ColorTopbar},
		{text: " RS ", color: ColorText},
		{text: fmt.Sprintf(" %s ", FormatHMS(st.ResetMS)), color: ColorTopbar},
		{text: fmt.Sprintf(" %3d ms ", st.MonitorFrameTimeMS), color: ColorText},
	}
	for _, segment := range segments {
		w.Print(segment.text, segment.color.Attr(), false)
	}
}

func crashLabel(crashed bool) string {
	if crashed {
		return " CRASH "
	}
	return "       "
}

func crashColor(crashed bool) Color {
	if crashed {
		return ColorError
	}
	return ColorTopbar
}
