package cmd

import (
	"fmt"
	"os"

	"github.com/chindows/aim/internal/opencode"
	"github.com/chindows/aim/internal/storage"
)

func registerOC() {
	Register("oc", []string{"openclaw"}, "Switch the default AI engine to OpenClaw", func(args []string) {
		cfg, err := storage.LoadConfig()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error loading config: %v\n", err)
			os.Exit(1)
		}

		target := opencode.OpenClawEngineName
		if len(args) > 0 {
			switch args[0] {
			case "default", "--default":
				target = opencode.DefaultEngineName
			case "status":
				fmt.Println(opencode.EnginePathFromConfig())
				return
			}
		}

		cfg.Engine = target
		if err := storage.SaveConfig(cfg); err != nil {
			fmt.Fprintf(os.Stderr, "Error saving config: %v\n", err)
			os.Exit(1)
		}
		opencode.EnginePath = target
		fmt.Printf("Default AI engine switched to %s\n", target)
	})
}
