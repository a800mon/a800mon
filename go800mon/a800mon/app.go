package a800mon

import (
	"context"
	"time"
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
	components     []Component
	visual         []VisualComponent
	statusUpdater  *StatusUpdater
	inputTimeoutMS int
}

func NewApp(screen *Screen, updater *StatusUpdater, inputTimeoutMS int) *App {
	return &App{screen: screen, statusUpdater: updater, inputTimeoutMS: inputTimeoutMS}
}

func (a *App) AddComponent(c Component) {
	a.components = append(a.components, c)
	if v, ok := c.(VisualComponent); ok {
		a.visual = append(a.visual, v)
		a.screen.Add(v.Window())
	}
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
			store.setFrameTimeMS(int(time.Since(start).Milliseconds()))
			continue
		}
		if State().UIFrozen {
			if hadInput && !wasFrozen {
				a.renderComponents(true)
			}
			store.setFrameTimeMS(int(time.Since(start).Milliseconds()))
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
			store.setFrameTimeMS(int(time.Since(start).Milliseconds()))
			continue
		}
		hadUpdates, err := a.updateState(ctx)
		if err != nil {
			if _, ok := err.(StopLoop); ok {
				return nil
			}
			return err
		}
		a.renderComponents(hadInput || hadUpdates || hadResize)
		store.setFrameTimeMS(int(time.Since(start).Milliseconds()))
	}
}

func (a *App) handleInput(ch int) bool {
	if ch == KeyResize() {
		a.RebuildScreen()
		return true
	}
	for _, c := range a.components {
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

func (a *App) renderComponents(force bool) {
	if force {
		for _, c := range a.visual {
			if !c.Window().Visible() {
				continue
			}
			c.Render(true)
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

type BaseComponent struct{}

func (b *BaseComponent) Update(ctx context.Context) (bool, error) { return false, nil }
func (b *BaseComponent) HandleInput(ch int) bool                  { return false }

type BaseWindowComponent struct {
	BaseComponent
	window *Window
}

func NewBaseWindowComponent(window *Window) BaseWindowComponent {
	return BaseWindowComponent{window: window}
}

func (b *BaseWindowComponent) Window() *Window   { return b.window }
func (b *BaseWindowComponent) Render(force bool) {}
