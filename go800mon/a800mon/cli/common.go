package cli

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/alecthomas/kong"
)

func cmdMonitor(socket string) int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	err := RunMonitor(ctx, socket)
	if err != nil && err != context.Canceled {
		return fail(err)
	}
	return 0
}

func cmdSimple(socket string, cmd Command) int {
	_, err := rpcClient(socket).Call(context.Background(), cmd, nil)
	if err != nil {
		return fail(err)
	}
	return 0
}

func colorizedHelpPrinter(base kong.HelpPrinter) kong.HelpPrinter {
	return func(options kong.HelpOptions, ctx *kong.Context) error {
		out := ctx.Stdout
		var buf bytes.Buffer
		ctx.Stdout = &buf
		err := base(options, ctx)
		ctx.Stdout = out
		if err != nil {
			return err
		}
		text := buf.String()
		if !helpColorEnabled() {
			_, werr := io.WriteString(out, text)
			return werr
		}
		_, werr := io.WriteString(out, colorizeHelpText(text))
		return werr
	}
}

func helpColorEnabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("A800MON_HELP_COLOR"))) {
	case "always":
		return true
	case "never":
		return false
	}
	term := os.Getenv("TERM")
	return term != "" && term != "dumb"
}

func colorizeHelpText(text string) string {
	const (
		reset = "\x1b[0m"
		head  = "\x1b[1;36m"
		cmd   = "\x1b[1;33m"
		flag  = "\x1b[32m"
		dim   = "\x1b[2m"
	)
	lines := strings.Split(text, "\n")
	for i, line := range lines {
		trim := strings.TrimSpace(line)
		leading := len(line) - len(strings.TrimLeft(line, " "))
		if strings.HasPrefix(trim, "Usage:") ||
			trim == "Commands:" ||
			trim == "Arguments:" ||
			trim == "Flags:" {
			lines[i] = head + trim + reset
			continue
		}
		if strings.HasPrefix(trim, "Run \"") {
			lines[i] = dim + line + reset
			continue
		}
		if leading <= 6 && strings.HasPrefix(trim, "-") {
			lines[i] = colorizeHelpLeadingToken(line, flag, reset)
			continue
		}
		if leading == 2 && trim != "" && !strings.HasPrefix(trim, "-") &&
			(strings.Contains(trim, "  ") || strings.Contains(trim, "(")) {
			lines[i] = colorizeHelpLeadingToken(line, cmd, reset)
		}
	}
	return strings.Join(lines, "\n")
}

func colorizeHelpLeadingToken(line string, color string, reset string) string {
	indent := line[:len(line)-len(strings.TrimLeft(line, " "))]
	trim := strings.TrimSpace(line)
	sep := strings.Index(trim, "  ")
	if sep < 0 {
		return indent + color + trim + reset
	}
	return indent + color + trim[:sep] + reset + trim[sep:]
}

func fail(err error) int {
	fmt.Fprintln(os.Stderr, formatCliError(err))
	return 1
}

func formatCliError(err error) string {
	if err == nil {
		return ""
	}
	var commandErr CommandError
	if errors.As(err, &commandErr) {
		msg := strings.TrimSpace(string(commandErr.Data))
		if msg == "" {
			msg = err.Error()
		}
		return formatCliBadge(fmt.Sprintf("%d", commandErr.Status), msg)
	}
	return formatCliBadge("ERR", err.Error())
}

func formatCliBadge(code string, msg string) string {
	badge := " " + code + " "
	if cliColorEnabled() {
		return "\x1b[41;97;1m" + badge + "\x1b[0m " + msg
	}
	return "[" + code + "] " + msg
}

func cliColorEnabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("A800MON_COLOR"))) {
	case "always":
		return true
	case "never":
		return false
	}
	return helpColorEnabled()
}

func formatOnOffBadge(enabled bool) string {
	text := "OFF"
	if enabled {
		text = "ON "
	}
	badge := " " + text + " "
	if !cliColorEnabled() {
		return badge
	}
	if enabled {
		return "\x1b[42;30m" + badge + "\x1b[0m"
	}
	return "\x1b[41;97;1m" + badge + "\x1b[0m"
}

func yesNo(v bool) string {
	if v {
		return "yes"
	}
	return "no"
}
