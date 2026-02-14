package monitor

import (
	"sync"

	. "go800mon/a800mon"
	"go800mon/internal/displaylist"
)

type AppMode int

const (
	AppModeNormal AppMode = iota + 1
	AppModeDebug
	AppModeShutdown
)

type AppStateData struct {
	DList                displaylist.DisplayList
	CPU                  CPUState
	CPUDisasm            string
	MonitorFrameTimeMS   int
	Paused               bool
	EmuMS                uint64
	ResetMS              uint64
	Crashed              bool
	StateSeq             uint64
	LastRPCError         string
	ActiveMode           AppMode
	UIFrozen             bool
	UseATASCII           bool
	DisassemblyEnabled   bool
	DisassemblyAddr      *uint16
	DMACTL               byte
	History              []CpuHistoryEntry
	DisassemblyRows      []DisasmRow
	BreakpointsSupported bool
}

type DisasmRow struct {
	Addr           uint16
	Size           int
	RawText        string
	AsmText        string
	Mnemonic       string
	Operand        string
	Comment        string
	OperandAddrPos [2]int
	HasOperandAddr bool
	FlowTarget     *uint16
}

type ScreenRow struct {
	Addr uint16
	Data []byte
}

type WatcherRow struct {
	Addr      uint16
	Value     byte
	NextValue byte
	Comment   string
}

type BreakpointConditionRow struct {
	CondType byte
	Op       byte
	Addr     uint16
	Value    uint16
}

type BreakpointClauseRow struct {
	Conditions []BreakpointConditionRow
}

type StateStore struct {
	mu sync.RWMutex
	s  AppStateData
}

var store = newStateStore()

func newStateStore() *StateStore {
	return &StateStore{
		s: AppStateData{
			ActiveMode:         AppModeNormal,
			UseATASCII:         true,
			DisassemblyEnabled: true,
		},
	}
}

func State() AppStateData {
	store.mu.RLock()
	defer store.mu.RUnlock()
	return store.snapshotLocked()
}

func (s *StateStore) snapshotLocked() AppStateData {
	st := s.s
	if st.History != nil {
		h := make([]CpuHistoryEntry, len(st.History))
		copy(h, st.History)
		st.History = h
	}
	if st.DisassemblyRows != nil {
		d := make([]DisasmRow, len(st.DisassemblyRows))
		copy(d, st.DisassemblyRows)
		st.DisassemblyRows = d
	}
	return st
}

func (s *StateStore) setStatus(paused bool, emuMS, resetMS uint64, crashed bool, stateSeq uint64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.Paused = paused
	s.s.EmuMS = emuMS
	s.s.ResetMS = resetMS
	s.s.Crashed = crashed
	s.s.StateSeq = stateSeq
}

func (s *StateStore) setLastRPCError(text string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.LastRPCError = text
}

func (s *StateStore) setCPU(cpu CPUState, cpuDisasm string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.CPU = cpu
	s.s.CPUDisasm = cpuDisasm
}

func (s *StateStore) setDList(dl displaylist.DisplayList, dmactl byte) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.DList = dl
	s.s.DMACTL = dmactl
}

func (s *StateStore) setHistory(rows []CpuHistoryEntry) {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]CpuHistoryEntry, len(rows))
	copy(out, rows)
	s.s.History = out
}

func (s *StateStore) setDisassemblyRows(rows []DisasmRow) {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]DisasmRow, len(rows))
	copy(out, rows)
	s.s.DisassemblyRows = out
}

func (s *StateStore) setFrameTimeMS(ms int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.MonitorFrameTimeMS = ms
}

func (s *StateStore) setUseATASCII(enabled bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.UseATASCII = enabled
}

func (s *StateStore) setDisassemblyEnabled(enabled bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.DisassemblyEnabled = enabled
}

func (s *StateStore) setDisassemblyAddr(addr *uint16) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.DisassemblyAddr = addr
}

func (s *StateStore) setActiveMode(mode AppMode) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.ActiveMode = mode
}

func (s *StateStore) setUIFrozen(enabled bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.UIFrozen = enabled
}

func (s *StateStore) setBreakpointsSupported(enabled bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.BreakpointsSupported = enabled
}
