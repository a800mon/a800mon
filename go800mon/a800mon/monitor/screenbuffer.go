package monitor

import (
	"context"
	"encoding/binary"
	"fmt"
	"hash/fnv"
	"strings"
	"time"

	. "go800mon/a800mon"
	"go800mon/internal/atascii"
	dl "go800mon/internal/displaylist"
)

type ScreenBufferInspector struct {
	BaseWindowComponent
	rpc            *RpcClient
	grid           *GridWidget
	rows           []ScreenRow
	hasUseATASCII  bool
	lastUseATASCII bool
	lastSnapshot   string
	rpcThrottle    time.Duration
	nextRPCAt      time.Time
}

type rowRangeIndex struct {
	s   int
	e   int
	off int
}

func NewScreenBufferInspector(rpc *RpcClient, window *Window) *ScreenBufferInspector {
	grid := NewGridWidget(window)
	grid.SetColumnGap(0)
	grid.SetSelectionEnabled(false)
	grid.AddColumn("address", 0, ColorAddress.Attr(), nil)
	grid.AddColumn("content", 0, ColorText.Attr(), nil)
	return &ScreenBufferInspector{
		BaseWindowComponent: NewBaseWindowComponent(window),
		rpc:                 rpc,
		grid:                grid,
		rpcThrottle:         100 * time.Millisecond,
	}
}

func (s *ScreenBufferInspector) HandleInput(ch int) bool {
	if !(ch == int(' ') || ch == int('a') || ch == int('A')) {
		return s.grid.HandleInput(ch)
	}
	st := State()
	enabled := !st.UseATASCII
	if app := s.App(); app != nil {
		app.DispatchAction(ActionSetATASCII, enabled)
	}
	s.hasUseATASCII = true
	s.lastUseATASCII = enabled
	w := s.Window()
	w.SetTagActive("atascii", enabled)
	w.SetTagActive("ascii", !enabled)
	return true
}

func (s *ScreenBufferInspector) Update(ctx context.Context) (bool, error) {
	st := State()
	changed := false
	if !s.hasUseATASCII || s.lastUseATASCII != st.UseATASCII {
		s.hasUseATASCII = true
		s.lastUseATASCII = st.UseATASCII
		w := s.Window()
		w.SetTagActive("atascii", st.UseATASCII)
		w.SetTagActive("ascii", !st.UseATASCII)
		changed = true
	}
	now := time.Now()
	if now.Before(s.nextRPCAt) {
		return changed, nil
	}
	s.nextRPCAt = now.Add(s.rpcThrottle)
	mapper := dl.NewMemoryMapper(st.DList, st.DMACTL, 0x400)
	fetchRanges, rowSlices := mapper.Plan()
	if len(fetchRanges) == 0 {
		s.rows = nil
		if s.lastSnapshot == "" {
			return changed, nil
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
			return changed, nil
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
	s.rows = rows
	snapshot := buildScreenRowsSnapshot(rows)
	if s.lastSnapshot == snapshot {
		return changed, nil
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
	contentWidth := w.Width() - 8
	if contentWidth < 0 {
		contentWidth = 0
	}
	rows := make([]ScreenRow, 0, w.Height())
	drawWidth := 0
	for _, row := range s.rows {
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
	gridRows := make([][]string, 0, len(rows))
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
		content := ""
		if leftPad > 0 {
			content += strings.Repeat("·", leftPad)
		}
		content += renderScreenText(row.Data[:rowLen], st.UseATASCII)
		if rightPad > 0 {
			content += strings.Repeat("·", rightPad)
		}
		gridRows = append(gridRows, []string{formatHex16(row.Addr) + ": ", content})
	}
	s.grid.SetData(gridRows)
	s.grid.SetSelectedRow(nil)
	s.grid.Render()
}

func renderScreenText(data []byte, useATASCII bool) string {
	if len(data) == 0 {
		return ""
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
		return string(out)
	}
	out := make([]rune, 0, len(data))
	for _, b := range data {
		ch, _ := renderScreenCharATASCII(b)
		out = append(out, ch)
	}
	return string(out)
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
