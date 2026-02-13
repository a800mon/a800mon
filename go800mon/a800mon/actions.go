package a800mon

import "context"

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
	ActionSetInputFocus
	ActionSetInputTarget
	ActionSetInputBuffer
	ActionQuit
)

type StopLoop struct{}

func (s StopLoop) Error() string { return "stop loop" }

type ActionDispatcher struct {
	rpc      *RpcClient
	rpcQueue []Command
	afterRPC func()
	stopLoop bool
}

func NewActionDispatcher(rpc *RpcClient) *ActionDispatcher {
	return &ActionDispatcher{rpc: rpc}
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
	if d.afterRPC != nil {
		d.afterRPC()
	}
	return false, nil
}
func (d *ActionDispatcher) HandleInput(ch int) bool { return false }
func (d *ActionDispatcher) Render(force bool)       {}

func (d *ActionDispatcher) SetAfterRPC(cb func()) {
	d.afterRPC = cb
}

func (d *ActionDispatcher) enqueue(cmd Command) {
	d.rpcQueue = append(d.rpcQueue, cmd)
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
	case ActionSetInputFocus:
		v := false
		if b, ok := value.(bool); ok {
			v = b
		}
		store.setInputFocus(v)
	case ActionSetInputTarget:
		if text, ok := value.(string); ok {
			store.setInputTarget(text)
		} else {
			store.setInputTarget("")
		}
	case ActionSetInputBuffer:
		if text, ok := value.(string); ok {
			store.setInputBuffer(text)
		}
	case ActionQuit:
		d.stopLoop = true
	}
	return nil
}

func (d *ActionDispatcher) updateStatus(status Status) {
	store.setStatus(status.Paused, status.EmuMS, status.ResetMS, status.Crashed, status.StateSeq)
}

func (d *ActionDispatcher) updateLastRPCError(text string) {
	store.setLastRPCError(text)
}

func (d *ActionDispatcher) updateCPU(cpu CPUState, dis string) {
	store.setCPU(cpu, dis)
}

func (d *ActionDispatcher) updateBreakpointsSupported(enabled bool) {
	store.setBreakpointsSupported(enabled)
}
