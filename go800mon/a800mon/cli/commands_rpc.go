package cli

import (
	"context"
	"os"
)

func cmdPing(socket string) int {
	data, err := rpcClient(socket).Call(context.Background(), CmdPing, nil)
	if err != nil {
		return fail(err)
	}
	if len(data) > 0 {
		_, _ = os.Stdout.Write(data)
	}
	return 0
}
