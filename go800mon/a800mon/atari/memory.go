package atari

import imemory "go800mon/internal/memory"

func DumpMemoryRaw(buffer []byte, useATASCII bool) []byte {
	return imemory.DumpRaw(buffer, useATASCII)
}

func DumpMemoryJSON(address uint16, buffer []byte, useATASCII bool) (string, error) {
	return imemory.DumpJSON(address, buffer, useATASCII)
}

func DumpMemoryHuman(address uint16, length int, buffer []byte, useATASCII bool, columns int, showHex bool, showASCII bool) string {
	return imemory.DumpHuman(address, length, buffer, useATASCII, columns, showHex, showASCII)
}
