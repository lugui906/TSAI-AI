package core

import (
	"testing"
	"time"
)

func TestNewTaskQueue(t *testing.T) {
	tq := NewTaskQueue(3)
	if tq == nil {
		t.Fatal("expected non-nil TaskQueue")
	}
	if tq.maxParallel != 3 {
		t.Errorf("expected maxParallel 3, got %d", tq.maxParallel)
	}
}

func TestTaskQueueAddAndNext(t *testing.T) {
	tq := NewTaskQueue(2)

	task := &Task{
		ID:      "test-1",
		Command: "echo",
		Status:  TaskPending,
	}
	tq.Add(task)

	got, ok := tq.Next()
	if !ok {
		t.Fatal("expected ok from Next")
	}
	if got.ID != "test-1" {
		t.Errorf("expected task ID 'test-1', got '%s'", got.ID)
	}
	if got.Command != "echo" {
		t.Errorf("expected command 'echo', got '%s'", got.Command)
	}
}

func TestTaskQueueOrder(t *testing.T) {
	tq := NewTaskQueue(1)

	tq.Add(&Task{ID: "first"})
	tq.Add(&Task{ID: "second"})
	tq.Add(&Task{ID: "third"})

	if task, _ := tq.Next(); task.ID != "first" {
		t.Errorf("expected 'first', got '%s'", task.ID)
	}
	if task, _ := tq.Next(); task.ID != "second" {
		t.Errorf("expected 'second', got '%s'", task.ID)
	}
	if task, _ := tq.Next(); task.ID != "third" {
		t.Errorf("expected 'third', got '%s'", task.ID)
	}
}

func TestTaskStatusValues(t *testing.T) {
	if TaskPending != "pending" {
		t.Errorf("expected 'pending', got '%s'", TaskPending)
	}
	if TaskRunning != "running" {
		t.Errorf("expected 'running', got '%s'", TaskRunning)
	}
	if TaskCompleted != "completed" {
		t.Errorf("expected 'completed', got '%s'", TaskCompleted)
	}
	if TaskFailed != "failed" {
		t.Errorf("expected 'failed', got '%s'", TaskFailed)
	}
}

func TestNewSessionPool(t *testing.T) {
	sp := NewSessionPool()
	if sp == nil {
		t.Fatal("expected non-nil SessionPool")
	}
}

func TestSessionPoolCreateAndGet(t *testing.T) {
	sp := NewSessionPool()
	s := sp.Create("session-1")
	if s.ID != "session-1" {
		t.Errorf("expected ID 'session-1', got '%s'", s.ID)
	}
	if s.CreatedAt.IsZero() {
		t.Error("expected non-zero CreatedAt")
	}

	got, ok := sp.Get("session-1")
	if !ok {
		t.Fatal("expected to find session")
	}
	if got.ID != "session-1" {
		t.Errorf("expected ID 'session-1', got '%s'", got.ID)
	}
}

func TestSessionPoolDelete(t *testing.T) {
	sp := NewSessionPool()
	sp.Create("session-1")
	sp.Delete("session-1")

	_, ok := sp.Get("session-1")
	if ok {
		t.Error("expected session to be deleted")
	}
}

func TestSessionPoolGetNonexistent(t *testing.T) {
	sp := NewSessionPool()
	_, ok := sp.Get("nonexistent")
	if ok {
		t.Error("expected false for nonexistent session")
	}
}

func TestNewScheduler(t *testing.T) {
	s := NewScheduler(2)
	if s == nil {
		t.Fatal("expected non-nil Scheduler")
	}
	if s.Queue.maxParallel != 2 {
		t.Errorf("expected maxParallel 2, got %d", s.Queue.maxParallel)
	}
}

func TestSchedulerStartStop(t *testing.T) {
	s := NewScheduler(2)
	go func() {
		time.Sleep(50 * time.Millisecond)
		s.Stop()
	}()
	s.Start()
}

func TestTaskDefaults(t *testing.T) {
	task := &Task{
		ID:      "test",
		Command: "cmd",
	}
	if task.Status != "" {
		t.Errorf("expected empty status, got '%s'", task.Status)
	}
	if !task.CreatedAt.IsZero() {
		t.Error("expected zero CreatedAt")
	}
}
