package cli

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"strings"

	"go800mon/internal/memory"
)

func cmdBPList(socket string) int {
	list, err := rpcClient(socket).BPList(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("Enabled: %s\n", formatOnOffBadge(list.Enabled))
	if len(list.Clauses) == 0 {
		fmt.Println("No breakpoint clauses.")
		return 0
	}
	for i, clause := range list.Clauses {
		parts := make([]string, 0, len(clause))
		for _, cond := range clause {
			parts = append(parts, FormatBPCondition(cond))
		}
		fmt.Printf("#%02d %s\n", i+1, strings.Join(parts, " AND "))
	}
	return 0
}

func cmdBPAdd(socket string, args cliBPAddCmd) int {
	if len(args.Conditions) == 0 {
		return fail(errors.New("Specify at least one condition."))
	}
	clauses, err := ParseBPClauses(strings.Join(args.Conditions, " "))
	if err != nil {
		return fail(err)
	}
	added := make([]int, 0, len(clauses))
	for _, clause := range clauses {
		idx, addErr := rpcClient(socket).BPAddClause(context.Background(), clause)
		if addErr != nil {
			return fail(addErr)
		}
		added = append(added, int(idx)+1)
	}
	if len(added) == 0 {
		return 0
	}
	if len(added) == 1 {
		fmt.Printf("Added clause #%d\n", added[0])
		return 0
	}
	parts := make([]string, 0, len(added))
	for _, idx := range added {
		parts = append(parts, fmt.Sprintf("#%d", idx))
	}
	fmt.Printf("Added clauses: %s\n", strings.Join(parts, ", "))
	return 0
}

func cmdBPDelete(socket string, args cliBPDeleteCmd) int {
	if args.Index <= 0 {
		return fail(errors.New("Clause index must be >= 1."))
	}
	if err := rpcClient(socket).BPDeleteClause(context.Background(), uint16(args.Index-1)); err != nil {
		return fail(err)
	}
	return cmdBPList(socket)
}

func cmdBPClear(socket string) int {
	if err := rpcClient(socket).BPClear(context.Background()); err != nil {
		return fail(err)
	}
	return cmdBPList(socket)
}

func cmdBPSetEnabled(socket string, enabled bool) int {
	if _, err := rpcClient(socket).BPSetEnabled(context.Background(), enabled); err != nil {
		return fail(err)
	}
	return cmdBPList(socket)
}

func blineModeName(mode byte) string {
	switch mode {
	case 0:
		return "disabled"
	case 1:
		return "break"
	case 2:
		return "blink"
	default:
		return fmt.Sprintf("mode%d", mode)
	}
}

func cmdBLine(socket string, args cliBLineCmd) int {
	var payload []byte
	if args.Scanline != nil {
		scanline, err := memory.ParseHex(*args.Scanline)
		if err != nil {
			return fail(err)
		}
		payload = make([]byte, 2)
		binary.LittleEndian.PutUint16(payload, scanline)
	}
	data, err := rpcClient(socket).Call(context.Background(), CmdBLine, payload)
	if err != nil {
		return fail(err)
	}
	if len(data) < 3 {
		return fail(errors.New("BLINE payload too short"))
	}
	scanline := binary.LittleEndian.Uint16(data[0:2])
	mode := blineModeName(data[2])
	fmt.Printf("scanline=%d mode=%s\n", scanline, mode)
	return 0
}
