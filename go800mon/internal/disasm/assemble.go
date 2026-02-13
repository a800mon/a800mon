package disasm

import (
	"fmt"
	"strconv"
	"strings"
	"unicode"
)

var asmOpcodesByMnemonic = buildAsmOpcodesByMnemonic()

func AssembleOne(addr uint16, statement string) ([]byte, error) {
	text := strings.TrimSpace(strings.SplitN(statement, ";", 2)[0])
	if text == "" {
		return nil, fmt.Errorf("empty instruction")
	}
	mnemonic, operand := splitAsmStatement(strings.ToUpper(text))
	if mnemonic == "" {
		return nil, fmt.Errorf("missing mnemonic")
	}
	if isDataMnemonic(mnemonic) {
		return assembleDataBytes(operand)
	}
	modes, ok := asmOpcodesByMnemonic[mnemonic]
	if !ok {
		return nil, fmt.Errorf("unknown mnemonic: %s", mnemonic)
	}
	mode, value, err := parseAsmOperand(operand)
	if err != nil {
		return nil, err
	}
	resolvedMode, opcode, err := resolveAsmOpcode(modes, mode, value)
	if err != nil {
		return nil, err
	}
	return encodeAsmInstruction(opcode, resolvedMode, value, addr)
}

func buildAsmOpcodesByMnemonic() map[string]map[string]byte {
	out := make(map[string]map[string]byte, 64)
	for opcode := 0; opcode < 256; opcode++ {
		mn := opMnemonic[opcode]
		mode := opMode[opcode]
		if mn == "???" || mode == "" {
			continue
		}
		row := out[mn]
		if row == nil {
			row = make(map[string]byte, 8)
			out[mn] = row
		}
		if _, exists := row[mode]; !exists {
			row[mode] = byte(opcode)
		}
	}
	return out
}

func splitAsmStatement(text string) (string, string) {
	text = strings.TrimSpace(text)
	if text == "" {
		return "", ""
	}
	i := strings.IndexFunc(text, unicode.IsSpace)
	if i < 0 {
		return text, ""
	}
	return text[:i], strings.TrimSpace(text[i:])
}

func isDataMnemonic(mnemonic string) bool {
	return mnemonic == ".DB" || mnemonic == "DB" || mnemonic == ".BYTE" || mnemonic == "BYTE"
}

func assembleDataBytes(operand string) ([]byte, error) {
	parts := strings.FieldsFunc(operand, func(r rune) bool {
		return r == ',' || unicode.IsSpace(r)
	})
	if len(parts) == 0 {
		return nil, fmt.Errorf("missing data byte")
	}
	out := make([]byte, 0, len(parts))
	for _, p := range parts {
		v, err := parseAsmValue(p)
		if err != nil {
			return nil, err
		}
		if v > 0xFF {
			return nil, fmt.Errorf("byte out of range: %s", p)
		}
		out = append(out, byte(v))
	}
	return out, nil
}

func parseAsmOperand(operand string) (string, uint16, error) {
	text := strings.TrimSpace(operand)
	if text == "" {
		return "imp", 0, nil
	}
	if text == "A" {
		return "acc", 0, nil
	}
	if strings.HasPrefix(text, "#") {
		v, err := parseAsmValue(text[1:])
		if err != nil {
			return "", 0, err
		}
		if v > 0xFF {
			return "", 0, fmt.Errorf("immediate out of range")
		}
		return "imm", v, nil
	}
	if strings.HasPrefix(text, "(") {
		if len(text) > 4 && strings.HasSuffix(text, ",X)") {
			v, err := parseAsmValue(strings.TrimSpace(text[1 : len(text)-3]))
			if err != nil {
				return "", 0, err
			}
			if v > 0xFF {
				return "", 0, fmt.Errorf("indexed indirect operand out of range")
			}
			return "inx", v, nil
		}
		if len(text) > 4 && strings.HasSuffix(text, "),Y") {
			v, err := parseAsmValue(strings.TrimSpace(text[1 : len(text)-3]))
			if err != nil {
				return "", 0, err
			}
			if v > 0xFF {
				return "", 0, fmt.Errorf("indirect indexed operand out of range")
			}
			return "iny", v, nil
		}
		if len(text) > 2 && strings.HasSuffix(text, ")") {
			v, err := parseAsmValue(strings.TrimSpace(text[1 : len(text)-1]))
			if err != nil {
				return "", 0, err
			}
			return "ind", v, nil
		}
		return "", 0, fmt.Errorf("invalid operand syntax")
	}
	if strings.HasSuffix(text, ",X") {
		v, err := parseAsmValue(strings.TrimSpace(text[:len(text)-2]))
		if err != nil {
			return "", 0, err
		}
		return "memx", v, nil
	}
	if strings.HasSuffix(text, ",Y") {
		v, err := parseAsmValue(strings.TrimSpace(text[:len(text)-2]))
		if err != nil {
			return "", 0, err
		}
		return "memy", v, nil
	}
	v, err := parseAsmValue(text)
	if err != nil {
		return "", 0, err
	}
	return "mem", v, nil
}

func parseAsmValue(token string) (uint16, error) {
	text := strings.TrimSpace(token)
	if text == "" {
		return 0, fmt.Errorf("missing operand")
	}
	parse := func(base int, value string) (uint16, error) {
		if value == "" {
			return 0, fmt.Errorf("invalid operand: %s", token)
		}
		n, err := strconv.ParseUint(value, base, 32)
		if err != nil || n > 0xFFFF {
			return 0, fmt.Errorf("operand out of range: %s", token)
		}
		return uint16(n), nil
	}
	if strings.HasPrefix(text, "$") {
		return parse(16, strings.TrimSpace(text[1:]))
	}
	if strings.HasPrefix(text, "0X") {
		return parse(16, strings.TrimSpace(text[2:]))
	}
	if strings.HasPrefix(text, "%") {
		return parse(2, strings.TrimSpace(text[1:]))
	}
	if strings.HasSuffix(text, "H") {
		return parse(16, strings.TrimSpace(text[:len(text)-1]))
	}
	if hasHexDigit(text) {
		return parse(16, text)
	}
	return parse(10, text)
}

func hasHexDigit(text string) bool {
	for _, r := range text {
		if r >= 'A' && r <= 'F' {
			return true
		}
	}
	return false
}

func resolveAsmOpcode(modes map[string]byte, mode string, value uint16) (string, byte, error) {
	switch mode {
	case "imp", "acc", "imm", "ind", "inx", "iny":
		opcode, ok := modes[mode]
		if !ok {
			return "", 0, fmt.Errorf("unsupported addressing mode")
		}
		return mode, opcode, nil
	case "mem":
		if hasOnlyRelativeMode(modes) {
			return "rel", modes["rel"], nil
		}
		if value <= 0xFF {
			if opcode, ok := modes["zpg"]; ok {
				return "zpg", opcode, nil
			}
		}
		if opcode, ok := modes["abs"]; ok {
			return "abs", opcode, nil
		}
		if opcode, ok := modes["rel"]; ok {
			return "rel", opcode, nil
		}
		return "", 0, fmt.Errorf("unsupported addressing mode")
	case "memx":
		if value <= 0xFF {
			if opcode, ok := modes["zpx"]; ok {
				return "zpx", opcode, nil
			}
		}
		if opcode, ok := modes["abx"]; ok {
			return "abx", opcode, nil
		}
		return "", 0, fmt.Errorf("unsupported addressing mode")
	case "memy":
		if value <= 0xFF {
			if opcode, ok := modes["zpy"]; ok {
				return "zpy", opcode, nil
			}
		}
		if opcode, ok := modes["aby"]; ok {
			return "aby", opcode, nil
		}
		return "", 0, fmt.Errorf("unsupported addressing mode")
	default:
		return "", 0, fmt.Errorf("unsupported addressing mode")
	}
}

func hasOnlyRelativeMode(modes map[string]byte) bool {
	if len(modes) != 1 {
		return false
	}
	_, ok := modes["rel"]
	return ok
}

func encodeAsmInstruction(opcode byte, mode string, value uint16, addr uint16) ([]byte, error) {
	switch modeSize(mode) {
	case 1:
		return []byte{opcode}, nil
	case 2:
		if mode == "rel" {
			delta := int(value) - int(addr) - 2
			if delta < -128 || delta > 127 {
				return nil, fmt.Errorf("branch target out of range")
			}
			return []byte{opcode, byte(int8(delta))}, nil
		}
		return []byte{opcode, byte(value & 0xFF)}, nil
	case 3:
		return []byte{opcode, byte(value & 0xFF), byte((value >> 8) & 0xFF)}, nil
	default:
		return nil, fmt.Errorf("unsupported instruction size")
	}
}
