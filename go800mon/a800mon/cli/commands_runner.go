package cli

import (
	"context"
	"os"
	"path/filepath"
	"strings"
)

func cmdRun(socket string, pathArg string) int {
	path, err := expandPath(pathArg)
	if err != nil {
		return fail(err)
	}
	_, err = rpcClient(socket).Call(context.Background(), CmdRun, []byte(path))
	if err != nil {
		return fail(err)
	}
	return 0
}

func expandPath(path string) (string, error) {
	if strings.HasPrefix(path, "~/") {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		path = filepath.Join(home, path[2:])
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	real, err := filepath.EvalSymlinks(abs)
	if err == nil {
		return real, nil
	}
	return abs, nil
}
