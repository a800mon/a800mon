package monitor

import (
	"context"
	"time"

	. "go800mon/a800mon"
)

type Component interface {
	Update(ctx context.Context) (bool, error)
	HandleInput(ch int) bool
}

type VisualComponent interface {
	Component
	Render(force bool)
	Window() *Window
}

type App struct {
	screen         *Screen
	dispatcher     *ActionDispatcher
	components     []Component
	input          []Component
	visual         []VisualComponent
	statusUpdater  *StatusUpdater
	inputTimeoutMS int
}

func NewApp(
	screen *Screen,
	dispatcher *ActionDispatcher,
	updater *StatusUpdater,
	inputTimeoutMS int,
) *App {
	return &App{
		screen:         screen,
		dispatcher:     dispatcher,
		statusUpdater:  updater,
		inputTimeoutMS: inputTimeoutMS,
	}
}

func (a *App) AddComponent(c Component) {
	if aware, ok := c.(interface{ setApp(*App) }); ok {
		aware.setApp(a)
	}
	a.components = append(a.components, c)
	if v, ok := c.(VisualComponent); ok {
		a.visual = append(a.visual, v)
		a.screen.Add(v.Window())
		a.screen.SetWindowInputHandler(v.Window(), v.HandleInput)
		return
	}
	a.input = append(a.input, c)
}

func (a *App) DispatchAction(action Action, value any) {
	if a.dispatcher == nil {
		return
	}
	_ = a.dispatcher.Dispatch(action, value)
}

func (a *App) RebuildScreen() {
	a.screen.Rebuild()
	for _, c := range a.visual {
		if !c.Window().Visible() {
			continue
		}
		c.Render(true)
	}
	a.screen.Update()
}

func (a *App) Loop(ctx context.Context) error {
	a.screen.Initialize()
	a.screen.SetInputTimeoutMS(a.inputTimeoutMS)
	a.RebuildScreen()
	prevW, prevH := a.screen.Size()

	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		start := time.Now()
		wasFrozen := State().UIFrozen
		syncedResize := a.screen.SyncResize()
		ch := a.screen.GetInputChar()
		hadInput := false
		resizedByKey := false
		if ch == 3 { // Ctrl+C as input fallback
			return context.Canceled
		}
		if ch == KeyResize() {
			a.RebuildScreen()
			resizedByKey = true
			hadInput = true
		} else if ch != -1 {
			hadInput = a.handleInput(ch)
		}
		curW, curH := a.screen.Size()
		hadResize := false
		if syncedResize || curW != prevW || curH != prevH {
			prevW, prevH = curW, curH
			a.RebuildScreen()
			hadResize = true
		}
		if hadResize || resizedByKey {
			a.DispatchAction(ActionSetFrameTimeMS, int(time.Since(start).Milliseconds()))
			continue
		}
		if State().UIFrozen {
			if hadInput && !wasFrozen {
				a.renderComponents(true, true)
			}
			a.DispatchAction(ActionSetFrameTimeMS, int(time.Since(start).Milliseconds()))
			continue
		}
		hadTick := hadInput
		if a.statusUpdater != nil {
			ticked, err := a.statusUpdater.Tick(ctx)
			if err != nil {
				return err
			}
			hadTick = hadTick || ticked
		}
		if !hadTick {
			a.DispatchAction(ActionSetFrameTimeMS, int(time.Since(start).Milliseconds()))
			continue
		}
		hadUpdates, err := a.updateState(ctx)
		if err != nil {
			if _, ok := err.(StopLoop); ok {
				return nil
			}
			return err
		}
		if a.statusUpdater != nil && a.dispatcher != nil && a.dispatcher.TakeRPCFlushed() {
			a.statusUpdater.RequestRefresh()
		}
		a.renderComponents(hadInput || hadUpdates || hadResize, false)
		a.DispatchAction(ActionSetFrameTimeMS, int(time.Since(start).Milliseconds()))
	}
}

func (a *App) handleInput(ch int) bool {
	if ch == KeyResize() {
		a.RebuildScreen()
		return true
	}
	if a.screen.HasInputFocus() {
		return a.screen.HandleInput(ch)
	}
	if a.screen.HandleInput(ch) {
		return true
	}
	for _, c := range a.input {
		if c.HandleInput(ch) {
			return true
		}
	}
	return false
}

func (a *App) updateState(ctx context.Context) (bool, error) {
	changed := false
	for _, c := range a.components {
		ok, err := c.Update(ctx)
		if err != nil {
			return false, err
		}
		changed = changed || ok
	}
	return changed, nil
}

func (a *App) renderComponents(render bool, force bool) {
	if render || force {
		for _, c := range a.visual {
			if !c.Window().Visible() {
				continue
			}
			c.Render(force)
		}
	}
	needsUpdate := force
	if !needsUpdate {
		for _, c := range a.visual {
			if c.Window().Visible() && c.Window().Dirty() {
				needsUpdate = true
				break
			}
		}
	}
	if needsUpdate {
		a.screen.Update()
	}
}

type BaseComponent struct {
	app *App
}

func (b *BaseComponent) setApp(app *App) {
	b.app = app
}

func (b *BaseComponent) App() *App {
	return b.app
}

func (b *BaseComponent) Update(ctx context.Context) (bool, error) { return false, nil }
func (b *BaseComponent) HandleInput(ch int) bool                  { return false }

type BaseWindowComponent struct {
	BaseComponent
	window *Window
}

func NewBaseWindowComponent(window *Window) BaseWindowComponent {
	return BaseWindowComponent{window: window}
}

func (b *BaseWindowComponent) Window() *Window { return b.window }
