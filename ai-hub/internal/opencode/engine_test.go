package opencode

import (
	"context"
	"os"
	"strings"
	"testing"
)

func TestNewPlanAgent(t *testing.T) {
	agent := NewPlanAgent("test-session")
	if agent.sessionID != "test-session" {
		t.Errorf("expected session 'test-session', got '%s'", agent.sessionID)
	}
}

func TestNewBuildAgent(t *testing.T) {
	agent := NewBuildAgent("test-session", true)
	if agent.sessionID != "test-session" {
		t.Errorf("expected session 'test-session', got '%s'", agent.sessionID)
	}
	if !agent.fullAccess {
		t.Error("expected fullAccess to be true")
	}

	agent2 := NewBuildAgent("test-session-2", false)
	if agent2.fullAccess {
		t.Error("expected fullAccess to be false")
	}
}

func TestCtxOrDefault(t *testing.T) {
	ctx := ctxOrDefault(nil)
	if ctx == nil {
		t.Error("expected non-nil context from nil input")
	}

	bg := context.Background()
	ctx2 := ctxOrDefault(bg)
	if ctx2 != bg {
		t.Error("expected same context back")
	}
}

func TestAgentExecuteNoOpenCode(t *testing.T) {
	orig := EnginePath
	defer func() { EnginePath = orig }()

	EnginePath = "nonexistent-binary-12345"

	plan := NewPlanAgent("test")
	_, err := plan.Execute(context.Background(), "test prompt")
	if err == nil {
		t.Error("expected error when binary doesn't exist")
	}
	if !strings.Contains(err.Error(), "nonexistent-binary-12345") {
		t.Errorf("error should mention the binary name, got: %v", err)
	}
}

func TestBuildExecuteNoOpenCode(t *testing.T) {
	orig := EnginePath
	defer func() { EnginePath = orig }()

	EnginePath = "nonexistent-binary-12345"

	build := NewBuildAgent("test", true)
	_, err := build.Execute(context.Background(), "test prompt")
	if err == nil {
		t.Error("expected error when binary doesn't exist")
	}
}

func TestEngineManager(t *testing.T) {
	em := NewEngineManager(9999)
	if em.Port != 9999 {
		t.Errorf("expected port 9999, got %d", em.Port)
	}

	if em.IsAlive() {
		t.Error("expected engine not alive before start")
	}
}

func TestNewEngineManager(t *testing.T) {
	em := NewEngineManager(21526)
	if em.Port != 21526 {
		t.Errorf("expected port 21526, got %d", em.Port)
	}
	if em.process != nil {
		t.Error("expected nil process on creation")
	}
}

func TestEnginePathDefault(t *testing.T) {
	if EnginePath != "opencode" {
		t.Errorf("expected default EnginePath 'opencode', got '%s'", EnginePath)
	}
}

func TestAgentResultStructure(t *testing.T) {
	result := &AgentResult{
		Success: true,
		Output:  "test output",
	}
	if !result.Success {
		t.Error("expected success")
	}
	if result.Output != "test output" {
		t.Errorf("expected 'test output', got '%s'", result.Output)
	}
}

func TestRunOpencodeNoBinary(t *testing.T) {
	orig := EnginePath
	defer func() { EnginePath = orig }()

	EnginePath = "nonexistent-binary-12345"

	_, err := runEngine(context.Background(), []string{"run", "test"})
	if err == nil {
		t.Error("expected error when binary doesn't exist")
	}
}

func TestMain(m *testing.M) {
	if v := os.Getenv("AIM_ENGINE_PATH"); v != "" {
		EnginePath = v
	}
	os.Exit(m.Run())
}
