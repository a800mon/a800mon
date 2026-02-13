package a800mon

import (
	"context"
	"time"
)

const capMonitorBreakpoints uint16 = 0x0008

type AppModeUpdater struct {
	dispatcher *ActionDispatcher
	lastPaused *bool
}

func NewAppModeUpdater(dispatcher *ActionDispatcher) *AppModeUpdater {
	return &AppModeUpdater{dispatcher: dispatcher}
}

func (a *AppModeUpdater) Update(ctx context.Context) (bool, error) {
	st := State()
	if a.lastPaused == nil {
		v := st.Paused
		a.lastPaused = &v
		_ = a.dispatcher.Dispatch(ActionSyncMode, nil)
		return true, nil
	}
	if st.Paused != *a.lastPaused {
		v := st.Paused
		a.lastPaused = &v
		_ = a.dispatcher.Dispatch(ActionSyncMode, nil)
		return true, nil
	}
	return false, nil
}

func (a *AppModeUpdater) HandleInput(ch int) bool              { return false }
func (a *AppModeUpdater) PostRender(ctx context.Context) error { return nil }

type BreakpointsWindowUpdater struct {
	app         *App
	screen      *Screen
	window      *Window
	lastVisible bool
}

func NewBreakpointsWindowUpdater(app *App, screen *Screen, window *Window) *BreakpointsWindowUpdater {
	return &BreakpointsWindowUpdater{
		app:         app,
		screen:      screen,
		window:      window,
		lastVisible: window.Visible(),
	}
}

func (u *BreakpointsWindowUpdater) Update(ctx context.Context) (bool, error) {
	visible := State().BreakpointsSupported
	if visible == u.lastVisible {
		return false, nil
	}
	u.lastVisible = visible
	if !visible && u.screen.Focused() == u.window {
		u.screen.Focus(nil)
	}
	u.window.SetVisible(visible)
	u.app.RebuildScreen()
	return true, nil
}

func (u *BreakpointsWindowUpdater) HandleInput(ch int) bool              { return false }
func (u *BreakpointsWindowUpdater) PostRender(ctx context.Context) error { return nil }

func RunMonitor(ctx context.Context, socketPath string) error {
	screen := NewScreen(nil)
	screen.Initialize()
	defer screen.End()

	rpc := NewRpcClient(NewSocketTransport(socketPath))
	defer rpc.Close()
	dispatcher := NewActionDispatcher(rpc)
	supportsBreakpoints := false
	if caps, err := rpc.Config(ctx); err == nil {
		for _, id := range caps {
			if id == capMonitorBreakpoints {
				supportsBreakpoints = true
				break
			}
		}
	}
	dispatcher.updateBreakpointsSupported(supportsBreakpoints)

	wcpu := NewWindow("CPU State", true)
	wdlist := NewGridWindow("DisplayList", true)
	wwatch := NewGridWindow("Watchers", true)
	wwatch.SetGridColumnGap(0)
	wscreen := NewWindow("Screen Buffer", true)
	wscreen.AddTag("ATASCII", "atascii", true)
	wscreen.AddTag("ASCII", "ascii", false)
	wdisasm := NewWindow("Disassembler", true)
	wdisasm.AddTag("FOLLOW", "follow", true)
	whistory := NewGridWindow("History", true)
	whistory.SetGridColumnGap(0)
	wbreakpoints := NewGridWindow("Breakpoints", true)
	wbreakpoints.SetGridColumnGap(0)
	wbreakpoints.AddTag("ENABLED", "bp_enabled", false)
	top := NewWindow("", false)
	bottom := NewWindow("", false)
	screen.SetFocusOrder(wdlist.Window, wwatch.Window, wscreen, wdisasm, whistory.Window, wbreakpoints.Window)

	statusUpdater := NewStatusUpdater(rpc, dispatcher, 200*time.Millisecond, 50*time.Millisecond)
	dispatcher.SetAfterRPC(statusUpdater.RequestRefresh)

	screenInspector := NewScreenBufferInspector(rpc, wscreen)
	disassemblyView := NewDisassemblyViewer(rpc, wdisasm)
	watchersView := NewWatchersViewer(rpc, wwatch)
	breakpointsView := NewBreakpointsViewer(rpc, wbreakpoints)
	historyView := NewHistoryViewer(rpc, whistory, true)
	displayList := NewDisplayListViewer(rpc, wdlist)
	cpu := NewCpuStateViewer(wcpu)
	topbar := NewTopBar(top)
	appmodeUpdater := NewAppModeUpdater(dispatcher)
	shortcutbar := NewShortcutBar(bottom)
	wdisasm.SetVisible(State().DisassemblyEnabled)
	wbreakpoints.SetVisible(State().BreakpointsSupported)

	layout := func(scr *Screen) {
		w, h := scr.Size()
		wcpu.Reshape(0, h-5, w, 3)
		leftTotalH := wcpu.Y() - 3
		if leftTotalH < 2 {
			leftTotalH = 2
		}
		dlistH := leftTotalH / 2
		if dlistH < 1 {
			dlistH = 1
		}
		watchH := leftTotalH - dlistH
		if watchH < 1 {
			watchH = 1
		}
		wdlist.Reshape(0, 2, 40, dlistH)
		wwatch.Reshape(0, 2+dlistH, 40, watchH)
		rightX := wdlist.X() + wdlist.Width() + 2
		rightTotal := w - rightX
		if rightTotal < 1 {
			rightTotal = 1
		}
		gap := 2
		baseScreenW := 1
		baseHistoryW := 1
		if rightTotal > gap+2 {
			baseScreenW = (rightTotal - gap) * 2 / 3
			baseHistoryW = rightTotal - gap - baseScreenW
			if baseScreenW < 1 {
				baseScreenW = 1
			}
			if baseHistoryW < 1 {
				baseHistoryW = 1
			}
		}
		if wdisasm.Visible() {
			historyW := baseHistoryW - 8
			if historyW < 1 {
				historyW = 1
			}
			disasmW := baseHistoryW - 8
			if disasmW < 1 {
				disasmW = 1
			}
			screenW := rightTotal - historyW - disasmW - 2*gap
			if screenW < 1 {
				screenW = 1
			}
			wscreen.Reshape(rightX, 2, screenW, wcpu.Y()-3)
			wdisasm.Reshape(wscreen.X()+wscreen.Width()+gap, 2, disasmW, wcpu.Y()-3)
			historyX := wdisasm.X() + wdisasm.Width() + gap
			historyH := wcpu.Y() - 3
			if historyH < 1 {
				historyH = 1
			}
			if wbreakpoints.Visible() {
				historyTopH := historyH / 2
				if historyTopH < 1 {
					historyTopH = 1
				}
				breakH := historyH - historyTopH
				if breakH < 1 {
					breakH = 1
				}
				whistory.Reshape(historyX, 2, historyW, historyTopH)
				wbreakpoints.Reshape(historyX, 2+historyTopH, historyW, breakH)
			} else {
				whistory.Reshape(historyX, 2, historyW, historyH)
			}
		} else {
			wscreen.Reshape(rightX, 2, baseScreenW, wcpu.Y()-3)
			historyX := wscreen.X() + wscreen.Width() + gap
			historyH := wcpu.Y() - 3
			if historyH < 1 {
				historyH = 1
			}
			if wbreakpoints.Visible() {
				historyTopH := historyH / 2
				if historyTopH < 1 {
					historyTopH = 1
				}
				breakH := historyH - historyTopH
				if breakH < 1 {
					breakH = 1
				}
				whistory.Reshape(historyX, 2, baseHistoryW, historyTopH)
				wbreakpoints.Reshape(historyX, 2+historyTopH, baseHistoryW, breakH)
			} else {
				whistory.Reshape(historyX, 2, baseHistoryW, historyH)
			}
		}
		top.Reshape(0, 0, w, 1)
		bottom.Reshape(0, h-1, w, 1)
	}
	screen.layoutInitializer = layout

	app := NewApp(screen, statusUpdater, 20)
	breakpointsWindowUpdater := NewBreakpointsWindowUpdater(app, screen, wbreakpoints.Window)
	disassemblyView.BindInput(screen, dispatcher)
	screenInspector.BindInput(screen)
	watchersView.BindInput(screen, dispatcher)
	breakpointsView.BindInput(screen, dispatcher)

	buildShortcuts(dispatcher, screen, wdlist.Window, whistory.Window, wscreen, wwatch.Window, wbreakpoints.Window, wdisasm, app, disassemblyView)
	inputProcessor := NewShortcutInput(shortcuts, dispatcher)

	app.AddComponent(dispatcher)
	app.AddComponent(cpu)
	app.AddComponent(disassemblyView)
	app.AddComponent(watchersView)
	app.AddComponent(breakpointsView)
	app.AddComponent(inputProcessor)
	app.AddComponent(topbar)
	app.AddComponent(appmodeUpdater)
	app.AddComponent(breakpointsWindowUpdater)
	app.AddComponent(shortcutbar)
	app.AddComponent(displayList)
	app.AddComponent(screenInspector)
	app.AddComponent(historyView)

	return app.Loop(ctx)
}

func buildShortcuts(dispatcher *ActionDispatcher, screen *Screen, wdlist, whistory, wscreen, wwatch, wbreakpoints, wdisasm *Window, app *App, disassemblyView *DisassemblyViewer) {
	action := func(key int, label string, a Action) Shortcut {
		return NewShortcut(key, label, func() { _ = dispatcher.Dispatch(a, nil) })
	}
	stepWithFollow := func(a Action) func() {
		return func() {
			disassemblyView.EnableFollow()
			_ = dispatcher.Dispatch(a, nil)
		}
	}
	step := NewShortcut(KeyF(5), "Step", stepWithFollow(ActionStep))
	stepVBlank := NewShortcut(KeyF(6), "Step VBLANK", stepWithFollow(ActionStepVBlank))
	stepOver := NewShortcut(KeyF(7), "Step over", stepWithFollow(ActionStepOver))
	pause := action(KeyF(8), "Pause", ActionPause)
	cont := action(KeyF(8), "Continue", ActionContinue)
	enterShutdown := action(27, "Shutdown", ActionEnterShutdown)
	exitShutdown := action(27, "Back", ActionExitShutdown)

	normal := NewShortcutLayer("NORMAL", ColorAppMode)
	_ = normal.Add(step)
	_ = normal.Add(stepVBlank)
	_ = normal.Add(stepOver)
	_ = normal.Add(pause)
	_ = normal.Add(enterShutdown)

	debug := NewShortcutLayer("DEBUG", ColorAppModeDebug)
	_ = debug.Add(step)
	_ = debug.Add(stepVBlank)
	_ = debug.Add(stepOver)
	_ = debug.Add(cont)
	_ = debug.Add(enterShutdown)

	shutdown := NewShortcutLayer("SHUTDOWN", ColorAppModeShutdown)
	_ = shutdown.Add(action(int('c'), "Cold start", ActionColdStart))
	_ = shutdown.Add(action(int('w'), "Warm start", ActionWarmStart))
	_ = shutdown.Add(action(int('t'), "Terminate", ActionTerminate))
	_ = shutdown.Add(exitShutdown)

	_ = shortcuts.Add(AppModeNormal, normal)
	_ = shortcuts.Add(AppModeDebug, debug)
	_ = shortcuts.Add(AppModeShutdown, shutdown)

	toggleDisasm := func() {
		st := State()
		if !wdisasm.Visible() {
			if st.DisassemblyAddr == nil {
				addr := st.CPU.PC
				_ = dispatcher.Dispatch(ActionSetDisassemblyAddr, addr)
			}
			_ = dispatcher.Dispatch(ActionSetDisassembly, true)
			wdisasm.SetVisible(true)
			app.RebuildScreen()
			screen.Focus(wdisasm)
			return
		}
		if screen.Focused() == wdisasm {
			screen.Focus(nil)
		} else {
			screen.Focus(wdisasm)
		}
	}
	focusWatchers := func() {
		if screen.Focused() == wwatch {
			screen.Focus(nil)
			return
		}
		screen.Focus(wwatch)
	}
	focusDisplayList := func() {
		if screen.Focused() == wdlist {
			screen.Focus(nil)
			return
		}
		screen.Focus(wdlist)
	}
	focusHistory := func() {
		if screen.Focused() == whistory {
			screen.Focus(nil)
			return
		}
		screen.Focus(whistory)
	}
	focusScreenBuffer := func() {
		if screen.Focused() == wscreen {
			screen.Focus(nil)
			return
		}
		screen.Focus(wscreen)
	}
	focusBreakpoints := func() {
		if !wbreakpoints.Visible() {
			return
		}
		if screen.Focused() == wbreakpoints {
			screen.Focus(nil)
			return
		}
		screen.Focus(wbreakpoints)
	}

	addWindowHotkey := func(window *Window, key int, label string, callback func()) {
		shortcut := NewShortcut(key, label, callback)
		shortcut.VisibleInGlobalBar = false
		_ = shortcuts.AddGlobal(shortcut)
		window.SetHotkeyLabel(shortcut.KeyAsText())
	}

	addWindowHotkey(wdlist, int('l'), "DisplayList", focusDisplayList)
	addWindowHotkey(whistory, int('h'), "History", focusHistory)
	addWindowHotkey(wscreen, int('s'), "Screen Buffer", focusScreenBuffer)
	addWindowHotkey(wwatch, int('w'), "Watchers", focusWatchers)
	addWindowHotkey(wbreakpoints, int('b'), "Breakpoints", focusBreakpoints)
	addWindowHotkey(wdisasm, int('d'), "Disassembly", toggleDisasm)
	nextWindow := NewShortcut(9, "Next window", screen.FocusNext)
	nextWindow.VisibleInGlobalBar = false
	_ = shortcuts.AddGlobal(nextWindow)
	prevWindow := NewShortcut(KeyBackTab(), "Previous window", screen.FocusPrev)
	prevWindow.VisibleInGlobalBar = false
	_ = shortcuts.AddGlobal(prevWindow)
	_ = shortcuts.AddGlobal(action(KeyF(9), "Freeze", ActionToggleFreeze))
	_ = shortcuts.AddGlobal(action(int('q'), "Quit", ActionQuit))
}
