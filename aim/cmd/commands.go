package cmd

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"text/tabwriter"

	"github.com/chindows/aim/internal/opencode"
	"github.com/chindows/aim/internal/server"
	"github.com/chindows/aim/internal/storage"
	"github.com/chindows/aim/internal/system"
)

type command struct {
	name    string
	aliases []string
	desc    string
	flags   *flag.FlagSet
	run     func(args []string)
}

var commands []command

func Register(name string, aliases []string, desc string, run func(args []string)) {
	commands = append(commands, command{name: name, aliases: aliases, desc: desc, run: run})
}

func Execute() {
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}
	cmdName := os.Args[1]
	if cmdName == "--help" || cmdName == "-h" || cmdName == "help" {
		printUsage()
		return
	}
	for _, cmd := range commands {
		if cmd.name == cmdName {
			cmd.run(os.Args[2:])
			return
		}
	}
	fmt.Fprintf(os.Stderr, "Unknown command: %s\n", cmdName)
	printUsage()
	os.Exit(1)
}

func printUsage() {
	fmt.Println("AIM 2.0 - AI Intelligence Middleware")
	fmt.Println("Usage: aim <command> [options]")
	fmt.Println("\nCommands:")
	w := tabwriter.NewWriter(os.Stdout, 0, 0, 3, ' ', 0)
	for _, cmd := range commands {
		fmt.Fprintf(w, "  %s\t%s\n", cmd.name, cmd.desc)
	}
	w.Flush()
}

func init() {
	registerRun()
	registerModel()
	registerServe()
	registerFix()
	registerDebug()
	registerChat()
}

func registerRun() {
	runOpenCode := func(ocArgs []string) {
		cmd := exec.CommandContext(context.Background(), opencode.EnginePath, ocArgs...)
		output, err := cmd.CombinedOutput()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %s\n%s", err, string(output))
			os.Exit(1)
		}
		for _, line := range strings.Split(strings.TrimSpace(string(output)), "\n") {
			if line == "" {
				continue
			}
			var evt struct {
				Type string `json:"type"`
				Part struct {
					Text string `json:"text"`
				} `json:"part"`
			}
			if err := json.Unmarshal([]byte(line), &evt); err != nil {
				continue
			}
			if evt.Type == "text" && evt.Part.Text != "" {
				fmt.Println(evt.Part.Text)
			}
		}
	}

	Register("run", []string{}, "Execute tasks with full system access (continues conversation)", func(args []string) {
		prompt := strings.Join(args, " ")
		if prompt == "" {
			fmt.Fprintln(os.Stderr, "Error: prompt required")
			os.Exit(1)
		}
		storage.LogOperation("run", prompt, "system", "started", "", false)
		runOpenCode([]string{"run", "--auto", "--continue", "--format", "json", prompt})
		storage.LogOperation("run", prompt, "system", "completed", "", false)
	})

	Register("newrun", []string{}, "Execute tasks in a new conversation", func(args []string) {
		prompt := strings.Join(args, " ")
		if prompt == "" {
			fmt.Fprintln(os.Stderr, "Error: prompt required")
			os.Exit(1)
		}
		storage.LogOperation("newrun", prompt, "system", "started", "", false)
		runOpenCode([]string{"run", "--auto", "--format", "json", prompt})
		storage.LogOperation("newrun", prompt, "system", "completed", "", false)
	})
}

func registerModel() {
	Register("model", []string{}, "Manage AI models and providers via OpenCode", func(args []string) {
		if len(args) < 1 {
			fmt.Fprintln(os.Stderr, "Usage: aim model <list|switch|set-backend|pull|delete> [options]")
			fmt.Fprintln(os.Stderr, "\nSubcommands delegate to 'opencode' under the hood.")
			os.Exit(1)
		}
		sub := args[0]
		subArgs := args[1:]

		switch sub {
		case "list":
			ocArgs := []string{"models"}
			if len(subArgs) > 0 {
				ocArgs = append(ocArgs, subArgs[0])
			}
			cmd := exec.CommandContext(context.Background(), opencode.EnginePath, ocArgs...)
			cmd.Stdout = os.Stdout
			cmd.Stderr = os.Stderr
			if err := cmd.Run(); err != nil {
				os.Exit(1)
			}

		case "switch", "set-backend":
			cmd := exec.CommandContext(context.Background(), opencode.EnginePath, "providers")
			cmd.Stdin = os.Stdin
			cmd.Stdout = os.Stdout
			cmd.Stderr = os.Stderr
			if err := cmd.Run(); err != nil {
				os.Exit(1)
			}

		case "pull":
			fmt.Println("Use 'opencode providers' to configure a provider with the model, then:")
			fmt.Println("  aim model list    # list available models from providers")

		case "delete":
			fmt.Println("Model deletion is managed via the provider. Use 'opencode providers' to manage.")

		default:
			fmt.Fprintf(os.Stderr, "Unknown model subcommand: %s\n", sub)
			os.Exit(1)
		}
	})
}

func registerServe() {
	showToken := func() {
		cfg, err := storage.LoadConfig()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		if cfg.RemoteToken == "" {
			fmt.Println("No token configured. Start server with 'aim serve' to auto-generate one.")
			return
		}
		fmt.Println(cfg.RemoteToken)
	}

	Register("serve", []string{}, "Start AIM intranet remote AI service with Token authentication", func(args []string) {
		if len(args) > 0 && args[0] == "token" {
			showToken()
			return
		}

		fs := flag.NewFlagSet("serve", flag.ExitOnError)
		port := fs.Int("port", 21526, "Port to listen on")
		token := fs.String("token", "", "Remote access token (auto-generated if empty)")
		fs.Parse(args)

		cfg, err := storage.LoadConfig()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error loading config: %v\n", err)
			os.Exit(1)
		}
		if *port == 21526 && cfg.ServePort != 0 {
			*port = cfg.ServePort
		}
		if *token == "" && cfg.RemoteToken != "" {
			*token = cfg.RemoteToken
		}

		svr := server.NewServer(*port, *token)
		if *token == "" {
			cfg.RemoteToken = svr.Token()
			storage.SaveConfig(cfg)
		}

		storage.LogOperation("serve", fmt.Sprintf("port=%d", *port), "system", "started", "", false)
		fmt.Printf("AIM serve starting on port %d\n", *port)
		fmt.Printf("Remote access token: %s\n", svr.Token())
		fmt.Println("Use this token on remote devices to connect")

		if err := svr.Start(context.Background()); err != nil {
			fmt.Fprintf(os.Stderr, "Server error: %v\n", err)
			os.Exit(1)
		}
		storage.LogOperation("serve", fmt.Sprintf("port=%d", *port), "system", "stopped", "", false)
	})
}

func registerFix() {
	Register("fix", []string{}, "AI-assisted system fix and repair", func(args []string) {
		prompt := strings.Join(args, " ")
		if prompt == "" {
			fmt.Fprintln(os.Stderr, "Error: issue description required")
			os.Exit(1)
		}
		fixPrompt := fmt.Sprintf("Diagnose and fix the following system issue: %s", prompt)
		storage.LogOperation("fix", fixPrompt, "system", "started", "", false)
		build := opencode.NewBuildAgent("fix-session", true)
		result, err := 		build.Execute(context.Background(), fixPrompt)
		if err != nil {
			storage.LogOperation("fix", fixPrompt, "system", "failed", err.Error(), false)
			fmt.Fprintf(os.Stderr, "Fix failed: %v\n", err)
			os.Exit(1)
		}
		storage.LogOperation("fix", fixPrompt, "system", "completed", result.Output, false)
		fmt.Println(result.Output)
	})
}

func registerDebug() {
	Register("debug", []string{}, "AI-assisted system diagnostics and debugging", func(args []string) {
		storage.LogOperation("debug", fmt.Sprintf("%v", args), "system", "started", "", false)

		hw, err := system.GetHardwareInfo()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Warning: could not get hardware info: %v\n", err)
		}
		var info string
		if hw != nil {
			info = fmt.Sprintf("System Info:\n  Hostname: %s\n  OS: %s\n  Kernel: %s\n  CPU: %s\n  Memory: %s\n  Arch: %s\n",
				hw.Hostname, hw.OS, hw.Kernel, hw.CPU, hw.Memory, hw.Architecture)
		}
		target := "general system diagnostics"
		if len(args) > 0 {
			target = strings.Join(args, " ")
		}
		prompt := fmt.Sprintf("Debug the following target: %s\n\nSystem information:\n%s", target, info)

		plan := opencode.NewPlanAgent("debug-session")
		planResult, err := 		plan.Execute(context.Background(), prompt)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Debug analysis error: %v\n", err)
			storage.LogOperation("debug", prompt, "system", "failed", err.Error(), false)
			return
		}
		fmt.Println("=== Debug Analysis ===")
		fmt.Println(planResult.Output)

		fmt.Println("\n=== Recent Operations ===")
		logs, err := storage.QueryLogs(10)
		if err == nil {
			for _, l := range logs {
				fmt.Printf("[%s] %s %s - %s\n", l.Time, l.Command, l.Args, l.Status)
			}
		}
		storage.LogOperation("debug", prompt, "system", "completed", planResult.Output, false)
	})
}

func registerChat() {
	Register("chat", []string{}, "Interactive AI chat session via OpenCode", func(args []string) {
		ocArgs := []string{"run"}
		if extra := args; len(extra) > 0 {
			ocArgs = append(ocArgs, strings.Join(extra, " "))
		}

		cmd := exec.CommandContext(context.Background(), opencode.EnginePath, ocArgs...)
		cmd.Stdin = os.Stdin
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			fmt.Fprintf(os.Stderr, "Chat error: %v\n", err)
			os.Exit(1)
		}
	})
}
