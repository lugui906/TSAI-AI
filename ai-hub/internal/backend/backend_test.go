package backend

import (
	"context"
	"testing"
)

func TestManagerRegister(t *testing.T) {
	mgr := NewManager()
	if len(mgr.List()) != 0 {
		t.Errorf("expected empty manager, got %d backends", len(mgr.List()))
	}

	vllm := NewVLLM("http://localhost:8000")
	mgr.Register(vllm)

	backends := mgr.List()
	if len(backends) != 1 {
		t.Fatalf("expected 1 backend, got %d", len(backends))
	}
	if backends[0] != "vllm" {
		t.Errorf("expected 'vllm', got '%s'", backends[0])
	}
}

func TestManagerSetCurrent(t *testing.T) {
	mgr := NewManager()
	mgr.Register(NewVLLM("http://localhost:8000"))

	if err := mgr.SetCurrent("vllm"); err != nil {
		t.Fatalf("SetCurrent failed: %v", err)
	}
	if mgr.Current() != "vllm" {
		t.Errorf("expected current 'vllm', got '%s'", mgr.Current())
	}

	if err := mgr.SetCurrent("nonexistent"); err == nil {
		t.Error("expected error for nonexistent backend")
	}
}

func TestManagerGet(t *testing.T) {
	mgr := NewManager()
	vllm := NewVLLM("http://localhost:8000")
	mgr.Register(vllm)

	got, err := mgr.Get("vllm")
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}
	if got.Name() != "vllm" {
		t.Errorf("expected 'vllm', got '%s'", got.Name())
	}

	_, err = mgr.Get("nonexistent")
	if err == nil {
		t.Error("expected error for nonexistent backend")
	}
}

func TestManagerGetCurrentNoBackend(t *testing.T) {
	mgr := NewManager()
	_, err := mgr.GetCurrent()
	if err == nil {
		t.Error("expected error when no backend selected")
	}
}

func TestBackendNames(t *testing.T) {
	if name := NewVLLM("http://localhost:8000").Name(); name != "vllm" {
		t.Errorf("expected 'vllm', got '%s'", name)
	}
	if name := NewCloud("http://localhost:8080", "key").Name(); name != "cloud" {
		t.Errorf("expected 'cloud', got '%s'", name)
	}
}

func TestVLLMPullDeleteError(t *testing.T) {
	v := NewVLLM("http://localhost:8000")
	if err := v.PullModel(context.Background(), "test"); err == nil {
		t.Error("expected error for vLLM pull")
	}
	if err := v.DeleteModel(context.Background(), "test"); err == nil {
		t.Error("expected error for vLLM delete")
	}
}

func TestCloudPullDeleteError(t *testing.T) {
	c := NewCloud("http://localhost:8080", "key")
	if err := c.PullModel(context.Background(), "test"); err == nil {
		t.Error("expected error for cloud pull")
	}
	if err := c.DeleteModel(context.Background(), "test"); err == nil {
		t.Error("expected error for cloud delete")
	}
}
