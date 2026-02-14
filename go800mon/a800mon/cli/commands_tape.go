package cli

func cmdTapeRemove(socket string) int {
	return cmdSimple(socket, CmdRemoveTape)
}
