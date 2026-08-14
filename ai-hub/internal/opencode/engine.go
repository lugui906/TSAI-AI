package opencode

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os/exec"
	"strings"
	"time"
)

var EnginePath = "opencode"

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

type opencodeEvent struct {
	Type    string `json:"type"`
	Part    struct {
		Text string `json:"text"`
	} `json:"part"`
}

func runOpencode(ctx context.Context, args []string) (*AgentResult, error) {
	cmd := exec.CommandContext(ctxOrDefault(ctx), EnginePath, args...)

	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("opencode error: %w\noutput: %s", err, string(output))
	}

	lines := strings.Split(strings.TrimSpace(string(output)), "\n")
	var textParts []string

	for _, line := range lines {
		if line == "" {
			continue
		}
		var evt opencodeEvent
		if err := json.Unmarshal([]byte(line), &evt); err != nil {
			continue
		}
		if evt.Type == "text" && evt.Part.Text != "" {
			textParts = append(textParts, evt.Part.Text)
		}
	}

	return &AgentResult{
		Success: true,
		Output:  strings.Join(textParts, "\n"),
	}, nil
}

func (p *PlanAgent) Execute(ctx context.Context, prompt string) (*AgentResult, error) {
	args := []string{"run", "--format", "json", prompt}
	return runOpencode(ctx, args)
}

func (b *BuildAgent) Execute(ctx context.Context, prompt string) (*AgentResult, error) {
	args := []string{"run", "--auto", "--format", "json", prompt}
	return runOpencode(ctx, args)
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
