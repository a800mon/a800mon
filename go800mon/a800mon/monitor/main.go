package monitor

import (
	"context"
	"time"

	. "go800mon/a800mon"
)

func init() {
	RegisterMonitorRunner(MonitorRun)
}

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

func (a *AppModeUpdater) HandleInput(ch int) bool { return false }

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

func (u *BreakpointsWindowUpdater) HandleInput(ch int) bool { return false }

func MonitorRun(ctx context.Context, socketPath string) error {
	shortcuts := NewShortcutManager()
	screen := NewScreen(nil, shortcuts)
	screen.SetShortcutModeProvider(func() int { return int(State().ActiveMode) })
	screen.Initialize()
	defer screen.End()

	rpc := NewRpcClient(NewSocketTransport(socketPath))
	defer rpc.Close()
	dispatcher := NewActionDispatcher(rpc)
	supportsBreakpoints := false
	if caps, err := rpc.Config(ctx); err == nil {
		for _, id := range caps {
			if id == CapMonitorBreakpoints {
				supportsBreakpoints = true
				break
			}
		}
	}
	_ = dispatcher.Dispatch(ActionSetBreakpointsSupported, supportsBreakpoints)

	wcpu := NewWindow("CPU State", true)
	wdlist := NewWindow("DisplayList", true)
	wwatch := NewWindow("Watchers", true)
	wscreen := NewWindow("Screen Buffer", true)
	wscreen.AddTag("ATASCII", "atascii", true)
	wscreen.AddTag("ASCII", "ascii", false)
	wdisasm := NewWindow("Disassembler", true)
	wdisasm.AddTag("FOLLOW", "follow", true)
	whistory := NewWindow("History", true)
	wbreakpoints := NewWindow("Breakpoints", true)
	wbreakpoints.AddTag("ENABLED", "bp_enabled", false)
	top := NewWindow("", false)
	bottom := NewWindow("", false)
	screen.SetFocusOrder(wdlist, wwatch, wscreen, wdisasm, whistory, wbreakpoints)

	statusUpdater := NewStatusUpdater(rpc, dispatcher, 200*time.Millisecond, 50*time.Millisecond)

	screenInspector := NewScreenBufferInspector(rpc, wscreen)
	disassemblyView := NewDisassemblyViewer(rpc, wdisasm)
	watchersView := NewWatchersViewer(rpc, wwatch)
	breakpointsView := NewBreakpointsViewer(rpc, wbreakpoints)
	historyView := NewHistoryViewer(rpc, whistory, true)
	displayList := NewDisplayListViewer(rpc, wdlist)
	cpu := NewCpuStateViewer(wcpu)
	topbar := NewTopBar(top)
	appmodeUpdater := NewAppModeUpdater(dispatcher)
	shortcutbar := NewShortcutBar(bottom, shortcuts)
	wdisasm.SetVisible(State().DisassemblyEnabled)
	wbreakpoints.SetVisible(State().BreakpointsSupported)

	layout := func(scr *Screen) {
		w, h := scr.Size()
		topY := 1
		breakpointsHTarget := 13
		wcpu.Reshape(0, h-4, w, 3)
		oldUpperH := wcpu.Y() - topY - 1
		if oldUpperH < 1 {
			oldUpperH = 1
		}
		upperH := oldUpperH + 1
		leftTotalH := oldUpperH
		if leftTotalH < 2 {
			leftTotalH = 2
		}
		oldDlistH := leftTotalH / 2
		if oldDlistH < 1 {
			oldDlistH = 1
		}
		dlistH := oldDlistH
		watchH := leftTotalH - oldDlistH + 1
		transfer := min(4, max(0, watchH-1))
		dlistH += transfer
		watchH -= transfer
		if watchH < 1 {
			watchH = 1
		}
		gap := 1
		wdlist.Reshape(0, topY, 40, dlistH)
		wwatch.Reshape(0, topY+dlistH, 40, watchH)
		rightX := wdlist.X() + wdlist.OuterWidth() + gap
		rightTotal := w - rightX
		if rightTotal < 1 {
			rightTotal = 1
		}
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
			wscreen.Reshape(rightX, topY, screenW, upperH)
			disasmX := rightX + screenW + gap
			wdisasm.Reshape(disasmX, topY, disasmW, upperH)
			historyX := disasmX + disasmW + gap
			historyH := upperH
			if historyH < 1 {
				historyH = 1
			}
			if wbreakpoints.Visible() {
				breakH := min(breakpointsHTarget, max(1, historyH-1))
				historyTopH := max(1, historyH-breakH)
				breakH = max(1, historyH-historyTopH)
				whistory.Reshape(historyX, topY, historyW, historyTopH)
				wbreakpoints.Reshape(historyX, topY+historyTopH, historyW, breakH)
			} else {
				whistory.Reshape(historyX, topY, historyW, historyH)
			}
		} else {
			screenW := baseScreenW
			wscreen.Reshape(rightX, topY, screenW, upperH)
			historyX := rightX + screenW + gap
			historyH := upperH
			if historyH < 1 {
				historyH = 1
			}
			if wbreakpoints.Visible() {
				breakH := min(breakpointsHTarget, max(1, historyH-1))
				historyTopH := max(1, historyH-breakH)
				breakH = max(1, historyH-historyTopH)
				whistory.Reshape(historyX, topY, baseHistoryW, historyTopH)
				wbreakpoints.Reshape(historyX, topY+historyTopH, baseHistoryW, breakH)
			} else {
				whistory.Reshape(historyX, topY, baseHistoryW, historyH)
			}
		}
		top.Reshape(0, 0, w, 1)
		bottom.Reshape(0, h-1, w, 1)
	}
	screen.SetLayoutInitializer(layout)
	dispatcher.SetInputFocusHandler(screen.SetInputFocus)

	app := NewApp(screen, dispatcher, statusUpdater, 20)
	breakpointsWindowUpdater := NewBreakpointsWindowUpdater(app, screen, wbreakpoints)

	app.AddComponent(dispatcher)
	app.AddComponent(cpu)
	app.AddComponent(disassemblyView)
	app.AddComponent(watchersView)
	app.AddComponent(breakpointsView)
	app.AddComponent(topbar)
	app.AddComponent(appmodeUpdater)
	app.AddComponent(breakpointsWindowUpdater)
	app.AddComponent(shortcutbar)
	app.AddComponent(displayList)
	app.AddComponent(screenInspector)
	app.AddComponent(historyView)

	buildShortcuts(shortcuts, dispatcher, screen, wdlist, whistory, wscreen, wwatch, wbreakpoints, wdisasm, app, disassemblyView)

	return app.Loop(ctx)
}

func buildShortcuts(shortcuts *ShortcutManager, dispatcher *ActionDispatcher, screen *Screen, wdlist, whistory, wscreen, wwatch, wbreakpoints, wdisasm *Window, app *App, disassemblyView *DisassemblyViewer) {
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
	_ = shutdown.Add(action('c', "Cold start", ActionColdStart))
	_ = shutdown.Add(action('w', "Warm start", ActionWarmStart))
	_ = shutdown.Add(action('t', "Terminate", ActionTerminate))
	_ = shutdown.Add(exitShutdown)

	_ = shortcuts.Add(int(AppModeNormal), normal)
	_ = shortcuts.Add(int(AppModeDebug), debug)
	_ = shortcuts.Add(int(AppModeShutdown), shutdown)

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
		}
		screen.Focus(wdisasm)
	}

	wdlist.AddHotkey('l', "DisplayList", func() { screen.Focus(wdlist) }, false)
	whistory.AddHotkey('h', "History", func() { screen.Focus(whistory) }, false)
	wscreen.AddHotkey('s', "Screen Buffer", func() { screen.Focus(wscreen) }, false)
	wwatch.AddHotkey('w', "Watchers", func() { screen.Focus(wwatch) }, false)
	wbreakpoints.AddHotkey(
		'b',
		"Breakpoints",
		func() { screen.Focus(wbreakpoints) },
		false,
	)
	wdisasm.AddHotkey('d', "Disassembly", toggleDisasm, false)
	nextWindow := NewShortcut(9, "Next window", screen.FocusNext)
	nextWindow.VisibleInGlobalBar = false
	_ = shortcuts.AddGlobal(nextWindow)
	prevWindow := NewShortcut(KeyBackTab(), "Previous window", screen.FocusPrev)
	prevWindow.VisibleInGlobalBar = false
	_ = shortcuts.AddGlobal(prevWindow)
	_ = shortcuts.AddGlobal(action(KeyF(9), "Freeze", ActionToggleFreeze))
	_ = shortcuts.AddGlobal(action('q', "Quit", ActionQuit))
}
