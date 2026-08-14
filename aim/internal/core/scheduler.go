package core

import (
	"context"
	"sync"
	"time"
)

type TaskStatus string

const (
	TaskPending    TaskStatus = "pending"
	TaskRunning    TaskStatus = "running"
	TaskCompleted  TaskStatus = "completed"
	TaskFailed     TaskStatus = "failed"
)

type Task struct {
	ID        string     `json:"id"`
	Command   string     `json:"command"`
	Args      []string   `json:"args"`
	Status    TaskStatus `json:"status"`
	CreatedAt time.Time  `json:"created_at"`
	Result    string     `json:"result,omitempty"`
	Error     string     `json:"error,omitempty"`
}

type TaskQueue struct {
	mu       sync.Mutex
	tasks    []*Task
	cond     *sync.Cond
	stopCh   chan struct{}
	maxParallel int
}

func NewTaskQueue(maxParallel int) *TaskQueue {
	tq := &TaskQueue{
		tasks:       make([]*Task, 0),
		stopCh:      make(chan struct{}),
		maxParallel: maxParallel,
	}
	tq.cond = sync.NewCond(&tq.mu)
	return tq
}

func (tq *TaskQueue) Add(task *Task) {
	tq.mu.Lock()
	defer tq.mu.Unlock()
	tq.tasks = append(tq.tasks, task)
	tq.cond.Signal()
}

func (tq *TaskQueue) Next() (*Task, bool) {
	tq.mu.Lock()
	defer tq.mu.Unlock()
	for len(tq.tasks) == 0 {
		select {
		case <-tq.stopCh:
			return nil, false
		default:
			tq.cond.Wait()
		}
	}
	task := tq.tasks[0]
	tq.tasks = tq.tasks[1:]
	return task, true
}

func (tq *TaskQueue) Stop() {
	close(tq.stopCh)
	tq.cond.Broadcast()
}

type Session struct {
	ID        string
	CreatedAt time.Time
	Tasks     []*Task
}

type SessionPool struct {
	mu       sync.RWMutex
	sessions map[string]*Session
}

func NewSessionPool() *SessionPool {
	return &SessionPool{
		sessions: make(map[string]*Session),
	}
}

func (sp *SessionPool) Create(id string) *Session {
	sp.mu.Lock()
	defer sp.mu.Unlock()
	s := &Session{
		ID:        id,
		CreatedAt: time.Now(),
	}
	sp.sessions[id] = s
	return s
}

func (sp *SessionPool) Get(id string) (*Session, bool) {
	sp.mu.RLock()
	defer sp.mu.RUnlock()
	s, ok := sp.sessions[id]
	return s, ok
}

func (sp *SessionPool) Delete(id string) {
	sp.mu.Lock()
	defer sp.mu.Unlock()
	delete(sp.sessions, id)
}

type Scheduler struct {
	Queue       *TaskQueue
	Sessions    *SessionPool
	ctx         context.Context
	cancel      context.CancelFunc
	wg          sync.WaitGroup
}

func NewScheduler(maxParallel int) *Scheduler {
	ctx, cancel := context.WithCancel(context.Background())
	return &Scheduler{
		Queue:    NewTaskQueue(maxParallel),
		Sessions: NewSessionPool(),
		ctx:      ctx,
		cancel:   cancel,
	}
}

func (s *Scheduler) Start() {
	for i := 0; i < s.Queue.maxParallel; i++ {
		s.wg.Add(1)
		go s.worker(i)
	}
}

func (s *Scheduler) Stop() {
	s.cancel()
	s.Queue.Stop()
	s.wg.Wait()
}

func (s *Scheduler) worker(id int) {
	defer s.wg.Done()
	for {
		task, ok := s.Queue.Next()
		if !ok {
			return
		}
		task.Status = TaskRunning
		select {
		case <-s.ctx.Done():
			task.Status = TaskFailed
			task.Error = "scheduler stopped"
			return
		default:
		}
	}
}
