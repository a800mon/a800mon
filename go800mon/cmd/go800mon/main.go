package main

import (
	"os"

	"go800mon/a800mon/cli"
	_ "go800mon/a800mon/monitor"
)

func main() {
	os.Exit(cli.Main(os.Args[1:]))
}
