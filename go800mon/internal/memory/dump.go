package memory

import (
	"encoding/json"
	"fmt"
	"strings"

	"go800mon/internal/atascii"
)

type DumpRow struct {
	Address uint16
	Data    []byte
}

func DumpRaw(buffer []byte, useATASCII bool) []byte {
	if !useATASCII {
		out := make([]byte, len(buffer))
		copy(out, buffer)
		return out
	}
	out := make([]byte, len(buffer))
	for i, b := range buffer {
		out[i] = atascii.ScreenToATASCII(b)
	}
	return out
}

func DumpJSON(address uint16, buffer []byte, useATASCII bool) (string, error) {
	data := DumpRaw(buffer, useATASCII)
	type payload struct {
		Address uint16 `json:"address"`
		Buffer  []byte `json:"buffer"`
	}
	pl := payload{Address: address, Buffer: data}
	encoded, err := json.Marshal(pl)
	if err != nil {
		return "", err
	}
	return string(encoded), nil
}

func DumpHuman(address uint16, length int, buffer []byte, useATASCII bool, columns int, showHex bool, showASCII bool) string {
	if columns <= 0 {
		columns = 16
	}
	if length < 0 {
		length = 0
	}
	lines := make([]string, 0, (length/columns)+1)
	for offset := 0; offset < length; offset += columns {
		addr := uint16((int(address) + offset) & 0xFFFF)
		end := offset + columns
		if end > len(buffer) {
			end = len(buffer)
		}
		chunk := buffer[offset:end]
		parts := []string{fmt.Sprintf("%04X:", addr)}
		if showHex {
			hex := make([]string, len(chunk))
			for i, b := range chunk {
				hex[i] = fmt.Sprintf("%02X", b)
			}
			hexWidth := columns*3 - 1
			hexText := strings.Join(hex, " ")
			if len(hexText) < hexWidth {
				hexText += strings.Repeat(" ", hexWidth-len(hexText))
			}
			parts = append(parts, hexText)
		}
		if showASCII {
			parts = append(parts, formatASCIIChunk(chunk, useATASCII))
		}
		lines = append(lines, strings.Join(parts, "  "))
	}
	return strings.Join(lines, "\n")
}

func DumpHumanRows(rows []DumpRow, useATASCII bool, showHex bool, showASCII bool) string {
	if len(rows) == 0 {
		return ""
	}
	drawWidth := 0
	for _, row := range rows {
		if len(row.Data) > drawWidth {
			drawWidth = len(row.Data)
		}
	}
	lines := make([]string, 0, len(rows))
	for _, row := range rows {
		chunk := row.Data
		parts := []string{fmt.Sprintf("%04X:", row.Address)}
		if showHex {
			tokens := make([]string, drawWidth)
			for i := 0; i < drawWidth; i++ {
				if i < len(chunk) {
					tokens[i] = fmt.Sprintf("%02X", chunk[i])
					continue
				}
				tokens[i] = ".."
			}
			parts = append(parts, strings.Join(tokens, " "))
		}
		if showASCII {
			ascii := formatASCIIChunk(chunk, useATASCII)
			if len(chunk) < drawWidth {
				pad := drawWidth - len(chunk)
				left := pad / 2
				right := pad - left
				ascii = strings.Repeat("·", left) + ascii + strings.Repeat("·", right)
			}
			parts = append(parts, ascii)
		}
		lines = append(lines, strings.Join(parts, "  "))
	}
	return strings.Join(lines, "\n")
}

func formatASCIIChunk(chunk []byte, useATASCII bool) string {
	var ascii strings.Builder
	ascii.Grow(len(chunk))
	for _, b := range chunk {
		if useATASCII {
			ascii.WriteString(atascii.LookupPrintable(atascii.ScreenToATASCII(b) & 0x7F))
			continue
		}
		if b >= 32 && b <= 126 {
			ascii.WriteByte(b)
		} else {
			ascii.WriteByte('.')
		}
	}
	return ascii.String()
}
