package cmd

import (
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/chindows/aim/internal/storage"
)

func registerAPIKey() {
	Register("apikey", []string{"api-key", "key"}, "Manage API keys for AI providers (keys passed to opencode as env vars)", func(args []string) {
		if len(args) < 1 {
			printAPIKeyUsage()
			return
		}

		sub := args[0]
		subArgs := args[1:]

		switch sub {
		case "set":
			if len(subArgs) < 2 {
				fmt.Fprintln(os.Stderr, "Usage: aim apikey set <provider> <key>")
				os.Exit(1)
			}
			provider := subArgs[0]
			key := subArgs[1]
			cfg, err := storage.LoadConfig()
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
			cfg.APIKeys[provider] = key
			if err := storage.SaveConfig(cfg); err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
			fmt.Printf("API key set for provider: %s\n", provider)

		case "list":
			cfg, err := storage.LoadConfig()
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
			if len(cfg.APIKeys) == 0 {
				fmt.Println("No API keys configured")
				return
			}
			providers := make([]string, 0, len(cfg.APIKeys))
			for p := range cfg.APIKeys {
				providers = append(providers, p)
			}
			sort.Strings(providers)
			fmt.Println("Configured API keys:")
			for _, p := range providers {
				key := cfg.APIKeys[p]
				masked := maskKey(key)
				fmt.Printf("  %s: %s\n", p, masked)
			}

		case "get":
			if len(subArgs) < 1 {
				fmt.Fprintln(os.Stderr, "Usage: aim apikey get <provider>")
				os.Exit(1)
			}
			cfg, err := storage.LoadConfig()
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
			key, ok := cfg.APIKeys[subArgs[0]]
			if !ok {
				fmt.Fprintf(os.Stderr, "No API key found for provider: %s\n", subArgs[0])
				os.Exit(1)
			}
			fmt.Println(key)

		case "remove", "rm", "delete":
			if len(subArgs) < 1 {
				fmt.Fprintln(os.Stderr, "Usage: aim apikey remove <provider>")
				os.Exit(1)
			}
			cfg, err := storage.LoadConfig()
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
			if _, ok := cfg.APIKeys[subArgs[0]]; !ok {
				fmt.Fprintf(os.Stderr, "No API key found for provider: %s\n", subArgs[0])
				os.Exit(1)
			}
			delete(cfg.APIKeys, subArgs[0])
			if err := storage.SaveConfig(cfg); err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				os.Exit(1)
			}
			fmt.Printf("API key removed for provider: %s\n", subArgs[0])

		default:
			printAPIKeyUsage()
			os.Exit(1)
		}
	})
}

func printAPIKeyUsage() {
	fmt.Println("Usage: aim apikey <command> [options]")
	fmt.Println("\nCommands:")
	fmt.Println("  set <provider> <key>    Set API key for a provider (e.g. openai, anthropic)")
	fmt.Println("  list                    List all configured API keys (masked)")
	fmt.Println("  get <provider>          Show API key value for a provider")
	fmt.Println("  remove|rm <provider>    Remove API key for a provider")
	fmt.Println("\nProviders map to environment variables passed to opencode:")
	fmt.Println("  openai    -> OPENAI_API_KEY")
	fmt.Println("  anthropic -> ANTHROPIC_API_KEY")
	fmt.Println("  deepseek  -> DEEPSEEK_API_KEY")
	fmt.Println("  groq      -> GROQ_API_KEY")
	fmt.Println("  <custom>  -> <CUSTOM>_API_KEY (uppercased)")
}

func maskKey(key string) string {
	if len(key) <= 8 {
		return strings.Repeat("*", len(key))
	}
	return key[:4] + strings.Repeat("*", len(key)-8) + key[len(key)-4:]
}
