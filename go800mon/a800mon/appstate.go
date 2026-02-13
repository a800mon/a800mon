package a800mon

import (
	"sync"

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
	DListSelectedRegion  *int
	ActiveMode           AppMode
	UIFrozen             bool
	DisplayListInspect   bool
	UseATASCII           bool
	DisassemblyEnabled   bool
	DisassemblyAddr      *uint16
	InputFocus           bool
	InputTarget          string
	InputBuffer          string
	DMACTL               byte
	ScreenRows           []ScreenRow
	History              []CpuHistoryEntry
	DisassemblyRows      []DisasmRow
	Watchers             []WatcherRow
	WatcherPending       *WatcherRow
	WatcherSelected      *int
	BreakpointsEnabled   bool
	BreakpointsSupported bool
	Breakpoints          []BreakpointClauseRow
}

type DisasmRow struct {
	Addr           uint16
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
	if st.ScreenRows != nil {
		rows := make([]ScreenRow, len(st.ScreenRows))
		copy(rows, st.ScreenRows)
		st.ScreenRows = rows
	}
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
	if st.Watchers != nil {
		w := make([]WatcherRow, len(st.Watchers))
		copy(w, st.Watchers)
		st.Watchers = w
	}
	if st.Breakpoints != nil {
		clauses := make([]BreakpointClauseRow, len(st.Breakpoints))
		for i, clause := range st.Breakpoints {
			conds := make([]BreakpointConditionRow, len(clause.Conditions))
			copy(conds, clause.Conditions)
			clauses[i] = BreakpointClauseRow{Conditions: conds}
		}
		st.Breakpoints = clauses
	}
	if st.WatcherPending != nil {
		p := *st.WatcherPending
		st.WatcherPending = &p
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

func (s *StateStore) setScreenRows(rows []ScreenRow) {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]ScreenRow, len(rows))
	copy(out, rows)
	s.s.ScreenRows = out
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

func (s *StateStore) setDisplayListInspect(enabled bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.DisplayListInspect = enabled
	if !enabled {
		s.s.DListSelectedRegion = nil
	} else if s.s.DListSelectedRegion == nil {
		idx := 0
		s.s.DListSelectedRegion = &idx
	}
}

func (s *StateStore) setDListSelectedRegion(idx *int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.DListSelectedRegion = idx
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

func (s *StateStore) setInputFocus(enabled bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.InputFocus = enabled
}

func (s *StateStore) setInputTarget(target string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.InputTarget = target
}

func (s *StateStore) setInputBuffer(text string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.InputBuffer = text
}

func (s *StateStore) setWatchers(rows []WatcherRow) {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]WatcherRow, len(rows))
	copy(out, rows)
	s.s.Watchers = out
	if len(out) == 0 {
		s.s.WatcherSelected = nil
		return
	}
	if s.s.WatcherSelected == nil {
		return
	}
	idx := *s.s.WatcherSelected
	if idx < 0 {
		idx = 0
	}
	if idx >= len(out) {
		idx = len(out) - 1
	}
	s.s.WatcherSelected = &idx
}

func (s *StateStore) setWatcherPending(row *WatcherRow) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if row == nil {
		s.s.WatcherPending = nil
		return
	}
	v := *row
	s.s.WatcherPending = &v
}

func (s *StateStore) setWatcherSelected(idx *int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if idx == nil {
		s.s.WatcherSelected = nil
		return
	}
	v := *idx
	if len(s.s.Watchers) == 0 {
		s.s.WatcherSelected = nil
		return
	}
	if v < 0 {
		v = 0
	}
	if v >= len(s.s.Watchers) {
		v = len(s.s.Watchers) - 1
	}
	s.s.WatcherSelected = &v
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

func (s *StateStore) setBreakpoints(enabled bool, clauses []BreakpointClauseRow) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.BreakpointsEnabled = enabled
	out := make([]BreakpointClauseRow, len(clauses))
	for i, clause := range clauses {
		conds := make([]BreakpointConditionRow, len(clause.Conditions))
		copy(conds, clause.Conditions)
		out[i] = BreakpointClauseRow{Conditions: conds}
	}
	s.s.Breakpoints = out
}

func (s *StateStore) setBreakpointsSupported(enabled bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.s.BreakpointsSupported = enabled
}
