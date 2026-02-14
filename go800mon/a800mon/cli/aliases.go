package cli

import mon "go800mon/a800mon"

type RpcClient = mon.RpcClient
type Command = mon.Command
type CommandError = mon.CommandError
type StackState = mon.StackState
type Trainer = mon.Trainer

const (
	CmdPing            = mon.CmdPing
	CmdRun             = mon.CmdRun
	CmdPause           = mon.CmdPause
	CmdContinue        = mon.CmdContinue
	CmdStep            = mon.CmdStep
	CmdStepVBlank      = mon.CmdStepVBlank
	CmdRunUntilReturn  = mon.CmdRunUntilReturn
	CmdColdstart       = mon.CmdColdstart
	CmdWarmstart       = mon.CmdWarmstart
	CmdStopEmulator    = mon.CmdStopEmulator
	CmdRestartEmulator = mon.CmdRestartEmulator
	CmdRemoveCartrige  = mon.CmdRemoveCartrige
	CmdRemoveTape      = mon.CmdRemoveTape
	CmdRemoveDisks     = mon.CmdRemoveDisks
	CmdSearch          = mon.CmdSearch
	CmdSetReg          = mon.CmdSetReg
	CmdBBRK            = mon.CmdBBRK
	CmdBLine           = mon.CmdBLine

	DMACTLAddr   = mon.DMACTLAddr
	DMACTLHWAddr = mon.DMACTLHWAddr
	DLPTRSAddr   = mon.DLPTRSAddr
)

var (
	RunMonitor         = mon.RunMonitor
	NewRpcClient       = mon.NewRpcClient
	NewSocketTransport = mon.NewSocketTransport
	NewTrainer         = mon.NewTrainer
	ParseBPClauses     = mon.ParseBPClauses
	FormatBPCondition  = mon.FormatBPCondition
	EncodeATASCIIText  = mon.EncodeATASCIIText
	ATASCIIToScreen    = mon.ATASCIIToScreen
	DecodeDisplayList  = mon.DecodeDisplayList
)

func formatCPU(cpu mon.CPUState) string {
	return mon.FormatCPU(cpu)
}
