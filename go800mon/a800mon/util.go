package a800mon

import "fmt"

func FormatCPU(cpu CPUState) string {
	n := "-"
	if cpu.P&0x80 != 0 {
		n = "N"
	}
	v := "-"
	if cpu.P&0x40 != 0 {
		v = "V"
	}
	d := "-"
	if cpu.P&0x08 != 0 {
		d = "D"
	}
	i := "-"
	if cpu.P&0x04 != 0 {
		i = "I"
	}
	z := "-"
	if cpu.P&0x02 != 0 {
		z = "Z"
	}
	c := "-"
	if cpu.P&0x01 != 0 {
		c = "C"
	}
	return fmt.Sprintf("%3d %3d A=%02X X=%02X Y=%02X S=%02X P=%s%s*-%s%s%s%s PC=%04X", cpu.YPos, cpu.XPos, cpu.A, cpu.X, cpu.Y, cpu.S, n, v, d, i, z, c, cpu.PC)
}

func formatCPU(cpu CPUState) string {
	return FormatCPU(cpu)
}

func FormatHMS(ms uint64) string {
	total := int(ms / 1000)
	h := total / 3600
	m := (total % 3600) / 60
	s := total % 60
	return fmt.Sprintf("%02d:%02d:%02d", h, m, s)
}

func formatHMS(ms uint64) string {
	return FormatHMS(ms)
}

func padRight(s string, n int) string {
	r := []rune(s)
	if len(r) >= n {
		return string(r[:n])
	}
	for len(r) < n {
		r = append(r, ' ')
	}
	return string(r)
}

func trimLastRune(text string) string {
	r := []rune(text)
	if len(r) == 0 {
		return ""
	}
	return string(r[:len(r)-1])
}
