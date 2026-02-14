package atari

import dl "go800mon/internal/displaylist"

const (
	DMACTLAddr   = dl.DMACTLAddr
	DMACTLHWAddr = dl.DMACTLHWAddr
	DLPTRSAddr   = dl.DLPTRSAddr
)

func DecodeDisplayList(startAddr uint16, data []byte) dl.DisplayList {
	return dl.Decode(startAddr, data)
}
