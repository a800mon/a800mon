package cli

import (
	"context"
	"fmt"
	"os"
	"strings"

	dl "go800mon/internal/displaylist"
	"go800mon/internal/memory"
)

func cmdDumpDList(socket string, args cliDListCmd) int {
	cl := rpcClient(socket)
	ctx := context.Background()
	var (
		start uint16
		err   error
		dump  []byte
	)
	if args.Address == nil {
		start, err = cl.ReadVector(ctx, DLPTRSAddr)
		if err != nil {
			return fail(err)
		}
		dump, err = cl.ReadDisplayList(ctx)
	} else {
		start, err = memory.ParseHex(*args.Address)
		if err != nil {
			return fail(err)
		}
		dump, err = cl.ReadDisplayListAt(ctx, start)
	}
	if err != nil {
		return fail(err)
	}
	dmactl, err := cl.ReadByte(ctx, DMACTLAddr)
	if err != nil {
		return fail(err)
	}
	if dmactl&0x03 == 0 {
		if hw, hwErr := cl.ReadByte(ctx, DMACTLHWAddr); hwErr == nil {
			dmactl = hw
		}
	}
	dlist := DecodeDisplayList(start, dump)
	for _, c := range dlist.Compacted() {
		if c.Count > 1 {
			fmt.Printf("%04X: %dx %s\n", c.Entry.Addr, c.Count, c.Entry.Description())
		} else {
			fmt.Printf("%04X: %s\n", c.Entry.Addr, c.Entry.Description())
		}
	}
	fmt.Println()
	fmt.Printf("Length: %04X\n", len(dump))
	segs := dlist.ScreenSegments(dmactl)
	if len(segs) > 0 {
		fmt.Println("Screen segments:")
		for i, seg := range segs {
			length := seg.End - seg.Start
			last := (seg.End - 1) & 0xFFFF
			fmt.Printf("#%d %04X-%04X len=%04X antic=%d\n", i+1, seg.Start, last, length, seg.Mode)
		}
	}
	return 0
}

func cmdGTIAState(socket string) int {
	state, err := rpcClient(socket).GTIAState(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("HPOSP:  %s\n", fmtBytes(state.HPOSP[:]))
	fmt.Printf("HPOSM:  %s\n", fmtBytes(state.HPOSM[:]))
	fmt.Printf("SIZEP:  %s\n", fmtBytes(state.SIZEP[:]))
	fmt.Printf("SIZEM:  %02X\n", state.SIZEM)
	fmt.Printf("GRAFP:  %s\n", fmtBytes(state.GRAFP[:]))
	fmt.Printf("GRAFM:  %02X\n", state.GRAFM)
	fmt.Printf("COLPM:  %s\n", fmtBytes(state.COLPM[:]))
	fmt.Printf("COLPF:  %s\n", fmtBytes(state.COLPF[:]))
	fmt.Printf("COLBK:  %02X\n", state.COLBK)
	fmt.Printf("PRIOR:  %02X\n", state.PRIOR)
	fmt.Printf("VDELAY: %02X\n", state.VDELAY)
	fmt.Printf("GRACTL: %02X\n", state.GRACTL)
	return 0
}

func cmdANTICState(socket string) int {
	state, err := rpcClient(socket).ANTICState(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("DMACTL: %02X\n", state.DMACTL)
	fmt.Printf("CHACTL: %02X\n", state.CHACTL)
	fmt.Printf("DLIST:  %04X\n", state.DLIST)
	fmt.Printf("HSCROL: %02X\n", state.HSCROL)
	fmt.Printf("VSCROL: %02X\n", state.VSCROL)
	fmt.Printf("PMBASE: %02X\n", state.PMBASE)
	fmt.Printf("CHBASE: %02X\n", state.CHBASE)
	fmt.Printf("VCOUNT: %02X\n", state.VCOUNT)
	fmt.Printf("NMIEN:  %02X\n", state.NMIEN)
	fmt.Printf("YPOS:   %d\n", state.YPOS)
	return 0
}

func cmdPIAState(socket string) int {
	state, err := rpcClient(socket).PIAState(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("PACTL: %02X\n", state.PACTL)
	fmt.Printf("PBCTL: %02X\n", state.PBCTL)
	fmt.Printf("PORTA: %02X\n", state.PORTA)
	fmt.Printf("PORTB: %02X\n", state.PORTB)
	return 0
}

func cmdPOKEYState(socket string) int {
	state, err := rpcClient(socket).POKEYState(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("stereo_enabled: %d\n", state.StereoEnabled)
	fmt.Printf("AUDF1:          %s\n", fmtBytes(state.AUDF1[:]))
	fmt.Printf("AUDC1:          %s\n", fmtBytes(state.AUDC1[:]))
	fmt.Printf("AUDCTL1:        %02X\n", state.AUDCTL1)
	fmt.Printf("KBCODE:         %02X\n", state.KBCODE)
	fmt.Printf("IRQEN:          %02X\n", state.IRQEN)
	fmt.Printf("IRQST:          %02X\n", state.IRQST)
	fmt.Printf("SKSTAT:         %02X\n", state.SKSTAT)
	fmt.Printf("SKCTL:          %02X\n", state.SKCTL)
	if state.HasChip2 {
		fmt.Printf("AUDF2:          %s\n", fmtBytes(state.AUDF2[:]))
		fmt.Printf("AUDC2:          %s\n", fmtBytes(state.AUDC2[:]))
		fmt.Printf("AUDCTL2:        %02X\n", state.AUDCTL2)
	}
	return 0
}

func fmtBytes(values []byte) string {
	if len(values) == 0 {
		return ""
	}
	parts := make([]string, 0, len(values))
	for _, v := range values {
		parts = append(parts, fmt.Sprintf("%02X", v))
	}
	return strings.Join(parts, " ")
}

func cmdScreen(socket string, args cliScreenCmd) int {
	if args.List && args.Segment != nil {
		fmt.Fprintln(os.Stderr, "--list cannot be used with a segment number")
		return 1
	}
	cl := rpcClient(socket)
	ctx := context.Background()
	start, err := cl.ReadVector(ctx, DLPTRSAddr)
	if err != nil {
		return fail(err)
	}
	dump, err := cl.ReadDisplayList(ctx)
	if err != nil {
		return fail(err)
	}
	dmactl, err := cl.ReadByte(ctx, DMACTLAddr)
	if err != nil {
		return fail(err)
	}
	if dmactl&0x03 == 0 {
		if hw, hwErr := cl.ReadByte(ctx, DMACTLHWAddr); hwErr == nil {
			dmactl = hw
		}
	}
	dlist := dl.Decode(start, dump)
	segments := dlist.ScreenSegments(dmactl)
	if len(segments) == 0 {
		fmt.Fprintln(os.Stderr, "No screen segments found.")
		return 1
	}
	if args.List {
		for i, seg := range segments {
			length := seg.End - seg.Start
			last := (seg.End - 1) & 0xFFFF
			fmt.Printf("#%d %04X-%04X len=%04X antic=%d\n", i+1, seg.Start, last, length, seg.Mode)
		}
		return 0
	}
	mapper := dl.NewMemoryMapper(dlist, dmactl, 4096)
	if args.Segment == nil {
		if args.Columns == nil && !args.Raw && !args.JSON {
			rows := make([]memory.DumpRow, 0)
			for _, row := range mapper.RowRanges() {
				if row.Addr == nil || row.Length <= 0 {
					continue
				}
				chunk, err := cl.ReadMemory(ctx, *row.Addr, uint16(row.Length))
				if err != nil {
					return fail(err)
				}
				if len(chunk) == 0 {
					continue
				}
				rowCopy := make([]byte, len(chunk))
				copy(rowCopy, chunk)
				rows = append(rows, memory.DumpRow{
					Address: *row.Addr,
					Data:    rowCopy,
				})
			}
			if len(rows) > 0 {
				fmt.Println(memory.DumpHumanRows(rows, args.ATASCII, !args.NoHex, !args.NoASCII))
				return 0
			}
		}
		data := make([]byte, 0)
		for _, seg := range segments {
			chunk, err := cl.ReadMemoryChunked(ctx, uint16(seg.Start&0xFFFF), seg.End-seg.Start)
			if err != nil {
				return fail(err)
			}
			data = append(data, chunk...)
		}
		cols := 0
		columnsProvided := args.Columns != nil
		if columnsProvided {
			cols = *args.Columns
		}
		return dumpMemory(
			uint16(segments[0].Start&0xFFFF),
			len(data),
			data,
			args.Raw,
			args.JSON,
			args.ATASCII,
			cols,
			columnsProvided,
			!args.NoHex,
			!args.NoASCII,
		)
	}
	idx := *args.Segment - 1
	if idx < 0 || idx >= len(segments) {
		fmt.Fprintf(os.Stderr, "Segment out of range (1-%d)\n", len(segments))
		return 1
	}
	seg := segments[idx]
	length := seg.End - seg.Start
	data, err := cl.ReadMemoryChunked(ctx, uint16(seg.Start&0xFFFF), length)
	if err != nil {
		return fail(err)
	}
	if args.Columns == nil && !args.Raw && !args.JSON {
		rows := make([]memory.DumpRow, 0)
		for _, row := range mapper.RowRanges() {
			if row.Addr == nil || row.Length <= 0 {
				continue
			}
			addr := int(*row.Addr)
			if addr < seg.Start || addr >= seg.End {
				continue
			}
			rel := addr - seg.Start
			if rel < 0 || rel >= len(data) {
				continue
			}
			rowEnd := rel + row.Length
			if rowEnd > len(data) {
				rowEnd = len(data)
			}
			chunk := data[rel:rowEnd]
			if len(chunk) == 0 {
				continue
			}
			rowCopy := make([]byte, len(chunk))
			copy(rowCopy, chunk)
			rows = append(rows, memory.DumpRow{
				Address: uint16(addr & 0xFFFF),
				Data:    rowCopy,
			})
		}
		if len(rows) > 0 {
			fmt.Println(memory.DumpHumanRows(rows, args.ATASCII, !args.NoHex, !args.NoASCII))
			return 0
		}
	}
	cols := 0
	columnsProvided := args.Columns != nil
	if columnsProvided {
		cols = *args.Columns
	}
	if cols == 0 {
		if c := mapper.BytesPerLine(seg.Mode); c > 0 {
			cols = c
		}
	}
	return dumpMemory(
		uint16(seg.Start&0xFFFF),
		length,
		data,
		args.Raw,
		args.JSON,
		args.ATASCII,
		cols,
		columnsProvided,
		!args.NoHex,
		!args.NoASCII,
	)
}

func dumpMemory(address uint16, length int, data []byte, raw bool, asJSON bool, useATASCII bool, columns int, columnsProvided bool, showHex bool, showASCII bool) int {
	if columnsProvided && (raw || asJSON) {
		fmt.Fprintln(os.Stderr, "--columns is only valid for formatted output")
		return 1
	}
	if raw {
		out := memory.DumpRaw(data, useATASCII)
		if len(out) > 0 {
			_, _ = os.Stdout.Write(out)
		}
		return 0
	}
	if asJSON {
		text, err := memory.DumpJSON(address, data, useATASCII)
		if err != nil {
			return fail(err)
		}
		fmt.Println(text)
		return 0
	}
	fmt.Println(memory.DumpHuman(address, length, data, useATASCII, columns, showHex, showASCII))
	return 0
}
