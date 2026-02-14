package cli

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"

	"go800mon/internal/disasm"
	"go800mon/internal/memory"
)

func cmdSearch(socket string, args cliSearchCmd) int {
	start, err := memory.ParseHex(args.Start)
	if err != nil {
		return fail(err)
	}
	end, err := memory.ParseHex(args.End)
	if err != nil {
		return fail(err)
	}
	raw := strings.Join(args.Pattern, " ")
	var pattern []byte
	if args.ATASCII || args.SearchScreen {
		pattern, err = EncodeATASCIIText(raw)
		if err != nil {
			return fail(err)
		}
		if args.SearchScreen {
			for i, b := range pattern {
				pattern[i] = ATASCIIToScreen(b)
			}
		}
	} else {
		pattern, err = memory.ParseHexPayload(raw)
		if err != nil {
			return fail(err)
		}
	}
	if len(pattern) == 0 || len(pattern) > 0xFF {
		return fail(errors.New("Pattern length must be in range 1..255."))
	}
	payload := make([]byte, 6+len(pattern))
	payload[0] = searchModeBytes
	binary.LittleEndian.PutUint16(payload[1:3], start)
	binary.LittleEndian.PutUint16(payload[3:5], end)
	payload[5] = byte(len(pattern))
	copy(payload[6:], pattern)
	data, err := rpcClient(socket).Call(context.Background(), CmdSearch, payload)
	if err != nil {
		return fail(err)
	}
	if len(data) < 6 {
		return fail(errors.New("SEARCH payload too short"))
	}
	total := binary.LittleEndian.Uint32(data[0:4])
	returned := int(binary.LittleEndian.Uint16(data[4:6]))
	expected := 6 + returned*2
	if len(data) < expected {
		return fail(fmt.Errorf("SEARCH payload too short: got=%d expected=%d", len(data), expected))
	}
	fmt.Printf("matches=%d returned=%d\n", total, returned)
	offset := 6
	for i := 0; i < returned; i++ {
		fmt.Printf("%04X\n", binary.LittleEndian.Uint16(data[offset:offset+2]))
		offset += 2
	}
	return 0
}

func cmdReadMem(socket string, args cliReadMemCmd) int {
	addr, err := memory.ParseHex(args.Addr)
	if err != nil {
		return fail(err)
	}
	length, err := memory.ParseHex(args.Length)
	if err != nil {
		return fail(err)
	}
	data, err := rpcClient(socket).ReadMemoryChunked(context.Background(), addr, int(length))
	if err != nil {
		return fail(err)
	}
	cols := 0
	columnsProvided := args.Columns != nil
	if columnsProvided {
		cols = *args.Columns
	}
	return dumpMemory(
		addr,
		int(length),
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

func cmdWriteMem(socket string, args cliWriteMemCmd) int {
	addr, err := memory.ParseHex(args.Addr)
	if err != nil {
		return fail(err)
	}
	hasBytes := len(args.Bytes) > 0
	hasHex := args.Hex != nil
	hasText := args.Text != nil
	if btoi(hasBytes)+btoi(hasHex)+btoi(hasText) != 1 {
		return fail(errors.New("Specify exactly one payload: <bytes...>, --hex, or --text."))
	}
	if args.ATASCII && !hasText {
		return fail(errors.New("--atascii is only valid with --text."))
	}
	data, err := resolveWriteMemData(args, hasBytes, hasHex)
	if err != nil {
		return fail(err)
	}
	if len(data) == 0 {
		return fail(errors.New("No data to write."))
	}
	if len(data) > 0xFFFF {
		return fail(fmt.Errorf("Data too long: %d bytes (max 65535).", len(data)))
	}
	if args.Screen {
		data = toScreenCodes(data)
	}
	if err := rpcClient(socket).WriteMemory(context.Background(), addr, data); err != nil {
		return fail(err)
	}
	return 0
}

func resolveWriteMemData(args cliWriteMemCmd, hasBytes bool, hasHex bool) ([]byte, error) {
	if hasBytes {
		return memory.ParseHexValues(args.Bytes)
	}
	if hasHex {
		text := strings.TrimSpace(*args.Hex)
		if text == "-" {
			raw, err := io.ReadAll(os.Stdin)
			if err != nil {
				return nil, err
			}
			text = string(raw)
		}
		return memory.ParseHexPayload(text)
	}
	text := *args.Text
	if text == "-" {
		raw, err := io.ReadAll(os.Stdin)
		if err != nil {
			return nil, err
		}
		text = string(raw)
	}
	if args.ATASCII {
		return EncodeATASCIIText(text)
	}
	return []byte(text), nil
}

func toScreenCodes(data []byte) []byte {
	out := make([]byte, len(data))
	for i, b := range data {
		out[i] = ATASCIIToScreen(b)
	}
	return out
}

func cmdDisasm(socket string, args cliDisasmCmd) int {
	addr, err := memory.ParseHex(args.Addr)
	if err != nil {
		return fail(err)
	}
	length, err := memory.ParseHex(args.Length)
	if err != nil {
		return fail(err)
	}
	data, err := rpcClient(socket).ReadMemoryChunked(context.Background(), addr, int(length))
	if err != nil {
		return fail(err)
	}
	for _, line := range disasm.Disasm(addr, data) {
		fmt.Println(line)
	}
	return 0
}

func btoi(v bool) int {
	if v {
		return 1
	}
	return 0
}
