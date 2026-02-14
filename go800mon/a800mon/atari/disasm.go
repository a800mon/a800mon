package atari

import idisasm "go800mon/internal/disasm"

type DecodedInstruction = idisasm.DecodedInstruction

func Disasm6502(startAddr uint16, data []byte) []string {
	return idisasm.Disasm(startAddr, data)
}

func Disasm6502One(startAddr uint16, data []byte) string {
	return idisasm.DisasmOne(startAddr, data)
}
