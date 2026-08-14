package opencode

import (
	"bufio"
	"context"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/chindows/aim/internal/storage"
)

const (
	DefaultEngineName  = "opencode"
	OpenClawEngineName = "openclaw"
)

var EnginePath = DefaultEngineName

// EnginePathFromConfig returns the persisted default engine binary name
// from aim's config, falling back to opencode when unset or unavailable.
func EnginePathFromConfig() string {
	cfg, err := storage.LoadConfig()
	if err != nil {
		return DefaultEngineName
	}
	if cfg.Engine != "" {
		return cfg.Engine
	}
	return DefaultEngineName
}

// ApplyPersistedEngine loads the persisted engine into the global EnginePath.
// Called once at CLI startup so every command honors the configured default.
func ApplyPersistedEngine() {
	EnginePath = EnginePathFromConfig()
}

type PlanAgent struct {
	sessionID string
}

type BuildAgent struct {
	sessionID string
	fullAccess bool
}

type AgentResult struct {
	Success   bool       `json:"success"`
	Output    string     `json:"output"`
}

func NewPlanAgent(sessionID string) *PlanAgent {
	return &PlanAgent{sessionID: sessionID}
}

func NewBuildAgent(sessionID string, fullAccess bool) *BuildAgent {
	return &BuildAgent{
		sessionID:  sessionID,
		fullAccess: fullAccess,
	}
}

func ctxOrDefault(ctx context.Context) context.Context {
	if ctx == nil {
		return context.Background()
	}
	return ctx
}

var providerEnvMap = map[string]string{
	"openai":    "OPENAI_API_KEY",
	"anthropic": "ANTHROPIC_API_KEY",
	"deepseek":  "DEEPSEEK_API_KEY",
	"groq":      "GROQ_API_KEY",
	"google":    "GOOGLE_API_KEY",
	"mistral":   "MISTRAL_API_KEY",
	"cohere":    "COHERE_API_KEY",
	"together":  "TOGETHER_API_KEY",
	"openrouter":"OPENROUTER_API_KEY",
}

func APIKeyEnvVars() []string {
	cfg, err := storage.LoadConfig()
	if err != nil {
		return nil
	}
	var envs []string
	for provider, key := range cfg.APIKeys {
		envKey, ok := providerEnvMap[provider]
		if !ok {
			envKey = strings.ToUpper(provider) + "_API_KEY"
		}
		envs = append(envs, envKey+"="+key)
	}
	return envs
}

func runEngine(ctx context.Context, args []string) (*AgentResult, error) {
	adapter := CurrentAdapter()
	cmd := exec.CommandContext(ctxOrDefault(ctx), adapter.Binary(), args...)
	cmd.Env = append(os.Environ(), APIKeyEnvVars()...)

	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("%s error: %w\nstderr: %s", adapter.Binary(), err, stderr.String())
	}

	return &AgentResult{
		Success: true,
		Output:  strings.Join(adapter.ExtractText(stdout.String()), "\n"),
	}, nil
}

// RunAndStream executes the engine with the given argv and prints text output
// as it arrives (opencode NDJSON) or after completion (openclaw JSON).
func RunAndStream(ctx context.Context, args []string) error {
	adapter := CurrentAdapter()
	cmd := exec.CommandContext(ctxOrDefault(ctx), adapter.Binary(), args...)
	cmd.Env = append(os.Environ(), APIKeyEnvVars()...)
	cmd.Stderr = os.Stderr

	if adapter.IsOpenClaw() {
		var stdout, stderr strings.Builder
		cmd.Stdout = &stdout
		cmd.Stderr = &stderr
		if err := cmd.Start(); err != nil {
			return err
		}
		if err := cmd.Wait(); err != nil {
			return fmt.Errorf("%s: %w\n%s", adapter.Binary(), err, stderr.String())
		}
		for _, t := range adapter.ExtractText(stdout.String()) {
			fmt.Println(t)
		}
		return nil
	}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return err
	}

	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		for _, t := range adapter.ExtractText(line) {
			fmt.Println(t)
		}
	}
	return cmd.Wait()
}

func (p *PlanAgent) Execute(ctx context.Context, prompt string) (*AgentResult, error) {
	args := CurrentAdapter().RunArgs(prompt, false, false)
	return runEngine(ctx, args)
}

func (b *BuildAgent) Execute(ctx context.Context, prompt string) (*AgentResult, error) {
	args := CurrentAdapter().RunArgs(prompt, true, false)
	return runEngine(ctx, args)
}

type EngineManager struct {
	Port    int
	process *exec.Cmd
}

func NewEngineManager(port int) *EngineManager {
	return &EngineManager{Port: port}
}

func (em *EngineManager) Start(ctx context.Context) error {
	ctx = ctxOrDefault(ctx)
	em.process = exec.CommandContext(ctx, EnginePath,
		"serve",
		"--port", fmt.Sprintf("%d", em.Port),
	)

	if err := em.process.Start(); err != nil {
		return fmt.Errorf("failed to start OpenCode engine: %w", err)
	}

	ready := make(chan bool, 1)
	go func() {
		for i := 0; i < 30; i++ {
			resp, err := http.Get(fmt.Sprintf("http://localhost:%d/health", em.Port))
			if err == nil {
				resp.Body.Close()
				ready <- true
				return
			}
			time.Sleep(time.Second)
		}
		ready <- false
	}()

	select {
	case ok := <-ready:
		if !ok {
			return fmt.Errorf("OpenCode engine failed to start within 30s")
		}
	case <-ctx.Done():
		return ctx.Err()
	}
	return nil
}

func (em *EngineManager) Stop() error {
	if em.process != nil && em.process.Process != nil {
		return em.process.Process.Kill()
	}
	return nil
}

func (em *EngineManager) IsAlive() bool {
	if em.process == nil || em.process.Process == nil {
		return false
	}
	return em.process.Process.Signal(nil) == nil
}

func (em *EngineManager) Restart(ctx context.Context) error {
	if err := em.Stop(); err != nil {
		return err
	}
	return em.Start(ctx)
}
