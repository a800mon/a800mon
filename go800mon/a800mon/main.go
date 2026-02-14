package a800mon

import (
	"context"
	"fmt"
)

var monitorRunner func(context.Context, string) error

func RegisterMonitorRunner(run func(context.Context, string) error) {
	monitorRunner = run
}

func RunMonitor(ctx context.Context, socketPath string) error {
	if monitorRunner == nil {
		return fmt.Errorf("monitor runner is not registered")
	}
	return monitorRunner(ctx, socketPath)
}
