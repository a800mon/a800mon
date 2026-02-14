package cli

import (
	"context"
	"fmt"
)

func cmdCartState(socket string) int {
	state, err := rpcClient(socket).CartrigeState(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("autoreboot:    %d\n", state.Autoreboot)
	fmt.Printf("main_present:  %d\n", state.Main.Present)
	fmt.Printf("main_type:     %d\n", state.Main.Type)
	fmt.Printf("main_state:    %08X\n", state.Main.State)
	fmt.Printf("main_size_kb:  %d\n", state.Main.SizeKB)
	fmt.Printf("main_raw:      %d\n", state.Main.Raw)
	fmt.Printf("piggy_present: %d\n", state.Piggy.Present)
	fmt.Printf("piggy_type:    %d\n", state.Piggy.Type)
	fmt.Printf("piggy_state:   %08X\n", state.Piggy.State)
	fmt.Printf("piggy_size_kb: %d\n", state.Piggy.SizeKB)
	fmt.Printf("piggy_raw:     %d\n", state.Piggy.Raw)
	return 0
}

func cmdCartRemove(socket string) int {
	return cmdSimple(socket, CmdRemoveCartrige)
}
