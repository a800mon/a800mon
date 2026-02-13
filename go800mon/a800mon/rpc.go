package a800mon

import (
	"context"

	irpc "go800mon/internal/rpc"
)

type RpcClient struct {
	inner *irpc.Client
}

type Command = irpc.Command

type Status = irpc.Status
type CPUState = irpc.CPUState
type CpuHistoryEntry = irpc.HistoryEntry
type BreakpointCondition = irpc.BreakpointCondition
type BreakpointList = irpc.BreakpointList
type CommandError = irpc.CommandError

const (
	CmdPing            = irpc.CmdPing
	CmdDListAddr       = irpc.CmdDlistAddr
	CmdDListDump       = irpc.CmdDlistDump
	CmdMemRead         = irpc.CmdMemRead
	CmdMemReadV        = irpc.CmdMemReadV
	CmdCPUState        = irpc.CmdCPUState
	CmdPause           = irpc.CmdPause
	CmdContinue        = irpc.CmdContinue
	CmdStep            = irpc.CmdStep
	CmdStepVBlank      = irpc.CmdStepVBlank
	CmdStatus          = irpc.CmdStatus
	CmdRun             = irpc.CmdRun
	CmdColdstart       = irpc.CmdColdstart
	CmdWarmstart       = irpc.CmdWarmstart
	CmdRemoveCartrige  = irpc.CmdRemoveCartrige
	CmdStopEmulator    = irpc.CmdStopEmulator
	CmdRestartEmulator = irpc.CmdRestartEmulator
	CmdRemoveTape      = irpc.CmdRemoveTape
	CmdRemoveDisks     = irpc.CmdRemoveDisks
	CmdHistory         = irpc.CmdHistory
	CmdBuiltinMonitor  = irpc.CmdBuiltinMonitor
	CmdWriteMemory     = irpc.CmdWriteMemory
	CmdBPClear         = irpc.CmdBPClear
	CmdBPAddClause     = irpc.CmdBPAddClause
	CmdBPDeleteClause  = irpc.CmdBPDeleteClause
	CmdBPSetEnabled    = irpc.CmdBPSetEnabled
	CmdBPList          = irpc.CmdBPList
	CmdBuildFeatures   = irpc.CmdBuildFeatures
	CmdConfig          = irpc.CmdConfig
	CmdGTIAState       = irpc.CmdGTIAState
	CmdANTICState      = irpc.CmdANTICState
	CmdCartState       = irpc.CmdCartState
	CmdJumps           = irpc.CmdJumps
	CmdPIAState        = irpc.CmdPIAState
	CmdPOKEYState      = irpc.CmdPOKEYState
	CmdStack           = irpc.CmdStack
	CmdStepOver        = irpc.CmdStepOver
	CmdRunUntilReturn  = irpc.CmdRunUntilReturn
	CmdBBRK            = irpc.CmdBBRK
	CmdBLine           = irpc.CmdBLine
	CmdSearch          = irpc.CmdSearch
	CmdSetReg          = irpc.CmdSetReg
)

func NewRpcClient(transport *SocketTransport) *RpcClient {
	return &RpcClient{inner: irpc.New(transport.Path)}
}

func (r *RpcClient) LastError() error {
	return r.inner.LastError()
}

func (r *RpcClient) Close() {
	r.inner.Close()
}

func (r *RpcClient) Call(ctx context.Context, command Command, payload []byte) ([]byte, error) {
	return r.inner.Call(ctx, command, payload)
}

func (r *RpcClient) ReadVector(ctx context.Context, addr uint16) (uint16, error) {
	return r.inner.ReadVector(ctx, addr)
}

func (r *RpcClient) ReadByte(ctx context.Context, addr uint16) (byte, error) {
	return r.inner.ReadByte(ctx, addr)
}

func (r *RpcClient) ReadMemory(ctx context.Context, addr uint16, length uint16) ([]byte, error) {
	return r.inner.ReadMemory(ctx, addr, length)
}

func (r *RpcClient) ReadMemoryChunked(ctx context.Context, addr uint16, length int) ([]byte, error) {
	return r.inner.ReadMemoryChunked(ctx, addr, length, 0x400)
}

func (r *RpcClient) WriteMemory(ctx context.Context, addr uint16, data []byte) error {
	return r.inner.WriteMemory(ctx, addr, data)
}

func (r *RpcClient) ReadDisplayList(ctx context.Context) ([]byte, error) {
	return r.inner.ReadDisplayList(ctx)
}

func (r *RpcClient) ReadDisplayListAt(ctx context.Context, startAddr uint16) ([]byte, error) {
	return r.inner.ReadDisplayListAt(ctx, startAddr)
}

func (r *RpcClient) Status(ctx context.Context) (Status, error) {
	return r.inner.Status(ctx)
}

func (r *RpcClient) CPUState(ctx context.Context) (CPUState, error) {
	return r.inner.CPUState(ctx)
}

func (r *RpcClient) History(ctx context.Context) ([]CpuHistoryEntry, error) {
	return r.inner.History(ctx)
}

func (r *RpcClient) GTIAState(ctx context.Context) (GTIAState, error) {
	return r.inner.GTIAState(ctx)
}

func (r *RpcClient) ANTICState(ctx context.Context) (ANTICState, error) {
	return r.inner.ANTICState(ctx)
}

func (r *RpcClient) CartrigeState(ctx context.Context) (CartState, error) {
	return r.inner.CartrigeState(ctx)
}

func (r *RpcClient) Jumps(ctx context.Context) (JumpsState, error) {
	return r.inner.Jumps(ctx)
}

func (r *RpcClient) PIAState(ctx context.Context) (PIAState, error) {
	return r.inner.PIAState(ctx)
}

func (r *RpcClient) POKEYState(ctx context.Context) (POKEYState, error) {
	return r.inner.POKEYState(ctx)
}

func (r *RpcClient) Stack(ctx context.Context) (StackState, error) {
	return r.inner.Stack(ctx)
}

func (r *RpcClient) BuildFeatures(ctx context.Context) ([]uint16, error) {
	return r.inner.BuildFeatures(ctx)
}

func (r *RpcClient) Config(ctx context.Context) ([]uint16, error) {
	return r.BuildFeatures(ctx)
}

func (r *RpcClient) BPClear(ctx context.Context) error {
	return r.inner.BPClear(ctx)
}

func (r *RpcClient) BPAddClause(ctx context.Context, conditions []BreakpointCondition) (uint16, error) {
	return r.inner.BPAddClause(ctx, conditions)
}

func (r *RpcClient) BPDeleteClause(ctx context.Context, clauseIndex uint16) error {
	return r.inner.BPDeleteClause(ctx, clauseIndex)
}

func (r *RpcClient) BPSetEnabled(ctx context.Context, enabled bool) (bool, error) {
	return r.inner.BPSetEnabled(ctx, enabled)
}

func (r *RpcClient) BPList(ctx context.Context) (BreakpointList, error) {
	return r.inner.BPList(ctx)
}
