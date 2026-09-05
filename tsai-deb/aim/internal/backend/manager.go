package backend

import (
	"context"
	"fmt"
	"sync"
)

type Manager struct {
	mu       sync.RWMutex
	backends map[string]Backend
	current  string
}

func NewManager() *Manager {
	return &Manager{
		backends: make(map[string]Backend),
	}
}

func (m *Manager) Register(b Backend) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.backends[b.Name()] = b
}

func (m *Manager) SetCurrent(name string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.backends[name]; !ok {
		return fmt.Errorf("backend %s not registered", name)
	}
	m.current = name
	return nil
}

func (m *Manager) GetCurrent() (Backend, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if m.current == "" {
		return nil, fmt.Errorf("no backend selected")
	}
	b, ok := m.backends[m.current]
	if !ok {
		return nil, fmt.Errorf("current backend %s not registered", m.current)
	}
	return b, nil
}

func (m *Manager) Get(name string) (Backend, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	b, ok := m.backends[name]
	if !ok {
		return nil, fmt.Errorf("backend %s not registered", name)
	}
	return b, nil
}

func (m *Manager) List() []string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var names []string
	for name := range m.backends {
		names = append(names, name)
	}
	return names
}

func (m *Manager) Current() string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.current
}

func (m *Manager) ListModels(ctx context.Context) ([]ModelInfo, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	b, err := m.GetCurrent()
	if err != nil {
		return nil, err
	}
	return b.ListModels(ctx)
}

func (m *Manager) Chat(ctx context.Context, req ChatRequest) (<-chan ChatResponse, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	b, err := m.GetCurrent()
	if err != nil {
		return nil, err
	}
	return b.Chat(ctx, req)
}

func (m *Manager) AvailableBackends(ctx context.Context) []string {
	if ctx == nil {
		ctx = context.Background()
	}
	m.mu.RLock()
	defer m.mu.RUnlock()
	var avail []string
	for name, b := range m.backends {
		if b.IsAvailable(ctx) {
			avail = append(avail, name)
		}
	}
	return avail
}
