package a800mon

const asmCommentCol = 18

func printAsmRow(window *Window, row DisasmRow, revAttr int) {
	for _, cell := range asmRowCells(row) {
		window.Print(cell.Text, cell.Attr|revAttr, false)
	}
}

func asmRowCells(row DisasmRow) []GridCell {
	if row.Mnemonic == "" {
		if row.AsmText == "" {
			return nil
		}
		return []GridCell{{Text: row.AsmText, Attr: ColorText.Attr()}}
	}
	cells := []GridCell{{Text: row.Mnemonic, Attr: ColorMnemonic.Attr()}}
	coreLen := len([]rune(row.Mnemonic))
	if row.Operand != "" {
		cells = append(cells, GridCell{Text: " ", Attr: ColorText.Attr()})
		coreLen += 1 + len([]rune(row.Operand))
		if row.FlowTarget == nil || !row.HasOperandAddr {
			cells = append(cells, GridCell{Text: row.Operand, Attr: ColorText.Attr()})
		} else {
			start := row.OperandAddrPos[0]
			end := row.OperandAddrPos[1]
			r := []rune(row.Operand)
			if start < 0 {
				start = 0
			}
			if end > len(r) {
				end = len(r)
			}
			if start > end {
				start = end
			}
			if start > 0 {
				cells = append(cells, GridCell{Text: string(r[:start]), Attr: ColorText.Attr()})
			}
			cells = append(cells, GridCell{Text: string(r[start:end]), Attr: ColorAddress.Attr()})
			if end < len(r) {
				cells = append(cells, GridCell{Text: string(r[end:]), Attr: ColorText.Attr()})
			}
		}
	}
	if row.Comment == "" {
		return cells
	}
	if coreLen < asmCommentCol {
		cells = append(cells, GridCell{Text: spaces(asmCommentCol - coreLen), Attr: ColorText.Attr()})
	}
	cells = append(cells, GridCell{Text: " ", Attr: ColorText.Attr()})
	cells = append(cells, GridCell{Text: row.Comment, Attr: ColorComment.Attr()})
	return cells
}

func spaces(n int) string {
	if n <= 0 {
		return ""
	}
	b := make([]rune, n)
	for i := range b {
		b[i] = ' '
	}
	return string(b)
}
