package cli

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"strings"

	"go800mon/internal/memory"
)

func cmdCPUState(socket string) int {
	return printCPUState(rpcClient(socket))
}

func cmdSetReg(socket string, args cliSetRegCmd) int {
	target := setRegTargets[strings.ToLower(args.Target)]
	value, err := memory.ParseHex(args.Value)
	if err != nil {
		return fail(err)
	}
	payload := make([]byte, 3)
	payload[0] = target
	binary.LittleEndian.PutUint16(payload[1:3], value)
	if _, err := rpcClient(socket).Call(context.Background(), CmdSetReg, payload); err != nil {
		return fail(err)
	}
	return 0
}

func cmdBBRK(socket string, args cliBBRKCmd) int {
	var payload []byte
	if args.Enabled != nil {
		enabled, err := parseBool(*args.Enabled)
		if err != nil {
			return fail(err)
		}
		if enabled {
			payload = []byte{1}
		} else {
			payload = []byte{0}
		}
	}
	data, err := rpcClient(socket).Call(context.Background(), CmdBBRK, payload)
	if err != nil {
		return fail(err)
	}
	if len(data) < 1 {
		return fail(errors.New("BBRK payload too short"))
	}
	if data[0] == 0 {
		fmt.Println("bbrk=off")
		return 0
	}
	fmt.Println("bbrk=on")
	return 0
}

func parseBool(value string) (bool, error) {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "1", "on", "true", "yes":
		return true, nil
	case "0", "off", "false", "no":
		return false, nil
	}
	return false, fmt.Errorf("Invalid boolean value: %s", value)
}
