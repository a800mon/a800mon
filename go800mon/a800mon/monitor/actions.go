package monitor

import (
	"context"

	. "go800mon/a800mon"
	"go800mon/internal/displaylist"
)

type Action int

const (
	ActionStep Action = iota + 1
	ActionStepVBlank
	ActionStepOver
	ActionPause
	ActionContinue
	ActionSyncMode
	ActionEnterShutdown
	ActionExitShutdown
	ActionColdStart
	ActionWarmStart
	ActionTerminate
	ActionToggleFreeze
	ActionSetATASCII
	ActionSetDisassembly
	ActionSetDisassemblyAddr
	ActionSetBreakpointsSupported
	ActionSetStatus
	ActionSetLastRPCError
	ActionSetCPU
	ActionSetHistory
	ActionSetDisassemblyRows
	ActionSetDList
	ActionSetDMACTL
	ActionSetFrameTimeMS
	ActionSetInputFocus
	ActionQuit
)

type CPUUpdate struct {
	CPU    CPUState
	Disasm string
}

type DListUpdate struct {
	DList  displaylist.DisplayList
	DMACTL byte
}

type StopLoop struct{}

func (s StopLoop) Error() string { return "stop loop" }

type ActionDispatcher struct {
	rpc           *RpcClient
	rpcQueue      []Command
	rpcFlushed    bool
	stopLoop      bool
	setInputFocus func(func(int) bool)
}

func NewActionDispatcher(rpc *RpcClient) *ActionDispatcher {
	return &ActionDispatcher{
		rpc:           rpc,
		setInputFocus: func(func(int) bool) {},
	}
}

func (d *ActionDispatcher) Update(ctx context.Context) (bool, error) {
	if d.stopLoop {
		return false, StopLoop{}
	}
	if len(d.rpcQueue) == 0 {
		return false, nil
	}
	queue := d.rpcQueue
	d.rpcQueue = nil
	for _, cmd := range queue {
		_, _ = d.rpc.Call(ctx, cmd, nil)
	}
	d.rpcFlushed = true
	return true, nil
}
func (d *ActionDispatcher) HandleInput(ch int) bool { return false }

func (d *ActionDispatcher) TakeRPCFlushed() bool {
	flushed := d.rpcFlushed
	d.rpcFlushed = false
	return flushed
}

func (d *ActionDispatcher) enqueue(cmd Command) {
	d.rpcQueue = append(d.rpcQueue, cmd)
}

func (d *ActionDispatcher) SetInputFocusHandler(callback func(func(int) bool)) {
	if callback == nil {
		d.setInputFocus = func(func(int) bool) {}
		return
	}
	d.setInputFocus = callback
}

func (d *ActionDispatcher) Dispatch(action Action, value any) error {
	st := State()
	switch action {
	case ActionStep:
		d.enqueue(CmdStep)
	case ActionStepVBlank:
		d.enqueue(CmdStepVBlank)
	case ActionStepOver:
		d.enqueue(CmdStepOver)
	case ActionPause:
		d.enqueue(CmdPause)
		store.setActiveMode(AppModeDebug)
	case ActionContinue:
		d.enqueue(CmdContinue)
		store.setActiveMode(AppModeNormal)
	case ActionSyncMode:
		if st.ActiveMode == AppModeDebug || st.ActiveMode == AppModeNormal {
			if st.Paused {
				store.setActiveMode(AppModeDebug)
			} else {
				store.setActiveMode(AppModeNormal)
			}
		}
	case ActionEnterShutdown:
		store.setActiveMode(AppModeShutdown)
	case ActionExitShutdown:
		if st.Paused {
			store.setActiveMode(AppModeDebug)
		} else {
			store.setActiveMode(AppModeNormal)
		}
	case ActionColdStart:
		d.enqueue(CmdColdstart)
		return d.Dispatch(ActionExitShutdown, nil)
	case ActionWarmStart:
		d.enqueue(CmdWarmstart)
		return d.Dispatch(ActionExitShutdown, nil)
	case ActionTerminate:
		d.enqueue(CmdStopEmulator)
		return d.Dispatch(ActionExitShutdown, nil)
	case ActionToggleFreeze:
		store.setUIFrozen(!st.UIFrozen)
	case ActionSetATASCII:
		v := false
		if b, ok := value.(bool); ok {
			v = b
		}
		store.setUseATASCII(v)
	case ActionSetDisassembly:
		v := false
		if b, ok := value.(bool); ok {
			v = b
		}
		store.setDisassemblyEnabled(v)
	case ActionSetDisassemblyAddr:
		if v, ok := value.(uint16); ok {
			store.setDisassemblyAddr(&v)
		}
	case ActionSetBreakpointsSupported:
		v := false
		if b, ok := value.(bool); ok {
			v = b
		}
		store.setBreakpointsSupported(v)
	case ActionSetStatus:
		if status, ok := value.(Status); ok {
			store.setStatus(
				status.Paused,
				status.EmuMS,
				status.ResetMS,
				status.Crashed,
				status.StateSeq,
			)
		}
	case ActionSetLastRPCError:
		if text, ok := value.(string); ok {
			store.setLastRPCError(text)
		} else {
			store.setLastRPCError("")
		}
	case ActionSetCPU:
		if update, ok := value.(CPUUpdate); ok {
			store.setCPU(update.CPU, update.Disasm)
		}
	case ActionSetHistory:
		if rows, ok := value.([]CpuHistoryEntry); ok {
			store.setHistory(rows)
		}
	case ActionSetDisassemblyRows:
		if rows, ok := value.([]DisasmRow); ok {
			store.setDisassemblyRows(rows)
		}
	case ActionSetDList:
		if update, ok := value.(DListUpdate); ok {
			store.setDList(update.DList, update.DMACTL)
		}
	case ActionSetDMACTL:
		if dmactl, ok := value.(byte); ok {
			store.setDList(st.DList, dmactl)
		}
	case ActionSetFrameTimeMS:
		if ms, ok := value.(int); ok {
			store.setFrameTimeMS(ms)
		}
	case ActionSetInputFocus:
		if value == nil {
			d.setInputFocus(nil)
			return nil
		}
		if handler, ok := value.(func(int) bool); ok {
			d.setInputFocus(handler)
		}
	case ActionQuit:
		d.stopLoop = true
	}
	return nil
}
