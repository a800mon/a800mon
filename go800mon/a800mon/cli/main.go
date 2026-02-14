package cli

import (
	"fmt"
	"os"
	"strings"

	"github.com/alecthomas/kong"
)

func Main(argv []string) int {
	if len(argv) == 0 {
		return cmdMonitor("/tmp/atari.sock")
	}
	normalizedArgv := normalizeSearchArgv(argv)
	args, parsed, err := parseCLI(normalizedArgv)
	if err != nil && canFallbackToMonitor(argv) {
		fallbackArgv := append(append([]string{}, normalizedArgv...), "monitor")
		args, parsed, err = parseCLI(fallbackArgv)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, formatCliError(err))
		return 2
	}
	socket := args.Socket
	selected := parsed.Selected()
	if selected == nil {
		return cmdMonitor(socket)
	}
	switch normalizeSelectedPath(selected.Path()) {
	case "monitor":
		return cmdMonitor(socket)
	case "run":
		return cmdRun(socket, args.Run.Path)
	case "debug", "debug shell":
		return cmdDebugShell(socket)
	case "debug jumps":
		return cmdJumps(socket)
	case "debug history":
		return cmdHistory(socket, args.Debug.History.Count)
	case "emulator", "emulator status":
		return cmdStatus(socket)
	case "emulator reboot":
		return cmdEmulatorReboot(socket, args.Emulator.Reboot)
	case "emulator stop":
		return cmdSimple(socket, CmdStopEmulator)
	case "emulator restart":
		return cmdSimple(socket, CmdRestartEmulator)
	case "emulator features":
		return cmdEmulatorConfig(socket)
	case "bp", "bp ls":
		return cmdBPList(socket)
	case "bp add":
		return cmdBPAdd(socket, args.BP.Add)
	case "bp del":
		return cmdBPDelete(socket, args.BP.Del)
	case "bp clear":
		return cmdBPClear(socket)
	case "bp on":
		return cmdBPSetEnabled(socket, true)
	case "bp off":
		return cmdBPSetEnabled(socket, false)
	case "bp scanline":
		return cmdBLine(socket, args.BP.Scanline)
	case "dump dlist":
		return cmdDumpDList(socket, args.Dump.DList)
	case "dump gtia":
		return cmdGTIAState(socket)
	case "dump antic":
		return cmdANTICState(socket)
	case "dump pia":
		return cmdPIAState(socket)
	case "dump pokey":
		return cmdPOKEYState(socket)
	case "cpu", "cpu get":
		return cmdCPUState(socket)
	case "cpu set":
		return cmdSetReg(socket, args.CPU.Set)
	case "cpu bbrk":
		return cmdBBRK(socket, args.CPU.BBRK)
	case "mem read":
		return cmdReadMem(socket, args.Mem.Read)
	case "mem write":
		return cmdWriteMem(socket, args.Mem.Write)
	case "mem search":
		return cmdSearch(socket, args.Mem.Search)
	case "mem disasm":
		return cmdDisasm(socket, args.Mem.Disasm)
	case "rpc ping":
		return cmdPing(socket)
	case "cart", "cart status":
		return cmdCartState(socket)
	case "cart remove":
		return cmdCartRemove(socket)
	case "tape remove":
		return cmdTapeRemove(socket)
	case "disk remove":
		return cmdDiskRemove(socket, args.Disk.Remove)
	case "trainer":
		return cmdTrainer(socket, args.Trainer)
	case "screen":
		return cmdScreen(socket, args.Screen)
	default:
		return 2
	}
}

func normalizeSearchArgv(argv []string) []string {
	out := append([]string{}, argv...)
	seenSearch := false
	for i := 0; i < len(out); i++ {
		token := out[i]
		if token == "--" {
			break
		}
		if !seenSearch && i > 0 && out[i-1] == "mem" && (token == "search" || token == "s") {
			seenSearch = true
			continue
		}
		if !seenSearch {
			continue
		}
		if token == "-s" {
			out[i] = "--screen"
		}
	}
	return out
}

func normalizeSelectedPath(path string) string {
	path = cliPathAliasPattern.ReplaceAllString(path, "")
	return strings.Join(strings.Fields(strings.ReplaceAll(path, ".", " ")), " ")
}

func parseCLI(argv []string) (cliArgs, *kong.Context, error) {
	var args cliArgs
	parser, err := kong.New(
		&args,
		kong.Name("go800mon"),
		kong.Description("Atari800 monitor UI and CLI."),
		kong.UsageOnError(),
		kong.ConfigureHelp(kong.HelpOptions{
			Compact:   true,
			FlagsLast: true,
		}),
		kong.Help(colorizedHelpPrinter(kong.DefaultHelpPrinter)),
		kong.ShortHelp(colorizedHelpPrinter(kong.DefaultShortHelpPrinter)),
	)
	if err != nil {
		return args, nil, err
	}
	parsed, err := parser.Parse(argv)
	if err != nil {
		return args, nil, err
	}
	return args, parsed, nil
}

func canFallbackToMonitor(argv []string) bool {
	for i := 0; i < len(argv); i++ {
		token := argv[i]
		switch token {
		case "-s", "--socket":
			if i+1 >= len(argv) || strings.HasPrefix(argv[i+1], "-") {
				return false
			}
			i++
			continue
		case "--":
			return i+1 >= len(argv)
		}
		if strings.HasPrefix(token, "--socket=") || strings.HasPrefix(token, "-s=") {
			continue
		}
		if strings.HasPrefix(token, "-") {
			continue
		}
		return false
	}
	return true
}

func rpcClient(socket string) *RpcClient {
	return NewRpcClient(NewSocketTransport(socket))
}
