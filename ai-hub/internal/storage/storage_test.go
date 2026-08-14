package storage

import (
	"os"
	"sync"
	"testing"
)

func TestInitConfigDir(t *testing.T) {
	tmpDir := t.TempDir()
	oldHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", oldHome)

	// Reset initOnce for testing
	initOnce = sync.Once{}
	encKey = nil
	configDir = ""
	configFile = ""

	if err := ensureInit(); err != nil {
		t.Fatalf("ensureInit failed: %v", err)
	}
	if configDir == "" {
		t.Fatal("configDir not set")
	}
	if configFile == "" {
		t.Fatal("configFile not set")
	}
	if len(encKey) != 32 {
		t.Fatalf("expected 32-byte key, got %d", len(encKey))
	}
}

func TestSaveLoadConfig(t *testing.T) {
	tmpDir := t.TempDir()
	oldHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", oldHome)

	initOnce = sync.Once{}
	encKey = nil
	configDir = ""
	configFile = ""

	cfg := DefaultConfig()
	cfg.Backend = "vllm"
	cfg.ServePort = 9999
	cfg.APIKeys["cloud"] = "test-key"

	if err := SaveConfig(cfg); err != nil {
		t.Fatalf("SaveConfig failed: %v", err)
	}

	initOnce = sync.Once{}
	encKey = nil
	configDir = ""
	configFile = ""

	loaded, err := LoadConfig()
	if err != nil {
		t.Fatalf("LoadConfig failed: %v", err)
	}
	if loaded.Backend != "vllm" {
		t.Errorf("expected backend vllm, got %s", loaded.Backend)
	}
	if loaded.ServePort != 9999 {
		t.Errorf("expected port 9999, got %d", loaded.ServePort)
	}
	if loaded.APIKeys["cloud"] != "test-key" {
		t.Errorf("expected cloud key 'test-key', got '%s'", loaded.APIKeys["cloud"])
	}
}

func TestLogOperation(t *testing.T) {
	tmpDir := t.TempDir()
	oldHome := os.Getenv("HOME")
	os.Setenv("HOME", tmpDir)
	defer os.Setenv("HOME", oldHome)

	InitLogger()
	if err := LogOperation("test-cmd", "arg1 arg2", "tester", "ok", "detail", false); err != nil {
		t.Fatalf("LogOperation failed: %v", err)
	}

	logs, err := QueryLogs(10)
	if err != nil {
		t.Fatalf("QueryLogs failed: %v", err)
	}
	if len(logs) != 1 {
		t.Fatalf("expected 1 log entry, got %d", len(logs))
	}
	if logs[0].Command != "test-cmd" {
		t.Errorf("expected command 'test-cmd', got '%s'", logs[0].Command)
	}
	if logs[0].Status != "ok" {
		t.Errorf("expected status 'ok', got '%s'", logs[0].Status)
	}
	if logs[0].Args != "arg1 arg2" {
		t.Errorf("expected args 'arg1 arg2', got '%s'", logs[0].Args)
	}
}

func TestDefaultConfig(t *testing.T) {
	cfg := DefaultConfig()
	if cfg.Backend != "vllm" {
		t.Errorf("expected default backend vllm, got %s", cfg.Backend)
	}
	if cfg.ServePort != 21526 {
		t.Errorf("expected default serve port 21526, got %d", cfg.ServePort)
	}
	if cfg.APIKeys == nil {
		t.Error("expected non-nil APIKeys map")
	}
}
