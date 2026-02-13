package a800mon

import dl "go800mon/internal/displaylist"
import irpc "go800mon/internal/rpc"

type DisplayList = dl.DisplayList
type DisplayListEntry = dl.Entry
type GTIAState = irpc.GTIAState
type ANTICState = irpc.ANTICState
type CartSlotState = irpc.CartSlotState
type CartState = irpc.CartState
type Breakpoint = irpc.BreakpointList
type JumpsState = irpc.JumpsState
type PIAState = irpc.PIAState
type POKEYState = irpc.POKEYState
type StackEntry = irpc.StackEntry
type StackState = irpc.StackState
