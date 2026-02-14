package cli

import (
	"bufio"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"time"

	"go800mon/internal/disasm"
	"go800mon/internal/memory"
)

const debugShellHelpText = "commands: pause(p), step(s), stepvbl(v), untilret(r [pc]), continue(c), stack(t), q"

func cmdDebugShell(socket string) int {
	cl := rpcClient(socket)
	defer cl.Close()

	fmt.Println(debugShellHelpText)
	reader := bufio.NewReader(os.Stdin)
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt)
	defer signal.Stop(sigCh)
	for {
		fmt.Print("debug> ")
		line, interrupted, err := readInteractiveLine(reader, sigCh)
		if interrupted {
			fmt.Println()
			return 0
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				fmt.Println()
				return 0
			}
			return fail(err)
		}
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts := strings.Fields(line)
		cmd := strings.ToLower(parts[0])
		var cmdErr error
		switch cmd {
		case "q", "quit", "exit":
			return 0
		case "help", "?":
			fmt.Println(debugShellHelpText)
			continue
		case "pause", "p":
			var paused bool
			paused, cmdErr = pauseRPC(cl)
			if cmdErr == nil {
				if !paused {
					fmt.Println("Pause requested but emulator is still running.")
					continue
				}
				cmdErr = printCPUStateErr(cl)
			}
		case "step", "s":
			_, cmdErr = cl.Call(context.Background(), CmdStep, nil)
			if cmdErr == nil {
				cmdErr = printCPUStateErr(cl)
			}
		case "stepvbl", "v":
			_, cmdErr = cl.Call(context.Background(), CmdStepVBlank, nil)
			if cmdErr == nil {
				cmdErr = printCPUStateErr(cl)
			}
		case "untilret", "r":
			if len(parts) > 2 {
				fmt.Println("Usage: untilret [pc]")
				continue
			}
			var payload []byte
			if len(parts) == 2 {
				pc, parseErr := memory.ParseHex(parts[1])
				if parseErr != nil {
					fmt.Println(parseErr)
					continue
				}
				payload = make([]byte, 2)
				binary.LittleEndian.PutUint16(payload, pc)
			}
			_, cmdErr = cl.Call(context.Background(), CmdRunUntilReturn, payload)
			if cmdErr == nil {
				cmdErr = printCPUStateErr(cl)
			}
		case "continue", "cont", "c":
			var resumed bool
			resumed, cmdErr = continueRPC(cl)
			if cmdErr == nil && !resumed {
				fmt.Println("Continue requested but emulator is still paused.")
			}
		case "stack", "t":
			var state StackState
			state, cmdErr = cl.Stack(context.Background())
			if cmdErr == nil {
				printStackState(state)
			}
		default:
			fmt.Println("Unknown command. " + debugShellHelpText)
			continue
		}
		if cmdErr != nil {
			fmt.Println(formatCliError(cmdErr))
		}
	}
}

func pauseRPC(cl *RpcClient) (bool, error) {
	if _, err := cl.Call(context.Background(), CmdPause, nil); err != nil {
		return false, err
	}
	deadline := time.Now().Add(500 * time.Millisecond)
	for time.Now().Before(deadline) {
		st, err := cl.Status(context.Background())
		if err != nil {
			return false, err
		}
		if st.Paused {
			return true, nil
		}
		if _, err = cl.Call(context.Background(), CmdPause, nil); err != nil {
			return false, err
		}
		if _, err = cl.Call(context.Background(), CmdPing, nil); err != nil {
			return false, err
		}
	}
	return false, nil
}

func continueRPC(cl *RpcClient) (bool, error) {
	if _, err := cl.Call(context.Background(), CmdContinue, nil); err != nil {
		return false, err
	}
	deadline := time.Now().Add(500 * time.Millisecond)
	for time.Now().Before(deadline) {
		st, err := cl.Status(context.Background())
		if err != nil {
			return false, err
		}
		if !st.Paused {
			return true, nil
		}
		if _, err = cl.Call(context.Background(), CmdPing, nil); err != nil {
			return false, err
		}
	}
	return false, nil
}

func cmdJumps(socket string) int {
	state, err := rpcClient(socket).Jumps(context.Background())
	if err != nil {
		return fail(err)
	}
	for i, pc := range state.PCs {
		fmt.Printf("%02d: %04X\n", i+1, pc)
	}
	return 0
}

func printCPUState(cl *RpcClient) int {
	if err := printCPUStateErr(cl); err != nil {
		return fail(err)
	}
	return 0
}

func printCPUStateErr(cl *RpcClient) error {
	cpu, err := cl.CPUState(context.Background())
	if err != nil {
		return err
	}
	fmt.Println(formatCPU(cpu))
	return nil
}

func printStackState(state StackState) {
	fmt.Printf("S=%02X count=%d\n", state.S, len(state.Entries))
	for _, entry := range state.Entries {
		fmt.Printf("01%02X: %02X\n", entry.StackOff, entry.Value)
	}
}

func cmdHistory(socket string, count int) int {
	entries, err := rpcClient(socket).History(context.Background())
	if err != nil {
		return fail(err)
	}
	if count >= 0 && count < len(entries) {
		entries = entries[:count]
	}
	for i := len(entries) - 1; i >= 0; i-- {
		e := entries[i]
		ins := disasm.DisasmOne(e.PC, e.OpBytes())
		fmt.Printf("%03d Y=%02X X=%02X PC=%04X  %s\n", (len(entries) - i), e.Y, e.X, e.PC, ins)
	}
	return 0
}
