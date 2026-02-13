package a800mon

import (
	"strings"

	"go800mon/internal/memory"
	imap "go800mon/internal/memorymap"
)

func LookupSymbol(addr uint16) string {
	return imap.Lookup(addr)
}

func FindSymbolByComment(query string) (uint16, bool) {
	return imap.FindByComment(query)
}

func FindSymbolOrAddress(query string) (uint16, bool) {
	if addr, ok := FindSymbolByComment(query); ok {
		return addr, true
	}
	q := strings.TrimSpace(query)
	q = strings.TrimPrefix(q, ";")
	q = strings.TrimSpace(q)
	if q == "" {
		return 0, false
	}
	addr, err := memory.ParseHex(q)
	if err != nil {
		return 0, false
	}
	return addr, true
}
