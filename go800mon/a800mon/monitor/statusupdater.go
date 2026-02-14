package monitor

import (
	"context"
	"time"

	. "go800mon/a800mon"
	"go800mon/internal/disasm"
)

type StatusUpdater struct {
	rpc             *RpcClient
	dispatcher      *ActionDispatcher
	pausedInterval  time.Duration
	runningInterval time.Duration
	errorInterval   time.Duration
	lastPoll        time.Time
	forceRefresh    bool
	capsSynced      bool
	lastCapsAttempt time.Time
}

func NewStatusUpdater(rpc *RpcClient, dispatcher *ActionDispatcher, pausedInterval, runningInterval time.Duration) *StatusUpdater {
	return &StatusUpdater{
		rpc:             rpc,
		dispatcher:      dispatcher,
		pausedInterval:  pausedInterval,
		runningInterval: runningInterval,
		errorInterval:   time.Second,
	}
}

func (s *StatusUpdater) RequestRefresh() {
	s.forceRefresh = true
}

func (s *StatusUpdater) Tick(ctx context.Context) (bool, error) {
	st := State()
	hadError := st.LastRPCError != ""
	interval := s.runningInterval
	if st.Paused {
		interval = s.pausedInterval
	}
	if st.LastRPCError != "" {
		interval = s.errorInterval
	}
	if !s.forceRefresh && !s.lastPoll.IsZero() && time.Since(s.lastPoll) < interval {
		return false, nil
	}
	forced := s.forceRefresh
	s.lastPoll = time.Now()
	s.forceRefresh = false

	status, err := s.rpc.Status(ctx)
	if err != nil {
		s.syncRPCError()
		return true, nil
	}
	changed := st.Paused != status.Paused ||
		st.EmuMS != status.EmuMS ||
		st.ResetMS != status.ResetMS ||
		st.Crashed != status.Crashed ||
		st.StateSeq != status.StateSeq
	if changed {
		_ = s.dispatcher.Dispatch(ActionSetStatus, status)
	}
	if changed || forced {
		s.updateCPU(ctx)
	}
	needCaps := hadError || !s.capsSynced
	if needCaps {
		now := time.Now()
		if hadError || s.lastCapsAttempt.IsZero() || now.Sub(s.lastCapsAttempt) >= time.Second {
			s.lastCapsAttempt = now
			if s.updateCapabilities(ctx) {
				s.capsSynced = true
			}
		}
	}
	s.syncRPCError()
	return true, nil
}

func (s *StatusUpdater) updateCPU(ctx context.Context) {
	cpu, err := s.rpc.CPUState(ctx)
	if err != nil {
		return
	}
	cpuDisasm := ""
	if code, err := s.rpc.ReadMemory(ctx, cpu.PC, 3); err == nil {
		cpuDisasm = disasm.DisasmOne(cpu.PC, code)
	}
	_ = s.dispatcher.Dispatch(
		ActionSetCPU,
		CPUUpdate{CPU: cpu, Disasm: cpuDisasm},
	)
}

func (s *StatusUpdater) syncRPCError() {
	err := s.rpc.LastError()
	text := ""
	if err != nil {
		text = err.Error()
	}
	if State().LastRPCError != text {
		_ = s.dispatcher.Dispatch(ActionSetLastRPCError, text)
	}
}

func (s *StatusUpdater) updateCapabilities(ctx context.Context) bool {
	caps, err := s.rpc.Config(ctx)
	if err != nil {
		return false
	}
	supported := false
	for _, id := range caps {
		if id == CapMonitorBreakpoints {
			supported = true
			break
		}
	}
	if State().BreakpointsSupported != supported {
		_ = s.dispatcher.Dispatch(ActionSetBreakpointsSupported, supported)
	}
	return true
}
