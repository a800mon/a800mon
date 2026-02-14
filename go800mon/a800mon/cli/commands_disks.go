package cli

import (
	"context"
	"errors"
)

func cmdDiskRemove(socket string, args cliDiskRemoveCmd) int {
	if args.All && args.Number != nil {
		return fail(errors.New("Use either --all or <number>, not both."))
	}
	var payload []byte
	if args.Number != nil {
		number := *args.Number
		if number < 1 || number > 255 {
			return fail(errors.New("Disk number must be in range 1..255."))
		}
		payload = []byte{byte(number)}
	}
	if _, err := rpcClient(socket).Call(context.Background(), CmdRemoveDisks, payload); err != nil {
		return fail(err)
	}
	return 0
}
