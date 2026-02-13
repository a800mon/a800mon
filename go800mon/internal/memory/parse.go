package memory

import (
	"encoding/hex"
	"fmt"
	"strconv"
	"strings"
)

func ParseHex(value string) (uint16, error) {
	text := strings.TrimSpace(strings.ToLower(value))
	text = strings.TrimPrefix(text, "$")
	text = strings.TrimPrefix(text, "0x")
	v, err := strconv.ParseUint(text, 16, 16)
	if err != nil {
		return 0, err
	}
	return uint16(v), nil
}

func ParseHexByte(value string) (byte, error) {
	parsed, err := ParseHex(value)
	if err != nil {
		return 0, fmt.Errorf("Invalid hex byte: %s", value)
	}
	if parsed > 0xFF {
		return 0, fmt.Errorf("Hex byte out of range: %s", value)
	}
	return byte(parsed), nil
}

func ParseHexValues(tokens []string) ([]byte, error) {
	out := make([]byte, 0, len(tokens))
	for _, token := range tokens {
		parsed, err := ParseHex(token)
		if err != nil {
			return nil, fmt.Errorf("Invalid hex value: %s", token)
		}
		if parsed <= 0xFF {
			out = append(out, byte(parsed))
			continue
		}
		out = append(out, byte(parsed&0xFF), byte(parsed>>8))
	}
	return out, nil
}

func ParseHexPayload(text string) ([]byte, error) {
	normalized := strings.ReplaceAll(text, ",", " ")
	fields := strings.Fields(normalized)
	if len(fields) == 0 {
		return nil, fmt.Errorf("Hex payload is empty.")
	}
	if len(fields) > 1 {
		out := make([]byte, 0, len(fields))
		for _, token := range fields {
			parsed, err := ParseHexByte(token)
			if err != nil {
				return nil, err
			}
			out = append(out, parsed)
		}
		return out, nil
	}
	value := strings.TrimSpace(strings.ToLower(fields[0]))
	value = strings.TrimPrefix(value, "$")
	value = strings.TrimPrefix(value, "0x")
	if value == "" {
		return nil, fmt.Errorf("Hex payload is empty.")
	}
	if len(value)%2 != 0 {
		return nil, fmt.Errorf("Hex payload must have an even number of digits.")
	}
	out, err := hex.DecodeString(value)
	if err != nil {
		return nil, fmt.Errorf("Invalid hex payload.")
	}
	return out, nil
}

func ParsePositiveInt(value string) (int, error) {
	text := strings.TrimSpace(strings.ToLower(value))
	if strings.HasPrefix(text, "$") {
		text = "0x" + text[1:]
	}
	parsed, err := strconv.ParseInt(text, 0, 32)
	if err != nil {
		return 0, fmt.Errorf("Invalid limit.")
	}
	if parsed <= 0 {
		return 0, fmt.Errorf("Limit must be > 0.")
	}
	return int(parsed), nil
}
