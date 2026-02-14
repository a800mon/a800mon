package atari

import iatascii "go800mon/internal/atascii"

func ScreenToATASCII(b byte) byte {
	return iatascii.ScreenToATASCII(b)
}

func ATASCIIToScreen(b byte) byte {
	return iatascii.ATASCIIToScreen(b)
}

func LookupATASCII(b byte) string {
	return iatascii.LookupPrintable(b)
}

func EncodeATASCIIText(text string) ([]byte, error) {
	return iatascii.EncodeText(text)
}
