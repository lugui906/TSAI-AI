package backend

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

type VLLMBackend struct {
	baseURL string
	client  *http.Client
}

func NewVLLM(baseURL string) *VLLMBackend {
	return &VLLMBackend{
		baseURL: strings.TrimRight(baseURL, "/"),
		client:  &http.Client{},
	}
}

func (v *VLLMBackend) Name() string { return "vllm" }

type vllmModelList struct {
	Data []struct {
		ID string `json:"id"`
	} `json:"data"`
}

func (v *VLLMBackend) ListModels(ctx context.Context) ([]ModelInfo, error) {
	resp, err := v.client.Get(v.baseURL + "/v1/models")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var list vllmModelList
	if err := json.NewDecoder(resp.Body).Decode(&list); err != nil {
		return nil, err
	}

	var models []ModelInfo
	for _, m := range list.Data {
		models = append(models, ModelInfo{
			Name:    m.ID,
			Backend: "vllm",
		})
	}
	return models, nil
}

type vllmChatReq struct {
	Model    string        `json:"model"`
	Messages []ChatMessage `json:"messages"`
	Stream   bool          `json:"stream"`
}

type vllmChatResp struct {
	Choices []struct {
		Delta struct {
			Content string `json:"content"`
		} `json:"delta"`
		Index int `json:"index"`
	} `json:"choices"`
}

func (v *VLLMBackend) Chat(ctx context.Context, req ChatRequest) (<-chan ChatResponse, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	body := vllmChatReq{
		Model:    req.Model,
		Messages: req.Messages,
		Stream:   req.Stream,
	}
	data, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", v.baseURL+"/v1/chat/completions", bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	httpResp, err := v.client.Do(httpReq)
	if err != nil {
		return nil, err
	}

	ch := make(chan ChatResponse)
	go func() {
		defer httpResp.Body.Close()
		defer close(ch)

		decoder := json.NewDecoder(httpResp.Body)
		for {
			var resp vllmChatResp
			if err := decoder.Decode(&resp); err == io.EOF {
				break
			} else if err != nil {
				ch <- ChatResponse{Content: fmt.Sprintf("error: %v", err), Done: true}
				break
			}
			for _, c := range resp.Choices {
				ch <- ChatResponse{Content: c.Delta.Content, Done: false}
			}
		}
		ch <- ChatResponse{Content: "", Done: true}
	}()
	return ch, nil
}

func (v *VLLMBackend) PullModel(ctx context.Context, name string) error {
	return fmt.Errorf("vLLM does not support model pull; use vLLM CLI directly")
}

func (v *VLLMBackend) DeleteModel(ctx context.Context, name string) error {
	return fmt.Errorf("vLLM does not support model delete via API")
}

func (v *VLLMBackend) IsAvailable(ctx context.Context) bool {
	resp, err := v.client.Get(v.baseURL + "/health")
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == 200
}
