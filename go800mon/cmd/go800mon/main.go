package main

import (
	"os"

	"go800mon/a800mon"
	_ "go800mon/a800mon/monitor"
)

func main() {
	os.Exit(a800mon.Main(os.Args[1:]))
}
