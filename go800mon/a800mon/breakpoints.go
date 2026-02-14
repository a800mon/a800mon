package a800mon

import (
	"fmt"
	"regexp"
	"strings"

	"go800mon/internal/memory"
)

var bpConditionTypes = map[string]byte{
	"pc":     1,
	"a":      2,
	"x":      3,
	"y":      4,
	"s":      5,
	"read":   6,
	"write":  7,
	"access": 8,
}

var bpTypeNames = map[byte]string{
	1: "pc",
	2: "a",
	3: "x",
	4: "y",
	5: "s",
	6: "read",
	7: "write",
	8: "access",
	9: "mem",
}

var bpOpIDs = map[string]byte{
	"<":  1,
	"<=": 2,
	"=":  3,
	"==": 3,
	"<>": 4,
	"!=": 4,
	">=": 5,
	">":  6,
}

var bpOpNames = map[byte]string{
	1: "<",
	2: "<=",
	3: "==",
	4: "<>",
	5: ">=",
	6: ">",
}

var bpAndWordRe = regexp.MustCompile(`(?i)\bAND\b`)
var bpOrWordRe = regexp.MustCompile(`(?i)\bOR\b`)

func BPTypeName(condType byte) string {
	name := bpTypeNames[condType]
	if name != "" {
		return name
	}
	return fmt.Sprintf("type%d", condType)
}

func BPOpSymbol(op byte) string {
	name := bpOpNames[op]
	if name != "" {
		return name
	}
	return fmt.Sprintf("op%d", op)
}

func splitBPExpression(expr string) (string, string, string, bool) {
	text := strings.TrimSpace(expr)
	for _, op := range []string{"<=", ">=", "==", "<>", "!=", "=", "<", ">"} {
		pos := strings.Index(text, op)
		if pos <= 0 {
			continue
		}
		left := strings.TrimSpace(text[:pos])
		right := strings.TrimSpace(text[pos+len(op):])
		if right == "" {
			break
		}
		return left, op, right, true
	}
	return "", "", "", false
}

func ParseBPCondition(expr string) (BreakpointCondition, error) {
	left, opText, valueText, ok := splitBPExpression(expr)
	if !ok {
		return BreakpointCondition{}, fmt.Errorf("invalid breakpoint condition: %s", expr)
	}
	op, ok := bpOpIDs[opText]
	if !ok {
		return BreakpointCondition{}, fmt.Errorf("invalid breakpoint operator in condition: %s", expr)
	}
	leftKey := strings.ToLower(strings.TrimSpace(left))
	cond := BreakpointCondition{Op: op}
	if t, ok := bpConditionTypes[leftKey]; ok {
		cond.Type = t
	} else if strings.HasPrefix(leftKey, "mem[") && strings.HasSuffix(leftKey, "]") {
		addr, err := memory.ParseHex(leftKey[4 : len(leftKey)-1])
		if err != nil {
			return BreakpointCondition{}, fmt.Errorf("invalid memory address in condition: %s", expr)
		}
		cond.Type = 9
		cond.Addr = addr
	} else if strings.HasPrefix(leftKey, "mem:") {
		addr, err := memory.ParseHex(leftKey[4:])
		if err != nil {
			return BreakpointCondition{}, fmt.Errorf("invalid memory address in condition: %s", expr)
		}
		cond.Type = 9
		cond.Addr = addr
	} else {
		return BreakpointCondition{}, fmt.Errorf("invalid breakpoint source in condition: %s", expr)
	}
	value, err := memory.ParseHex(valueText)
	if err != nil {
		return BreakpointCondition{}, fmt.Errorf("invalid breakpoint value in condition: %s", expr)
	}
	cond.Value = value
	return cond, nil
}

func ParseBPClause(expr string) ([]BreakpointCondition, error) {
	clauses, err := ParseBPClauses(expr)
	if err != nil {
		return nil, err
	}
	if len(clauses) != 1 {
		return nil, fmt.Errorf("use a single OR clause in this context")
	}
	return clauses[0], nil
}

func normalizeBPLogic(expr string) string {
	text := bpAndWordRe.ReplaceAllString(expr, "&&")
	return bpOrWordRe.ReplaceAllString(text, "||")
}

func ParseBPClauses(expr string) ([][]BreakpointCondition, error) {
	text := strings.TrimSpace(normalizeBPLogic(expr))
	if text == "" {
		return nil, fmt.Errorf("breakpoint clause is empty")
	}
	rawClauses := strings.Split(text, "||")
	if len(rawClauses) == 0 {
		return nil, fmt.Errorf("invalid breakpoint clause")
	}
	clauses := make([][]BreakpointCondition, 0, len(rawClauses))
	for _, rawClause := range rawClauses {
		clauseText := strings.TrimSpace(rawClause)
		if clauseText == "" {
			return nil, fmt.Errorf("invalid breakpoint clause")
		}
		parts := strings.Split(clauseText, "&&")
		if len(parts) == 0 {
			return nil, fmt.Errorf("invalid breakpoint clause")
		}
		conds := make([]BreakpointCondition, 0, len(parts))
		for _, part := range parts {
			item := strings.TrimSpace(part)
			if item == "" {
				return nil, fmt.Errorf("invalid breakpoint clause")
			}
			cond, err := ParseBPCondition(item)
			if err != nil {
				return nil, err
			}
			conds = append(conds, cond)
		}
		clauses = append(clauses, conds)
	}
	return clauses, nil
}

func formatBPValue(condType byte, value uint16) string {
	if condType == 2 || condType == 3 || condType == 4 || condType == 5 {
		return fmt.Sprintf("$%02X", value)
	}
	return fmt.Sprintf("$%04X", value)
}

func FormatBPCondition(cond BreakpointCondition) string {
	op := BPOpSymbol(cond.Op)
	if cond.Type == 9 {
		return fmt.Sprintf("mem[%04X] %s %s", cond.Addr, op, formatBPValue(cond.Type, cond.Value))
	}
	name := BPTypeName(cond.Type)
	return fmt.Sprintf("%s %s %s", name, op, formatBPValue(cond.Type, cond.Value))
}
