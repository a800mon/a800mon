package a800mon

import (
	"context"
	"encoding/binary"
	"fmt"
	"hash/fnv"
	"strings"

	"go800mon/internal/atascii"
	dl "go800mon/internal/displaylist"
)

type ScreenBufferInspector struct {
	BaseWindowComponent
	rpc            *RpcClient
	grid           *GridWidget
	screen         *Screen
	lastUseATASCII bool
	lastSnapshot   string
}

type rowRangeIndex struct {
	s   int
	e   int
	off int
}

func NewScreenBufferInspector(rpc *RpcClient, window *Window) *ScreenBufferInspector {
	grid := NewGridWidget(window)
	grid.SetGridColumnGap(0)
	grid.SetGridSelectionEnabled(false)
	return &ScreenBufferInspector{
		BaseWindowComponent: NewBaseWindowComponent(window),
		rpc:                 rpc,
		grid:                grid,
	}
}

func (s *ScreenBufferInspector) BindInput(screen *Screen) {
	s.screen = screen
}

func (s *ScreenBufferInspector) HandleInput(ch int) bool {
	if State().InputFocus {
		return false
	}
	if s.screen == nil || !(s.screen.Focused() == s.Window()) {
		return false
	}
	if !(ch == int(' ') || ch == int('a') || ch == int('A')) {
		return s.grid.HandleGridNavigationInput(ch)
	}
	store.setUseATASCII(!State().UseATASCII)
	return true
}

func (s *ScreenBufferInspector) Update(ctx context.Context) (bool, error) {
	if State().InputFocus {
		return false, nil
	}
	st := State()
	mapper := dl.NewMemoryMapper(st.DList, st.DMACTL, 0x400)
	fetchRanges, rowSlices := mapper.Plan()
	segs := st.DList.ScreenSegments(st.DMACTL)
	if st.DListSelectedRegion != nil && *st.DListSelectedRegion >= 0 && *st.DListSelectedRegion < len(segs) {
		seg := segs[*st.DListSelectedRegion]
		fetchRanges = []dl.FetchRange{{Start: seg.Start, End: seg.End}}
		filtered := make([]dl.RowSlice, 0, len(rowSlices))
		for _, r := range rowSlices {
			addr := int(r.Addr)
			if seg.Start <= addr && addr < seg.End {
				filtered = append(filtered, r)
			}
		}
		rowSlices = filtered
	}
	if len(fetchRanges) == 0 {
		store.setScreenRows(nil)
		if s.lastSnapshot == "" {
			return false, nil
		}
		s.lastSnapshot = ""
		return true, nil
	}
	buffer := make([]byte, 0, 8192)
	index := make([]rowRangeIndex, 0, len(fetchRanges))
	off := 0
	for _, r := range fetchRanges {
		ln := r.End - r.Start
		if ln <= 0 {
			continue
		}
		chunk, err := s.rpc.ReadMemoryChunked(ctx, uint16(r.Start&0xFFFF), ln)
		if err != nil {
			return false, nil
		}
		buffer = append(buffer, chunk...)
		index = append(index, rowRangeIndex{s: r.Start, e: r.End, off: off})
		off += len(chunk)
	}
	rows := make([]ScreenRow, 0, len(rowSlices))
	for _, rs := range rowSlices {
		row := readRow(buffer, index, int(rs.Addr), rs.Length)
		if len(row) == 0 {
			continue
		}
		rows = append(rows, ScreenRow{Addr: rs.Addr, Data: row})
	}
	store.setScreenRows(rows)
	snapshot := buildScreenRowsSnapshot(rows)
	if s.lastSnapshot == snapshot {
		return false, nil
	}
	s.lastSnapshot = snapshot
	return true, nil
}

func readRow(buffer []byte, index []rowRangeIndex, addr, ln int) []byte {
	if ln <= 0 {
		return nil
	}
	out := make([]byte, 0, ln)
	cur := addr
	remaining := ln
	for remaining > 0 {
		found := false
		for _, it := range index {
			if it.s <= cur && cur < it.e {
				take := it.e - cur
				if take > remaining {
					take = remaining
				}
				from := it.off + (cur - it.s)
				to := from + take
				if from < 0 || to > len(buffer) || from >= to {
					return nil
				}
				out = append(out, buffer[from:to]...)
				cur += take
				remaining -= take
				found = true
				break
			}
		}
		if !found {
			return nil
		}
	}
	return out
}

func (s *ScreenBufferInspector) Render(_force bool) {
	st := State()
	w := s.Window()
	if s.lastUseATASCII != st.UseATASCII {
		s.lastUseATASCII = st.UseATASCII
		w.SetTagActive("atascii", st.UseATASCII)
		w.SetTagActive("ascii", !st.UseATASCII)
	}
	contentWidth := w.Width() - 8
	if contentWidth < 0 {
		contentWidth = 0
	}
	rows := make([]ScreenRow, 0, w.Height())
	drawWidth := 0
	for _, row := range st.ScreenRows {
		if len(row.Data) > contentWidth {
			row.Data = row.Data[:contentWidth]
		}
		if len(row.Data) > drawWidth {
			drawWidth = len(row.Data)
		}
		rows = append(rows, row)
	}
	if drawWidth > contentWidth {
		drawWidth = contentWidth
	}
	gridRows := make([]GridRow, 0, len(rows))
	for _, row := range rows {
		rowLen := len(row.Data)
		if rowLen > drawWidth {
			rowLen = drawWidth
		}
		leftPad := 0
		rightPad := 0
		if drawWidth > rowLen {
			leftPad = (drawWidth - rowLen) / 2
			rightPad = drawWidth - rowLen - leftPad
		}
		cells := GridRow{{Text: formatHex16(row.Addr) + ": ", Attr: ColorAddress.Attr()}}
		if leftPad > 0 {
			cells = append(cells, GridCell{Text: strings.Repeat("·", leftPad), Attr: ColorUnused.Attr()})
		}
		cells = append(cells, renderScreenRuns(row.Data[:rowLen], st.UseATASCII)...)
		if rightPad > 0 {
			cells = append(cells, GridCell{Text: strings.Repeat("·", rightPad), Attr: ColorUnused.Attr()})
		}
		gridRows = append(gridRows, cells)
	}
	s.grid.SetGridColumnWidths(nil)
	s.grid.SetGridRows(gridRows)
	s.grid.SetGridSelected(nil)
	s.grid.RenderGrid()
}

func renderScreenRuns(data []byte, useATASCII bool) []GridCell {
	if len(data) == 0 {
		return nil
	}
	if !useATASCII {
		out := make([]rune, 0, len(data))
		for _, b := range data {
			if b <= 0 {
				out = append(out, ' ')
				continue
			}
			v := b & 0x7F
			if v >= 32 && v <= 126 {
				out = append(out, rune(v))
			} else {
				out = append(out, '.')
			}
		}
		return []GridCell{{Text: string(out), Attr: ColorText.Attr()}}
	}
	runs := make([]GridCell, 0, len(data))
	buf := make([]rune, 0, len(data))
	curAttr := -1
	flush := func() {
		if len(buf) == 0 || curAttr < 0 {
			return
		}
		runs = append(runs, GridCell{Text: string(buf), Attr: ColorText.Attr() | curAttr})
		buf = buf[:0]
	}
	for _, b := range data {
		ch, attr := renderScreenCharATASCII(b)
		if curAttr < 0 {
			curAttr = attr
		}
		if attr != curAttr {
			flush()
			curAttr = attr
		}
		buf = append(buf, ch)
	}
	flush()
	return runs
}

func renderScreenCharATASCII(b byte) (rune, int) {
	if b <= 0 {
		return ' ', 0
	}
	a := atascii.ScreenToATASCII(b)
	r := []rune(atascii.LookupPrintable(a & 0x7F))
	ch := '.'
	if len(r) > 0 {
		ch = r[0]
	}
	attr := 0
	if (a & 0x80) != 0 {
		attr = AttrReverse()
	}
	return ch, attr
}

func buildScreenRowsSnapshot(rows []ScreenRow) string {
	h := fnv.New64a()
	var n [2]byte
	binary.LittleEndian.PutUint16(n[:], uint16(len(rows)))
	_, _ = h.Write(n[:])
	for _, r := range rows {
		binary.LittleEndian.PutUint16(n[:], r.Addr)
		_, _ = h.Write(n[:])
		binary.LittleEndian.PutUint16(n[:], uint16(len(r.Data)))
		_, _ = h.Write(n[:])
		if len(r.Data) > 0 {
			_, _ = h.Write(r.Data)
		}
	}
	return fmt.Sprintf("%016X", h.Sum64())
}

func formatHex16(v uint16) string {
	const hex = "0123456789ABCDEF"
	b := [4]byte{hex[(v>>12)&0xF], hex[(v>>8)&0xF], hex[(v>>4)&0xF], hex[v&0xF]}
	return string(b[:])
}
