package cli

import "regexp"

type cliArgs struct {
	Socket   string            `short:"s" default:"/tmp/atari.sock" help:"Path to Atari800 monitor socket."`
	Monitor  cliEmptyCmd       `cmd:"" help:"Run the curses monitor UI."`
	Run      cliRunCmd         `cmd:"" help:"Run a file via RPC."`
	Debug    cliDebugCmd       `cmd:"" aliases:"d" help:"Debugger commands."`
	Emulator cliEmulatorCmd    `cmd:"" aliases:"e" help:"Emulator control commands."`
	BP       cliBreakpointsCmd `cmd:"" name:"bp" help:"Manage user breakpoints."`
	Dump     cliDumpCmd        `cmd:"" help:"Dump hardware/display state."`
	CPU      cliCpuCmd         `cmd:"" help:"CPU commands."`
	Mem      cliMemCmd         `cmd:"" help:"Memory commands."`
	RPC      cliRpcCmd         `cmd:"" name:"rpc" help:"RPC transport commands."`
	Cart     cliCartCmd        `cmd:"" name:"cart" help:"Cartridge commands."`
	Tape     cliTapeCmd        `cmd:"" name:"tape" help:"Tape commands."`
	Disk     cliDiskCmd        `cmd:"" name:"disk" help:"Disk commands."`
	Screen   cliScreenCmd      `cmd:"" help:"Dump screen memory segments."`
	Trainer  cliTrainerCmd     `cmd:"" name:"trainer" help:"Interactive value trainer."`
}

type cliEmptyCmd struct{}

type cliRunCmd struct {
	Path string `arg:"" help:"Path to file."`
}

type cliHistoryCmd struct {
	Count int `short:"n" name:"count" default:"-1" help:"Limit output to last N entries."`
}

type cliDebugCmd struct {
	Shell   cliEmptyCmd   `cmd:"" default:"1" aliases:"s" help:"Interactive debugger session."`
	Jumps   cliEmptyCmd   `cmd:"" aliases:"j" help:"Show jump history ring."`
	History cliHistoryCmd `cmd:"" aliases:"h" help:"Show CPU execution history."`
}

type cliEmulatorRebootCmd struct {
	Cold bool `name:"cold" xor:"mode" help:"Cold start."`
	Warm bool `name:"warm" xor:"mode" help:"Warm start (default)."`
}

type cliEmulatorCmd struct {
	Reboot   cliEmulatorRebootCmd `cmd:"" help:"Reboot emulation."`
	Status   cliEmptyCmd          `cmd:"" default:"1" help:"Get status."`
	Stop     cliEmptyCmd          `cmd:"" help:"Stop emulator."`
	Restart  cliEmptyCmd          `cmd:"" help:"Restart emulator."`
	Features cliEmptyCmd          `cmd:"" help:"Show emulator capabilities."`
}

type cliBreakpointsCmd struct {
	LS       cliEmptyCmd    `cmd:"" default:"1" name:"ls" help:"List user breakpoint clauses."`
	Add      cliBPAddCmd    `cmd:"" help:"Add one breakpoint clause (AND)."`
	Del      cliBPDeleteCmd `cmd:"" name:"del" help:"Delete clause by index (1-based)."`
	Clear    cliEmptyCmd    `cmd:"" help:"Clear all breakpoint clauses."`
	On       cliEmptyCmd    `cmd:"" name:"on" help:"Enable all user breakpoints."`
	Off      cliEmptyCmd    `cmd:"" name:"off" help:"Disable all user breakpoints."`
	Scanline cliBLineCmd    `cmd:"" name:"scanline" help:"Query/set scanline break value."`
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

type cliMemCmd struct {
	Read   cliReadMemCmd  `cmd:"" aliases:"r" help:"Read memory."`
	Write  cliWriteMemCmd `cmd:"" aliases:"w" help:"Write memory."`
	Search cliSearchCmd   `cmd:"" aliases:"s" help:"Search memory for a pattern."`
	Disasm cliDisasmCmd   `cmd:"" aliases:"d" help:"Disassemble 6502 memory."`
}

type cliSearchCmd struct {
	ATASCII      bool     `short:"a" name:"atascii" help:"Convert input text to ATASCII bytes before search."`
	SearchScreen bool     `name:"screen" help:"Convert input text to screen-codes before search."`
	Start        string   `arg:"" help:"Start address (hex: 0xNNNN, $NNNN, NNNN)."`
	End          string   `arg:"" help:"End address (hex: 0xNNNN, $NNNN, NNNN)."`
	Pattern      []string `arg:"" help:"Hex bytes by default; text when --atascii and/or --screen is used."`
}

type cliCpuCmd struct {
	Get  cliEmptyCmd  `cmd:"" default:"1" help:"Show CPU state."`
	Set  cliSetRegCmd `cmd:"" help:"Set CPU register or flag."`
	BBRK cliBBRKCmd   `cmd:"" name:"bbrk" help:"Query/set break-on-BRK mode."`
}

type cliDumpCmd struct {
	DList cliDListCmd `cmd:"" name:"dlist" help:"Dump display list."`
	GTIA  cliEmptyCmd `cmd:"" name:"gtia" help:"Show GTIA register state."`
	ANTIC cliEmptyCmd `cmd:"" name:"antic" help:"Show ANTIC register state."`
	PIA   cliEmptyCmd `cmd:"" name:"pia" help:"Show PIA register state."`
	POKEY cliEmptyCmd `cmd:"" name:"pokey" help:"Show POKEY register state."`
}

type cliRpcCmd struct {
	Ping cliEmptyCmd `cmd:"" help:"Ping RPC server."`
}

type cliCartCmd struct {
	Status cliEmptyCmd `cmd:"" default:"1" help:"Show cartridge state."`
	Remove cliEmptyCmd `cmd:"" help:"Remove cartridge."`
}

type cliTapeCmd struct {
	Remove cliEmptyCmd `cmd:"" help:"Remove cassette."`
}

type cliDiskCmd struct {
	Remove cliDiskRemoveCmd `cmd:"" help:"Remove disk(s)."`
}

type cliDiskRemoveCmd struct {
	Number *int `arg:"" optional:"" help:"Optional disk number."`
	All    bool `name:"all" help:"Remove all disks."`
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

var cliPathAliasPattern = regexp.MustCompile(`\s*\([^)]*\)`)

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
