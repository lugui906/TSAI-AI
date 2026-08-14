package system

import (
	"os"
	"testing"
)

func TestGetHardwareInfo(t *testing.T) {
	info, err := GetHardwareInfo()
	if err != nil {
		t.Fatalf("GetHardwareInfo failed: %v", err)
	}
	if info == nil {
		t.Fatal("expected non-nil HardwareInfo")
	}
	if info.Hostname == "" {
		t.Error("expected non-empty hostname")
	}
	hostname, _ := os.Hostname()
	if info.Hostname != hostname {
		t.Errorf("expected hostname '%s', got '%s'", hostname, info.Hostname)
	}
	if info.OS != "linux" {
		t.Errorf("expected OS 'linux', got '%s'", info.OS)
	}
	if info.Architecture == "" {
		t.Error("expected non-empty architecture")
	}
}

func TestExecCommand(t *testing.T) {
	output, err := ExecCommand("echo", "hello")
	if err != nil {
		t.Fatalf("ExecCommand failed: %v", err)
	}
	if output != "hello\n" {
		t.Errorf("expected 'hello\\n', got '%s'", output)
	}
}

func TestExecCommandWithInput(t *testing.T) {
	output, err := ExecCommandWithInput("world", "cat")
	if err != nil {
		t.Fatalf("ExecCommandWithInput failed: %v", err)
	}
	if output != "world" {
		t.Errorf("expected 'world', got '%s'", output)
	}
}

func TestExecCommandError(t *testing.T) {
	_, err := ExecCommand("nonexistent-command-12345")
	if err == nil {
		t.Error("expected error for nonexistent command")
	}
}

func TestKillProcessError(t *testing.T) {
	err := KillProcess(999999999)
	if err == nil {
		t.Error("expected error for non-existent process")
	}
}

func TestVMInterface(t *testing.T) {
	vm := NewVMInterface()
	if vm == nil {
		t.Fatal("expected non-nil VMInterface")
	}
}

func TestParseInt(t *testing.T) {
	if n := parseInt("123"); n != 123 {
		t.Errorf("expected 123, got %d", n)
	}
	if n := parseInt("abc"); n != 0 {
		t.Errorf("expected 0, got %d", n)
	}
	if n := parseInt(""); n != 0 {
		t.Errorf("expected 0, got %d", n)
	}
}
