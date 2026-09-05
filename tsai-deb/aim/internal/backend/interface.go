package backend

import "context"

type ChatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type ChatRequest struct {
	Model    string        `json:"model"`
	Messages []ChatMessage `json:"messages"`
	Stream   bool          `json:"stream"`
}

type ChatResponse struct {
	Content string `json:"content"`
	Done    bool   `json:"done"`
}

type ModelInfo struct {
	Name       string `json:"name"`
	Size       int64  `json:"size"`
	Backend    string `json:"backend"`
	Running    bool   `json:"running"`
}

type Backend interface {
	Name() string
	ListModels(ctx context.Context) ([]ModelInfo, error)
	Chat(ctx context.Context, req ChatRequest) (<-chan ChatResponse, error)
	PullModel(ctx context.Context, name string) error
	DeleteModel(ctx context.Context, name string) error
	IsAvailable(ctx context.Context) bool
}
