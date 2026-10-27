package main

import (
	"fmt"
	"os"

	"github.com/octelium/octelium/pkg/utils/ldflags"
)

func main() {
	if len(os.Args) != 2 {
		os.Exit(2)
	}
	fmt.Print(ldflags.GetImage(os.Args[1], ""))
}
