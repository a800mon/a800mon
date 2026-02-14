package cli

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"

	"go800mon/internal/memory"
)

func cmdTrainer(socket string, args cliTrainerCmd) int {
	start, err := memory.ParseHex(args.Start)
	if err != nil {
		return fail(err)
	}
	stop, err := memory.ParseHex(args.Stop)
	if err != nil {
		return fail(err)
	}
	initial, err := memory.ParseHexByte(args.Value)
	if err != nil {
		return fail(err)
	}
	trainer, err := NewTrainer(start, stop, nil)
	if err != nil {
		return fail(err)
	}
	cl := rpcClient(socket)
	defer cl.Close()
	trainer.BindReader(func(addr uint16, length int) ([]byte, error) {
		return cl.ReadMemoryChunked(context.Background(), addr, length)
	})
	matches, err := trainer.Start(&initial)
	if err != nil {
		return fail(err)
	}
	fmt.Printf(
		"range=%04X-%04X initial=%02X matches=%d\n",
		start,
		stop,
		initial,
		matches,
	)
	fmt.Println("commands: c <value>, nc, p [limit], q")
	if matches == 0 {
		return 0
	}
	if matches == 1 {
		printSingleTrainerMatch(trainer)
	}

	reader := bufio.NewReader(os.Stdin)
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt)
	defer signal.Stop(sigCh)
	for {
		fmt.Print("trainer> ")
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
		switch cmd {
		case "q":
			return 0
		case "p":
			if len(parts) > 2 {
				fmt.Println("Usage: p [limit]")
				continue
			}
			limit := 20
			if len(parts) == 2 {
				limit, err = memory.ParsePositiveInt(parts[1])
				if err != nil {
					fmt.Println(err)
					continue
				}
			}
			printTrainerMatches(trainer, limit)
		case "nc":
			if len(parts) != 1 {
				fmt.Println("Usage: nc")
				continue
			}
			matches, err = trainer.NotChanged()
			if err != nil {
				return fail(err)
			}
			fmt.Printf("matches=%d\n", matches)
			if matches == 0 {
				return 0
			}
			if matches == 1 {
				printSingleTrainerMatch(trainer)
			}
		case "c":
			if len(parts) != 2 {
				fmt.Println("Usage: c <value>")
				continue
			}
			var next byte
			next, err = memory.ParseHexByte(parts[1])
			if err != nil {
				fmt.Println(err)
				continue
			}
			matches, err = trainer.Changed(next)
			if err != nil {
				return fail(err)
			}
			fmt.Printf("matches=%d\n", matches)
			if matches == 0 {
				return 0
			}
			if matches == 1 {
				printSingleTrainerMatch(trainer)
			}
		default:
			fmt.Println("Unknown command. Use: c <value>, nc, p [limit], q")
		}
	}
}

func readInteractiveLine(reader *bufio.Reader, sigCh <-chan os.Signal) (string, bool, error) {
	lineCh := make(chan string, 1)
	errCh := make(chan error, 1)
	go func() {
		line, err := reader.ReadString('\n')
		if err != nil {
			errCh <- err
			return
		}
		lineCh <- line
	}()
	select {
	case <-sigCh:
		return "", true, nil
	case err := <-errCh:
		return "", false, err
	case line := <-lineCh:
		return line, false, nil
	}
}

func printTrainerMatches(trainer *Trainer, limit int) {
	total := trainer.MatchCount()
	fmt.Printf("matches=%d\n", total)
	if total == 0 {
		return
	}
	rows := trainer.Rows(limit)
	fmt.Println("idx  addr  val")
	for i, row := range rows {
		fmt.Printf("%03d  %04X  %02X\n", i+1, row.Addr, row.Value)
	}
	if len(rows) < total {
		fmt.Printf("... %d more\n", total-len(rows))
	}
}

func printSingleTrainerMatch(trainer *Trainer) {
	rows := trainer.Rows(1)
	if len(rows) == 0 {
		return
	}
	fmt.Println("idx  addr  val")
	fmt.Printf("001  %04X  %02X\n", rows[0].Addr, rows[0].Value)
}
