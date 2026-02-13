package a800mon

import "context"

type CpuStateViewer struct {
	BaseWindowComponent
	lastSnapshot string
}

func NewCpuStateViewer(window *Window) *CpuStateViewer {
	v := &CpuStateViewer{BaseWindowComponent: NewBaseWindowComponent(window)}
	return v
}

func (v *CpuStateViewer) Update(_ctx context.Context) (bool, error) {
	st := State()
	snap := formatCPU(st.CPU) + "|" + st.CPUDisasm
	if v.lastSnapshot == snap {
		return false, nil
	}
	v.lastSnapshot = snap
	return true, nil
}

func (v *CpuStateViewer) Render(_force bool) {
	st := State()
	line := formatCPU(st.CPU)
	if st.CPUDisasm != "" {
		line += "  " + st.CPUDisasm
	}
	w := v.Window()
	w.Cursor(0, 0)
	w.Print(line, ColorText.Attr(), false)
	w.ClearToEOL(false)
}
