package a800mon

import (
	"bufio"
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/alecthomas/kong"
	"go800mon/internal/disasm"
	dl "go800mon/internal/displaylist"
	"go800mon/internal/memory"
)

type cliArgs struct {
	Socket         string            `short:"s" default:"/tmp/atari.sock" help:"Path to Atari800 monitor socket."`
	Monitor        cliEmptyCmd       `cmd:"" help:"Run the curses monitor UI."`
	Run            cliRunCmd         `cmd:"" help:"Run a file via RPC."`
	Pause          cliEmptyCmd       `cmd:"" help:"Pause emulation."`
	Step           cliEmptyCmd       `cmd:"" help:"Step one instruction."`
	StepVBL        cliEmptyCmd       `cmd:"" name:"stepvbl" help:"Step one VBLANK."`
	StepOver       cliStepPCOptional `cmd:"" name:"stepover" help:"Step over instruction."`
	RunUntilRet    cliStepPCOptional `cmd:"" name:"rununtilret" help:"Run until return from subroutine."`
	Continue       cliEmptyCmd       `cmd:"" name:"continue" help:"Continue emulation."`
	Coldstart      cliEmptyCmd       `cmd:"" help:"Cold start emulation."`
	Warmstart      cliEmptyCmd       `cmd:"" help:"Warm start emulation."`
	Removecartrige cliEmptyCmd       `cmd:"" help:"Remove cartridge."`
	Removetape     cliEmptyCmd       `cmd:"" help:"Remove cassette."`
	Removedisks    cliEmptyCmd       `cmd:"" help:"Remove all disks."`
	Emulator       cliEmulatorCmd    `cmd:"" help:"Emulator control commands."`
	BP             cliBreakpointsCmd `cmd:"" name:"bp" help:"Manage user breakpoints."`
	DList          cliDListCmd       `cmd:"" name:"dlist" help:"Dump display list."`
	CPUState       cliEmptyCmd       `cmd:"" name:"cpu" help:"Show CPU state."`
	GTIAState      cliEmptyCmd       `cmd:"" name:"gtia" help:"Show GTIA register state."`
	ANTICState     cliEmptyCmd       `cmd:"" name:"antic" help:"Show ANTIC register state."`
	CartState      cliEmptyCmd       `cmd:"" name:"cart" help:"Show cartridge state."`
	Jumps          cliEmptyCmd       `cmd:"" name:"jumps" help:"Show jump history ring."`
	PIAState       cliEmptyCmd       `cmd:"" name:"pia" help:"Show PIA register state."`
	POKEYState     cliEmptyCmd       `cmd:"" name:"pokey" help:"Show POKEY register state."`
	Stack          cliEmptyCmd       `cmd:"" name:"stack" help:"Show 6502 stack bytes."`
	History        cliHistoryCmd     `cmd:"" help:"Show CPU execution history."`
	BBRK           cliBBRKCmd        `cmd:"" name:"bbrk" help:"Query/set break-on-BRK mode."`
	BLine          cliBLineCmd       `cmd:"" name:"bline" help:"Query/set scanline break value."`
	Trainer        cliTrainerCmd     `cmd:"" name:"trainer" help:"Interactive value trainer."`
	Search         cliSearchCmd      `cmd:"" name:"search" help:"Search memory for a pattern."`
	SetReg         cliSetRegCmd      `cmd:"" name:"cpureg" help:"Set CPU register or flag."`
	Status         cliEmptyCmd       `cmd:"" help:"Get status."`
	Ping           cliEmptyCmd       `cmd:"" help:"Ping RPC server."`
	ReadMem        cliReadMemCmd     `cmd:"" name:"readmem" help:"Read memory."`
	WriteMem       cliWriteMemCmd    `cmd:"" name:"writemem" help:"Write memory."`
	Disasm         cliDisasmCmd      `cmd:"" help:"Disassemble 6502 memory."`
	Screen         cliScreenCmd      `cmd:"" help:"Dump screen memory segments."`
}

type cliEmptyCmd struct{}

type cliRunCmd struct {
	Path string `arg:"" help:"Path to file."`
}

type cliHistoryCmd struct {
	Count int `short:"n" name:"count" default:"-1" help:"Limit output to last N entries."`
}

type cliStepPCOptional struct {
	PC *string `arg:"" optional:"" help:"Optional PC address (hex: 0xNNNN, $NNNN, NNNN)."`
}

type cliEmulatorCmd struct {
	Stop     cliEmptyCmd `cmd:"" help:"Stop emulator."`
	Restart  cliEmptyCmd `cmd:"" help:"Restart emulator."`
	Features cliEmptyCmd `cmd:"" help:"Show emulator capability flags."`
	Debug    cliEmptyCmd `cmd:"" help:"Switch to emulator built-in monitor."`
}

type cliBreakpointsCmd struct {
	LS    cliEmptyCmd    `cmd:"" default:"1" name:"ls" help:"List user breakpoint clauses."`
	Add   cliBPAddCmd    `cmd:"" help:"Add one breakpoint clause (AND)."`
	Del   cliBPDeleteCmd `cmd:"" name:"del" help:"Delete clause by index (1-based)."`
	Clear cliEmptyCmd    `cmd:"" help:"Clear all breakpoint clauses."`
	On    cliEmptyCmd    `cmd:"" name:"on" help:"Enable all user breakpoints."`
	Off   cliEmptyCmd    `cmd:"" name:"off" help:"Disable all user breakpoints."`
}

type cliBPAddCmd struct {
	Conditions []string `arg:"" help:"Conditions joined by AND in one clause."`
}

type cliBPDeleteCmd struct {
	Index int `arg:"" help:"Clause index (1-based)."`
}

type cliBBRKCmd struct {
	Enabled *string `arg:"" optional:"" help:"Optional state: on/off/1/0."`
}

type cliBLineCmd struct {
	Scanline *string `arg:"" optional:"" help:"Optional scanline (hex: 0xNNNN, $NNNN, NNNN)."`
}

type cliTrainerCmd struct {
	Start string `arg:"" help:"Start address (hex: 0xNNNN, $NNNN, NNNN)."`
	Stop  string `arg:"" help:"Stop address (hex: 0xNNNN, $NNNN, NNNN)."`
	Value string `arg:"" help:"Initial byte value (hex: 00..FF)."`
}

type cliSearchCmd struct {
	ATASCII      bool     `short:"a" name:"atascii" help:"Convert input text to ATASCII bytes before search."`
	SearchScreen bool     `name:"screen" help:"Convert input text to screen-codes before search."`
	Start        string   `arg:"" help:"Start address (hex: 0xNNNN, $NNNN, NNNN)."`
	End          string   `arg:"" help:"End address (hex: 0xNNNN, $NNNN, NNNN)."`
	Pattern      []string `arg:"" help:"Hex bytes by default; text when --atascii and/or --screen is used."`
}

type cliSetRegCmd struct {
	Target string `arg:"" enum:"pc,a,x,y,s,n,v,d,i,z,c" help:"Target register/flag."`
	Value  string `arg:"" help:"Value (hex: 0xNNNN, $NNNN, NNNN)."`
}

type cliDListCmd struct {
	Address *string `arg:"" optional:"" help:"Optional display list start address (hex: 0xNNNN, $NNNN, NNNN)."`
}

type cliReadMemCmd struct {
	Addr    string `arg:"" help:"Address (hex: 0xNNNN, $NNNN, NNNN)."`
	Length  string `arg:"" help:"Length (hex: 0xNNNN, $NNNN, NNNN)."`
	Raw     bool   `name:"raw" xor:"format" help:"Output raw bytes without formatting."`
	JSON    bool   `name:"json" xor:"format" help:"Output JSON with address and buffer."`
	ATASCII bool   `short:"a" name:"atascii" help:"Render ASCII column using ATASCII mapping."`
	Columns *int   `short:"c" name:"columns" help:"Bytes per line (default: 16)."`
	NoHex   bool   `name:"nohex" help:"Hide hex column in formatted output."`
	NoASCII bool   `name:"noascii" help:"Hide ASCII column in formatted output."`
}

type cliWriteMemCmd struct {
	Addr    string   `arg:"" help:"Address (hex: 0xNNNN, $NNNN, NNNN)."`
	Bytes   []string `arg:"" optional:"" help:"Byte/word values (hex). Values > FF are written as little-endian words."`
	Hex     *string  `name:"hex" help:"Hex payload (001122...) or '-' to read from stdin."`
	Text    *string  `name:"text" help:"Text payload or '-' to read from stdin."`
	ATASCII bool     `short:"a" name:"atascii" help:"Encode --text using ATASCII bytes."`
	Screen  bool     `short:"S" name:"screen" help:"Convert payload from ATASCII to screen codes."`
}

type cliDisasmCmd struct {
	Addr   string `arg:"" help:"Address (hex: 0xNNNN, $NNNN, NNNN)."`
	Length string `arg:"" help:"Length (hex: 0xNNNN, $NNNN, NNNN)."`
}

type cliScreenCmd struct {
	Segment *int `arg:"" optional:"" help:"Segment number (1-based). When omitted, dumps all segments."`
	List    bool `short:"l" name:"list" help:"List screen segments."`
	Raw     bool `name:"raw" xor:"format" help:"Output raw bytes without formatting."`
	JSON    bool `name:"json" xor:"format" help:"Output JSON with address and buffer."`
	ATASCII bool `short:"a" name:"atascii" help:"Render ASCII column using ATASCII mapping."`
	Columns *int `short:"c" name:"columns" help:"Bytes per line (default: 16)."`
	NoHex   bool `name:"nohex" help:"Hide hex column in formatted output."`
	NoASCII bool `name:"noascii" help:"Hide ASCII column in formatted output."`
}

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
	switch selected.Path() {
	case "monitor":
		return cmdMonitor(socket)
	case "run":
		return cmdRun(socket, args.Run.Path)
	case "pause":
		return cmdSimple(socket, CmdPause)
	case "step":
		return cmdStepLike(socket, CmdStep)
	case "stepvbl":
		return cmdStepLike(socket, CmdStepVBlank)
	case "stepover":
		return cmdStepOver(socket, args.StepOver)
	case "rununtilret":
		return cmdRunUntilReturn(socket, args.RunUntilRet)
	case "continue":
		return cmdSimple(socket, CmdContinue)
	case "coldstart":
		return cmdSimple(socket, CmdColdstart)
	case "warmstart":
		return cmdSimple(socket, CmdWarmstart)
	case "removecartrige":
		return cmdSimple(socket, CmdRemoveCartrige)
	case "removetape":
		return cmdSimple(socket, CmdRemoveTape)
	case "removedisks":
		return cmdSimple(socket, CmdRemoveDisks)
	case "emulator stop", "emulator.stop":
		return cmdSimple(socket, CmdStopEmulator)
	case "emulator restart", "emulator.restart":
		return cmdSimple(socket, CmdRestartEmulator)
	case "emulator debug", "emulator.debug":
		return cmdSimple(socket, CmdBuiltinMonitor)
	case "emulator features", "emulator.features":
		return cmdEmulatorConfig(socket)
	case "bp", "bp ls", "bp.ls":
		return cmdBPList(socket)
	case "bp add", "bp.add":
		return cmdBPAdd(socket, args.BP.Add)
	case "bp del", "bp.del":
		return cmdBPDelete(socket, args.BP.Del)
	case "bp clear", "bp.clear":
		return cmdBPClear(socket)
	case "bp on", "bp.on":
		return cmdBPSetEnabled(socket, true)
	case "bp off", "bp.off":
		return cmdBPSetEnabled(socket, false)
	case "dlist":
		return cmdDumpDList(socket, args.DList)
	case "cpu":
		return cmdCPUState(socket)
	case "gtia":
		return cmdGTIAState(socket)
	case "antic":
		return cmdANTICState(socket)
	case "cart":
		return cmdCartState(socket)
	case "jumps":
		return cmdJumps(socket)
	case "pia":
		return cmdPIAState(socket)
	case "pokey":
		return cmdPOKEYState(socket)
	case "stack":
		return cmdStack(socket)
	case "history":
		return cmdHistory(socket, args.History.Count)
	case "bbrk":
		return cmdBBRK(socket, args.BBRK)
	case "bline":
		return cmdBLine(socket, args.BLine)
	case "trainer":
		return cmdTrainer(socket, args.Trainer)
	case "search":
		return cmdSearch(socket, args.Search)
	case "cpureg":
		return cmdSetReg(socket, args.SetReg)
	case "status":
		return cmdStatus(socket)
	case "ping":
		return cmdPing(socket)
	case "readmem":
		return cmdReadMem(socket, args.ReadMem)
	case "writemem":
		return cmdWriteMem(socket, args.WriteMem)
	case "disasm":
		return cmdDisasm(socket, args.Disasm)
	case "screen":
		return cmdScreen(socket, args.Screen)
	default:
		return 2
	}
}

func normalizeSearchArgv(argv []string) []string {
	out := append([]string{}, argv...)
	seenSearch := false
	for i, token := range out {
		if !seenSearch {
			if token == "search" {
				seenSearch = true
			}
			continue
		}
		if token == "--" {
			break
		}
		if token == "-s" {
			out[i] = "--screen"
		}
	}
	return out
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

func cmdMonitor(socket string) int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	err := RunMonitor(ctx, socket)
	if err != nil && err != context.Canceled {
		return fail(err)
	}
	return 0
}

func cmdRun(socket string, pathArg string) int {
	path, err := expandPath(pathArg)
	if err != nil {
		return fail(err)
	}
	_, err = rpcClient(socket).Call(context.Background(), CmdRun, []byte(path))
	if err != nil {
		return fail(err)
	}
	return 0
}

func cmdSimple(socket string, cmd Command) int {
	_, err := rpcClient(socket).Call(context.Background(), cmd, nil)
	if err != nil {
		return fail(err)
	}
	return 0
}

func cmdStepLike(socket string, cmd Command) int {
	cl := rpcClient(socket)
	if _, err := cl.Call(context.Background(), cmd, nil); err != nil {
		return fail(err)
	}
	return printCPUState(cl)
}

func cmdStepOver(socket string, args cliStepPCOptional) int {
	cl := rpcClient(socket)
	var payload []byte
	if args.PC != nil {
		pc, err := memory.ParseHex(*args.PC)
		if err != nil {
			return fail(err)
		}
		payload = make([]byte, 2)
		binary.LittleEndian.PutUint16(payload, pc)
	}
	if _, err := cl.Call(context.Background(), CmdStepOver, payload); err != nil {
		return fail(err)
	}
	return printCPUState(cl)
}

func cmdRunUntilReturn(socket string, args cliStepPCOptional) int {
	cl := rpcClient(socket)
	var payload []byte
	if args.PC != nil {
		pc, err := memory.ParseHex(*args.PC)
		if err != nil {
			return fail(err)
		}
		payload = make([]byte, 2)
		binary.LittleEndian.PutUint16(payload, pc)
	}
	if _, err := cl.Call(context.Background(), CmdRunUntilReturn, payload); err != nil {
		return fail(err)
	}
	return printCPUState(cl)
}

func cmdDumpDList(socket string, args cliDListCmd) int {
	cl := rpcClient(socket)
	ctx := context.Background()
	var (
		start uint16
		err   error
		dump  []byte
	)
	if args.Address == nil {
		start, err = cl.ReadVector(ctx, DLPTRSAddr)
		if err != nil {
			return fail(err)
		}
		dump, err = cl.ReadDisplayList(ctx)
	} else {
		start, err = memory.ParseHex(*args.Address)
		if err != nil {
			return fail(err)
		}
		dump, err = cl.ReadDisplayListAt(ctx, start)
	}
	if err != nil {
		return fail(err)
	}
	dmactl, err := cl.ReadByte(ctx, DMACTLAddr)
	if err != nil {
		return fail(err)
	}
	if dmactl&0x03 == 0 {
		if hw, hwErr := cl.ReadByte(ctx, DMACTLHWAddr); hwErr == nil {
			dmactl = hw
		}
	}
	dlist := DecodeDisplayList(start, dump)
	for _, c := range dlist.Compacted() {
		if c.Count > 1 {
			fmt.Printf("%04X: %dx %s\n", c.Entry.Addr, c.Count, c.Entry.Description())
		} else {
			fmt.Printf("%04X: %s\n", c.Entry.Addr, c.Entry.Description())
		}
	}
	fmt.Println()
	fmt.Printf("Length: %04X\n", len(dump))
	segs := dlist.ScreenSegments(dmactl)
	if len(segs) > 0 {
		fmt.Println("Screen segments:")
		for i, seg := range segs {
			length := seg.End - seg.Start
			last := (seg.End - 1) & 0xFFFF
			fmt.Printf("#%d %04X-%04X len=%04X antic=%d\n", i+1, seg.Start, last, length, seg.Mode)
		}
	}
	return 0
}

func cmdCPUState(socket string) int {
	return printCPUState(rpcClient(socket))
}

func cmdGTIAState(socket string) int {
	state, err := rpcClient(socket).GTIAState(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("HPOSP:  %s\n", fmtBytes(state.HPOSP[:]))
	fmt.Printf("HPOSM:  %s\n", fmtBytes(state.HPOSM[:]))
	fmt.Printf("SIZEP:  %s\n", fmtBytes(state.SIZEP[:]))
	fmt.Printf("SIZEM:  %02X\n", state.SIZEM)
	fmt.Printf("GRAFP:  %s\n", fmtBytes(state.GRAFP[:]))
	fmt.Printf("GRAFM:  %02X\n", state.GRAFM)
	fmt.Printf("COLPM:  %s\n", fmtBytes(state.COLPM[:]))
	fmt.Printf("COLPF:  %s\n", fmtBytes(state.COLPF[:]))
	fmt.Printf("COLBK:  %02X\n", state.COLBK)
	fmt.Printf("PRIOR:  %02X\n", state.PRIOR)
	fmt.Printf("VDELAY: %02X\n", state.VDELAY)
	fmt.Printf("GRACTL: %02X\n", state.GRACTL)
	return 0
}

func cmdANTICState(socket string) int {
	state, err := rpcClient(socket).ANTICState(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("DMACTL: %02X\n", state.DMACTL)
	fmt.Printf("CHACTL: %02X\n", state.CHACTL)
	fmt.Printf("DLIST:  %04X\n", state.DLIST)
	fmt.Printf("HSCROL: %02X\n", state.HSCROL)
	fmt.Printf("VSCROL: %02X\n", state.VSCROL)
	fmt.Printf("PMBASE: %02X\n", state.PMBASE)
	fmt.Printf("CHBASE: %02X\n", state.CHBASE)
	fmt.Printf("VCOUNT: %02X\n", state.VCOUNT)
	fmt.Printf("NMIEN:  %02X\n", state.NMIEN)
	fmt.Printf("YPOS:   %d\n", state.YPOS)
	return 0
}

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

func cmdPIAState(socket string) int {
	state, err := rpcClient(socket).PIAState(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("PACTL: %02X\n", state.PACTL)
	fmt.Printf("PBCTL: %02X\n", state.PBCTL)
	fmt.Printf("PORTA: %02X\n", state.PORTA)
	fmt.Printf("PORTB: %02X\n", state.PORTB)
	return 0
}

func cmdPOKEYState(socket string) int {
	state, err := rpcClient(socket).POKEYState(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("stereo_enabled: %d\n", state.StereoEnabled)
	fmt.Printf("AUDF1:          %s\n", fmtBytes(state.AUDF1[:]))
	fmt.Printf("AUDC1:          %s\n", fmtBytes(state.AUDC1[:]))
	fmt.Printf("AUDCTL1:        %02X\n", state.AUDCTL1)
	fmt.Printf("KBCODE:         %02X\n", state.KBCODE)
	fmt.Printf("IRQEN:          %02X\n", state.IRQEN)
	fmt.Printf("IRQST:          %02X\n", state.IRQST)
	fmt.Printf("SKSTAT:         %02X\n", state.SKSTAT)
	fmt.Printf("SKCTL:          %02X\n", state.SKCTL)
	if state.HasChip2 {
		fmt.Printf("AUDF2:          %s\n", fmtBytes(state.AUDF2[:]))
		fmt.Printf("AUDC2:          %s\n", fmtBytes(state.AUDC2[:]))
		fmt.Printf("AUDCTL2:        %02X\n", state.AUDCTL2)
	}
	return 0
}

func cmdStack(socket string) int {
	state, err := rpcClient(socket).Stack(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("S=%02X count=%d\n", state.S, len(state.Entries))
	for _, entry := range state.Entries {
		fmt.Printf("01%02X: %02X\n", entry.StackOff, entry.Value)
	}
	return 0
}

func printCPUState(cl *RpcClient) int {
	cpu, err := cl.CPUState(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Println(formatCPU(cpu))
	return 0
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

func cmdBBRK(socket string, args cliBBRKCmd) int {
	var payload []byte
	if args.Enabled != nil {
		enabled, err := parseBool(*args.Enabled)
		if err != nil {
			return fail(err)
		}
		if enabled {
			payload = []byte{1}
		} else {
			payload = []byte{0}
		}
	}
	data, err := rpcClient(socket).Call(context.Background(), CmdBBRK, payload)
	if err != nil {
		return fail(err)
	}
	if len(data) < 1 {
		return fail(errors.New("BBRK payload too short"))
	}
	if data[0] == 0 {
		fmt.Println("bbrk=off")
		return 0
	}
	fmt.Println("bbrk=on")
	return 0
}

func cmdBLine(socket string, args cliBLineCmd) int {
	var payload []byte
	if args.Scanline != nil {
		scanline, err := memory.ParseHex(*args.Scanline)
		if err != nil {
			return fail(err)
		}
		payload = make([]byte, 2)
		binary.LittleEndian.PutUint16(payload, scanline)
	}
	data, err := rpcClient(socket).Call(context.Background(), CmdBLine, payload)
	if err != nil {
		return fail(err)
	}
	if len(data) < 3 {
		return fail(errors.New("BLINE payload too short"))
	}
	scanline := binary.LittleEndian.Uint16(data[0:2])
	mode := blineModeName(data[2])
	fmt.Printf("scanline=%d mode=%s\n", scanline, mode)
	return 0
}

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
		line, interrupted, err := readTrainerLine(reader, sigCh)
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

func readTrainerLine(reader *bufio.Reader, sigCh <-chan os.Signal) (string, bool, error) {
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

func cmdSearch(socket string, args cliSearchCmd) int {
	start, err := memory.ParseHex(args.Start)
	if err != nil {
		return fail(err)
	}
	end, err := memory.ParseHex(args.End)
	if err != nil {
		return fail(err)
	}
	raw := strings.Join(args.Pattern, " ")
	var pattern []byte
	if args.ATASCII || args.SearchScreen {
		pattern, err = EncodeATASCIIText(raw)
		if err != nil {
			return fail(err)
		}
		if args.SearchScreen {
			for i, b := range pattern {
				pattern[i] = ATASCIIToScreen(b)
			}
		}
	} else {
		pattern, err = memory.ParseHexPayload(raw)
		if err != nil {
			return fail(err)
		}
	}
	if len(pattern) == 0 || len(pattern) > 0xFF {
		return fail(errors.New("Pattern length must be in range 1..255."))
	}
	payload := make([]byte, 6+len(pattern))
	payload[0] = searchModeBytes
	binary.LittleEndian.PutUint16(payload[1:3], start)
	binary.LittleEndian.PutUint16(payload[3:5], end)
	payload[5] = byte(len(pattern))
	copy(payload[6:], pattern)
	data, err := rpcClient(socket).Call(context.Background(), CmdSearch, payload)
	if err != nil {
		return fail(err)
	}
	if len(data) < 6 {
		return fail(errors.New("SEARCH payload too short"))
	}
	total := binary.LittleEndian.Uint32(data[0:4])
	returned := int(binary.LittleEndian.Uint16(data[4:6]))
	expected := 6 + returned*2
	if len(data) < expected {
		return fail(fmt.Errorf("SEARCH payload too short: got=%d expected=%d", len(data), expected))
	}
	fmt.Printf("matches=%d returned=%d\n", total, returned)
	offset := 6
	for i := 0; i < returned; i++ {
		fmt.Printf("%04X\n", binary.LittleEndian.Uint16(data[offset:offset+2]))
		offset += 2
	}
	return 0
}

func cmdSetReg(socket string, args cliSetRegCmd) int {
	target := setRegTargets[strings.ToLower(args.Target)]
	value, err := memory.ParseHex(args.Value)
	if err != nil {
		return fail(err)
	}
	payload := make([]byte, 3)
	payload[0] = target
	binary.LittleEndian.PutUint16(payload[1:3], value)
	if _, err := rpcClient(socket).Call(context.Background(), CmdSetReg, payload); err != nil {
		return fail(err)
	}
	return 0
}

func cmdStatus(socket string) int {
	st, err := rpcClient(socket).Status(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf(
		"paused=%s crashed=%s emu_ms=%d reset_ms=%d state_seq=%d\n",
		yesNo(st.Paused),
		yesNo(st.Crashed),
		st.EmuMS,
		st.ResetMS,
		st.StateSeq,
	)
	return 0
}

type emulatorCapability struct {
	ID   uint16
	Desc string
}

var emulatorCapabilities = []emulatorCapability{
	{0x0001, "SDL2 video backend (VIDEO_SDL2)"},
	{0x0002, "SDL1 video backend (VIDEO_SDL)"},
	{0x0003, "Sound support (SOUND)"},
	{0x0004, "Callback sound backend (SOUND_CALLBACK)"},
	{0x0005, "Audio recording (AUDIO_RECORDING)"},
	{0x0006, "Video recording (VIDEO_RECORDING)"},
	{0x0007, "Code breakpoints/history (MONITOR_BREAK)"},
	{0x0008, "User breakpoint table (MONITOR_BREAKPOINTS)"},
	{0x0009, "Readline monitor support (MONITOR_READLINE)"},
	{0x000A, "Disassembler label hints (MONITOR_HINTS)"},
	{0x000B, "UTF-8 monitor output (MONITOR_UTF8)"},
	{0x000C, "ANSI monitor output (MONITOR_ANSI)"},
	{0x000D, "Monitor assembler command (MONITOR_ASSEMBLER)"},
	{0x000E, "Monitor profiling/coverage (MONITOR_PROFILE)"},
	{0x000F, "Monitor TRACE command (MONITOR_TRACE)"},
	{0x0010, "NetSIO/FujiNet emulation (NETSIO)"},
	{0x0011, "IDE emulation (IDE)"},
	{0x0012, "R: device support (R_IO_DEVICE)"},
	{0x0013, "Black Box emulation (PBI_BB)"},
	{0x0014, "MIO emulation (PBI_MIO)"},
	{0x0015, "Prototype80 emulation (PBI_PROTO80)"},
	{0x0016, "1400XL/1450XLD emulation (PBI_XLD)"},
	{0x0017, "VoiceBox emulation (VOICEBOX)"},
	{0x0018, "AF80 card emulation (AF80)"},
	{0x0019, "BIT3 card emulation (BIT3)"},
	{0x001A, "XEP80 emulation (XEP80_EMULATION)"},
	{0x001B, "NTSC filter (NTSC_FILTER)"},
	{0x001C, "PAL blending (PAL_BLENDING)"},
	{0x001D, "Crash menu support (CRASH_MENU)"},
	{0x001E, "New cycle-exact core (NEW_CYCLE_EXACT)"},
	{0x001F, "libpng support (HAVE_LIBPNG)"},
	{0x0020, "zlib support (HAVE_LIBZ)"},
}

var setRegTargets = map[string]byte{
	"pc": 1,
	"a":  2,
	"x":  3,
	"y":  4,
	"s":  5,
	"n":  6,
	"v":  7,
	"d":  8,
	"i":  9,
	"z":  10,
	"c":  11,
}

const searchModeBytes byte = 1

func cmdBPList(socket string) int {
	list, err := rpcClient(socket).BPList(context.Background())
	if err != nil {
		return fail(err)
	}
	fmt.Printf("Enabled: %s\n", formatOnOffBadge(list.Enabled))
	if len(list.Clauses) == 0 {
		fmt.Println("No breakpoint clauses.")
		return 0
	}
	for i, clause := range list.Clauses {
		parts := make([]string, 0, len(clause))
		for _, cond := range clause {
			parts = append(parts, formatBPCondition(cond))
		}
		fmt.Printf("#%02d %s\n", i+1, strings.Join(parts, " && "))
	}
	return 0
}

func cmdBPAdd(socket string, args cliBPAddCmd) int {
	if len(args.Conditions) == 0 {
		return fail(errors.New("Specify at least one condition."))
	}
	conds := make([]BreakpointCondition, 0, len(args.Conditions))
	for _, expr := range args.Conditions {
		cond, err := parseBPCondition(expr)
		if err != nil {
			return fail(err)
		}
		conds = append(conds, cond)
	}
	idx, err := rpcClient(socket).BPAddClause(context.Background(), conds)
	if err != nil {
		return fail(err)
	}
	fmt.Printf("Added clause #%d\n", int(idx)+1)
	return 0
}

func cmdBPDelete(socket string, args cliBPDeleteCmd) int {
	if args.Index <= 0 {
		return fail(errors.New("Clause index must be >= 1."))
	}
	if err := rpcClient(socket).BPDeleteClause(context.Background(), uint16(args.Index-1)); err != nil {
		return fail(err)
	}
	return cmdBPList(socket)
}

func cmdBPClear(socket string) int {
	if err := rpcClient(socket).BPClear(context.Background()); err != nil {
		return fail(err)
	}
	return cmdBPList(socket)
}

func cmdBPSetEnabled(socket string, enabled bool) int {
	if _, err := rpcClient(socket).BPSetEnabled(context.Background(), enabled); err != nil {
		return fail(err)
	}
	return cmdBPList(socket)
}

func cmdEmulatorConfig(socket string) int {
	caps, err := rpcClient(socket).BuildFeatures(context.Background())
	if err != nil {
		return fail(err)
	}
	enabled := map[uint16]bool{}
	for _, id := range caps {
		enabled[id] = true
	}
	known := map[uint16]bool{}
	for _, cap := range emulatorCapabilities {
		known[cap.ID] = true
		fmt.Printf("%s %s\n", formatOnOffBadge(enabled[cap.ID]), cap.Desc)
	}
	for _, id := range caps {
		if known[id] {
			continue
		}
		fmt.Printf("%s Unknown capability 0x%04X\n", formatOnOffBadge(true), id)
	}
	return 0
}

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

func cmdReadMem(socket string, args cliReadMemCmd) int {
	addr, err := memory.ParseHex(args.Addr)
	if err != nil {
		return fail(err)
	}
	length, err := memory.ParseHex(args.Length)
	if err != nil {
		return fail(err)
	}
	data, err := rpcClient(socket).ReadMemoryChunked(context.Background(), addr, int(length))
	if err != nil {
		return fail(err)
	}
	cols := 0
	columnsProvided := args.Columns != nil
	if columnsProvided {
		cols = *args.Columns
	}
	return dumpMemory(
		addr,
		int(length),
		data,
		args.Raw,
		args.JSON,
		args.ATASCII,
		cols,
		columnsProvided,
		!args.NoHex,
		!args.NoASCII,
	)
}

func cmdWriteMem(socket string, args cliWriteMemCmd) int {
	addr, err := memory.ParseHex(args.Addr)
	if err != nil {
		return fail(err)
	}
	hasBytes := len(args.Bytes) > 0
	hasHex := args.Hex != nil
	hasText := args.Text != nil
	if btoi(hasBytes)+btoi(hasHex)+btoi(hasText) != 1 {
		return fail(errors.New("Specify exactly one payload: <bytes...>, --hex, or --text."))
	}
	if args.ATASCII && !hasText {
		return fail(errors.New("--atascii is only valid with --text."))
	}
	data, err := resolveWriteMemData(args, hasBytes, hasHex)
	if err != nil {
		return fail(err)
	}
	if len(data) == 0 {
		return fail(errors.New("No data to write."))
	}
	if len(data) > 0xFFFF {
		return fail(fmt.Errorf("Data too long: %d bytes (max 65535).", len(data)))
	}
	if args.Screen {
		data = toScreenCodes(data)
	}
	if err := rpcClient(socket).WriteMemory(context.Background(), addr, data); err != nil {
		return fail(err)
	}
	return 0
}

func resolveWriteMemData(args cliWriteMemCmd, hasBytes bool, hasHex bool) ([]byte, error) {
	if hasBytes {
		return memory.ParseHexValues(args.Bytes)
	}
	if hasHex {
		text := strings.TrimSpace(*args.Hex)
		if text == "-" {
			raw, err := io.ReadAll(os.Stdin)
			if err != nil {
				return nil, err
			}
			text = string(raw)
		}
		return memory.ParseHexPayload(text)
	}
	text := *args.Text
	if text == "-" {
		raw, err := io.ReadAll(os.Stdin)
		if err != nil {
			return nil, err
		}
		text = string(raw)
	}
	if args.ATASCII {
		return EncodeATASCIIText(text)
	}
	return []byte(text), nil
}

func toScreenCodes(data []byte) []byte {
	out := make([]byte, len(data))
	for i, b := range data {
		out[i] = ATASCIIToScreen(b)
	}
	return out
}

func fmtBytes(values []byte) string {
	if len(values) == 0 {
		return ""
	}
	parts := make([]string, 0, len(values))
	for _, v := range values {
		parts = append(parts, fmt.Sprintf("%02X", v))
	}
	return strings.Join(parts, " ")
}

func parseBool(value string) (bool, error) {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "1", "on", "true", "yes":
		return true, nil
	case "0", "off", "false", "no":
		return false, nil
	}
	return false, fmt.Errorf("Invalid boolean value: %s", value)
}

func blineModeName(mode byte) string {
	switch mode {
	case 0:
		return "disabled"
	case 1:
		return "break"
	case 2:
		return "blink"
	default:
		return fmt.Sprintf("mode%d", mode)
	}
}

func cmdDisasm(socket string, args cliDisasmCmd) int {
	addr, err := memory.ParseHex(args.Addr)
	if err != nil {
		return fail(err)
	}
	length, err := memory.ParseHex(args.Length)
	if err != nil {
		return fail(err)
	}
	data, err := rpcClient(socket).ReadMemoryChunked(context.Background(), addr, int(length))
	if err != nil {
		return fail(err)
	}
	for _, line := range disasm.Disasm(addr, data) {
		fmt.Println(line)
	}
	return 0
}

func btoi(v bool) int {
	if v {
		return 1
	}
	return 0
}

func cmdScreen(socket string, args cliScreenCmd) int {
	if args.List && args.Segment != nil {
		fmt.Fprintln(os.Stderr, "--list cannot be used with a segment number")
		return 1
	}
	cl := rpcClient(socket)
	ctx := context.Background()
	start, err := cl.ReadVector(ctx, DLPTRSAddr)
	if err != nil {
		return fail(err)
	}
	dump, err := cl.ReadDisplayList(ctx)
	if err != nil {
		return fail(err)
	}
	dmactl, err := cl.ReadByte(ctx, DMACTLAddr)
	if err != nil {
		return fail(err)
	}
	if dmactl&0x03 == 0 {
		if hw, hwErr := cl.ReadByte(ctx, DMACTLHWAddr); hwErr == nil {
			dmactl = hw
		}
	}
	dlist := dl.Decode(start, dump)
	segments := dlist.ScreenSegments(dmactl)
	if len(segments) == 0 {
		fmt.Fprintln(os.Stderr, "No screen segments found.")
		return 1
	}
	if args.List {
		for i, seg := range segments {
			length := seg.End - seg.Start
			last := (seg.End - 1) & 0xFFFF
			fmt.Printf("#%d %04X-%04X len=%04X antic=%d\n", i+1, seg.Start, last, length, seg.Mode)
		}
		return 0
	}
	mapper := dl.NewMemoryMapper(dlist, dmactl, 4096)
	if args.Segment == nil {
		if args.Columns == nil && !args.Raw && !args.JSON {
			rows := make([]memory.DumpRow, 0)
			for _, row := range mapper.RowRanges() {
				if row.Addr == nil || row.Length <= 0 {
					continue
				}
				chunk, err := cl.ReadMemory(ctx, *row.Addr, uint16(row.Length))
				if err != nil {
					return fail(err)
				}
				if len(chunk) == 0 {
					continue
				}
				rowCopy := make([]byte, len(chunk))
				copy(rowCopy, chunk)
				rows = append(rows, memory.DumpRow{
					Address: *row.Addr,
					Data:    rowCopy,
				})
			}
			if len(rows) > 0 {
				fmt.Println(memory.DumpHumanRows(rows, args.ATASCII, !args.NoHex, !args.NoASCII))
				return 0
			}
		}
		data := make([]byte, 0)
		for _, seg := range segments {
			chunk, err := cl.ReadMemoryChunked(ctx, uint16(seg.Start&0xFFFF), seg.End-seg.Start)
			if err != nil {
				return fail(err)
			}
			data = append(data, chunk...)
		}
		cols := 0
		columnsProvided := args.Columns != nil
		if columnsProvided {
			cols = *args.Columns
		}
		return dumpMemory(
			uint16(segments[0].Start&0xFFFF),
			len(data),
			data,
			args.Raw,
			args.JSON,
			args.ATASCII,
			cols,
			columnsProvided,
			!args.NoHex,
			!args.NoASCII,
		)
	}
	idx := *args.Segment - 1
	if idx < 0 || idx >= len(segments) {
		fmt.Fprintf(os.Stderr, "Segment out of range (1-%d)\n", len(segments))
		return 1
	}
	seg := segments[idx]
	length := seg.End - seg.Start
	data, err := cl.ReadMemoryChunked(ctx, uint16(seg.Start&0xFFFF), length)
	if err != nil {
		return fail(err)
	}
	if args.Columns == nil && !args.Raw && !args.JSON {
		rows := make([]memory.DumpRow, 0)
		for _, row := range mapper.RowRanges() {
			if row.Addr == nil || row.Length <= 0 {
				continue
			}
			addr := int(*row.Addr)
			if addr < seg.Start || addr >= seg.End {
				continue
			}
			rel := addr - seg.Start
			if rel < 0 || rel >= len(data) {
				continue
			}
			rowEnd := rel + row.Length
			if rowEnd > len(data) {
				rowEnd = len(data)
			}
			chunk := data[rel:rowEnd]
			if len(chunk) == 0 {
				continue
			}
			rowCopy := make([]byte, len(chunk))
			copy(rowCopy, chunk)
			rows = append(rows, memory.DumpRow{
				Address: uint16(addr & 0xFFFF),
				Data:    rowCopy,
			})
		}
		if len(rows) > 0 {
			fmt.Println(memory.DumpHumanRows(rows, args.ATASCII, !args.NoHex, !args.NoASCII))
			return 0
		}
	}
	cols := 0
	columnsProvided := args.Columns != nil
	if columnsProvided {
		cols = *args.Columns
	}
	if cols == 0 {
		if c := mapper.BytesPerLine(seg.Mode); c > 0 {
			cols = c
		}
	}
	return dumpMemory(
		uint16(seg.Start&0xFFFF),
		length,
		data,
		args.Raw,
		args.JSON,
		args.ATASCII,
		cols,
		columnsProvided,
		!args.NoHex,
		!args.NoASCII,
	)
}

func dumpMemory(address uint16, length int, data []byte, raw bool, asJSON bool, useATASCII bool, columns int, columnsProvided bool, showHex bool, showASCII bool) int {
	if columnsProvided && (raw || asJSON) {
		fmt.Fprintln(os.Stderr, "--columns is only valid for formatted output")
		return 1
	}
	if raw {
		out := memory.DumpRaw(data, useATASCII)
		if len(out) > 0 {
			_, _ = os.Stdout.Write(out)
		}
		return 0
	}
	if asJSON {
		text, err := memory.DumpJSON(address, data, useATASCII)
		if err != nil {
			return fail(err)
		}
		fmt.Println(text)
		return 0
	}
	fmt.Println(memory.DumpHuman(address, length, data, useATASCII, columns, showHex, showASCII))
	return 0
}

func expandPath(path string) (string, error) {
	if strings.HasPrefix(path, "~/") {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		path = filepath.Join(home, path[2:])
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	real, err := filepath.EvalSymlinks(abs)
	if err == nil {
		return real, nil
	}
	return abs, nil
}

func colorizedHelpPrinter(base kong.HelpPrinter) kong.HelpPrinter {
	return func(options kong.HelpOptions, ctx *kong.Context) error {
		out := ctx.Stdout
		var buf bytes.Buffer
		ctx.Stdout = &buf
		err := base(options, ctx)
		ctx.Stdout = out
		if err != nil {
			return err
		}
		text := buf.String()
		if !helpColorEnabled() {
			_, werr := io.WriteString(out, text)
			return werr
		}
		_, werr := io.WriteString(out, colorizeHelpText(text))
		return werr
	}
}

func helpColorEnabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("A800MON_HELP_COLOR"))) {
	case "always":
		return true
	case "never":
		return false
	}
	term := os.Getenv("TERM")
	return term != "" && term != "dumb"
}

func colorizeHelpText(text string) string {
	const (
		reset = "\x1b[0m"
		head  = "\x1b[1;36m"
		cmd   = "\x1b[1;33m"
		flag  = "\x1b[32m"
		dim   = "\x1b[2m"
	)
	lines := strings.Split(text, "\n")
	for i, line := range lines {
		trim := strings.TrimSpace(line)
		leading := len(line) - len(strings.TrimLeft(line, " "))
		if strings.HasPrefix(trim, "Usage:") ||
			trim == "Commands:" ||
			trim == "Arguments:" ||
			trim == "Flags:" {
			lines[i] = head + trim + reset
			continue
		}
		if strings.HasPrefix(trim, "Run \"") {
			lines[i] = dim + line + reset
			continue
		}
		if leading <= 6 && strings.HasPrefix(trim, "-") {
			lines[i] = colorizeHelpLeadingToken(line, flag, reset)
			continue
		}
		if leading == 2 && trim != "" && !strings.HasPrefix(trim, "-") &&
			(strings.Contains(trim, "  ") || strings.Contains(trim, "(")) {
			lines[i] = colorizeHelpLeadingToken(line, cmd, reset)
		}
	}
	return strings.Join(lines, "\n")
}

func colorizeHelpLeadingToken(line string, color string, reset string) string {
	indent := line[:len(line)-len(strings.TrimLeft(line, " "))]
	trim := strings.TrimSpace(line)
	sep := strings.Index(trim, "  ")
	if sep < 0 {
		return indent + color + trim + reset
	}
	return indent + color + trim[:sep] + reset + trim[sep:]
}

func fail(err error) int {
	fmt.Fprintln(os.Stderr, formatCliError(err))
	return 1
}

func formatCliError(err error) string {
	if err == nil {
		return ""
	}
	var commandErr CommandError
	if errors.As(err, &commandErr) {
		msg := strings.TrimSpace(string(commandErr.Data))
		if msg == "" {
			msg = err.Error()
		}
		return formatCliBadge(fmt.Sprintf("%d", commandErr.Status), msg)
	}
	return formatCliBadge("ERR", err.Error())
}

func formatCliBadge(code string, msg string) string {
	badge := " " + code + " "
	if cliColorEnabled() {
		return "\x1b[41;97;1m" + badge + "\x1b[0m " + msg
	}
	return "[" + code + "] " + msg
}

func cliColorEnabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("A800MON_COLOR"))) {
	case "always":
		return true
	case "never":
		return false
	}
	return helpColorEnabled()
}

func formatOnOffBadge(enabled bool) string {
	text := "OFF"
	if enabled {
		text = "ON "
	}
	badge := " " + text + " "
	if !cliColorEnabled() {
		return badge
	}
	if enabled {
		return "\x1b[42;30m" + badge + "\x1b[0m"
	}
	return "\x1b[41;97;1m" + badge + "\x1b[0m"
}

func yesNo(v bool) string {
	if v {
		return "yes"
	}
	return "no"
}
