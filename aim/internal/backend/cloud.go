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

type CloudBackend struct {
	baseURL  string
	apiKey   string
	client   *http.Client
}

func NewCloud(baseURL, apiKey string) *CloudBackend {
	return &CloudBackend{
		baseURL: strings.TrimRight(baseURL, "/"),
		apiKey:  apiKey,
		client:  &http.Client{},
	}
}

func (c *CloudBackend) Name() string { return "cloud" }

type cloudModelList struct {
	Data []struct {
		ID string `json:"id"`
	} `json:"data"`
}

func (c *CloudBackend) ListModels(ctx context.Context) ([]ModelInfo, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.baseURL+"/v1/models", nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	resp, err := c.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var list cloudModelList
	if err := json.NewDecoder(resp.Body).Decode(&list); err != nil {
		return nil, err
	}

	var models []ModelInfo
	for _, m := range list.Data {
		models = append(models, ModelInfo{
			Name:    m.ID,
			Backend: "cloud",
		})
	}
	return models, nil
}

type cloudChatReq struct {
	Model    string        `json:"model"`
	Messages []ChatMessage `json:"messages"`
	Stream   bool          `json:"stream"`
}

type cloudChatResp struct {
	Choices []struct {
		Delta struct {
			Content string `json:"content"`
		} `json:"delta"`
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
		Index int `json:"index"`
	} `json:"choices"`
}

func (c *CloudBackend) Chat(ctx context.Context, req ChatRequest) (<-chan ChatResponse, error) {
	body := cloudChatReq{
		Model:    req.Model,
		Messages: req.Messages,
		Stream:   req.Stream,
	}
	data, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/v1/chat/completions", bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)

	httpResp, err := c.client.Do(httpReq)
	if err != nil {
		return nil, err
	}

	ch := make(chan ChatResponse)
	go func() {
		defer httpResp.Body.Close()
		defer close(ch)

		if req.Stream {
			decoder := json.NewDecoder(httpResp.Body)
			for {
				var resp cloudChatResp
				if err := decoder.Decode(&resp); err == io.EOF {
					break
				} else if err != nil {
					ch <- ChatResponse{Content: fmt.Sprintf("error: %v", err), Done: true}
					break
				}
				for _, choice := range resp.Choices {
					ch <- ChatResponse{Content: choice.Delta.Content, Done: false}
				}
			}
			ch <- ChatResponse{Content: "", Done: true}
		} else {
			var resp cloudChatResp
			if err := json.NewDecoder(httpResp.Body).Decode(&resp); err != nil {
				ch <- ChatResponse{Content: fmt.Sprintf("error: %v", err), Done: true}
				return
			}
			for _, choice := range resp.Choices {
				ch <- ChatResponse{Content: choice.Message.Content, Done: true}
			}
		}
	}()
	return ch, nil
}

func (c *CloudBackend) PullModel(ctx context.Context, name string) error {
	return fmt.Errorf("cloud API does not support model pull")
}

func (c *CloudBackend) DeleteModel(ctx context.Context, name string) error {
	return fmt.Errorf("cloud API does not support model delete")
}

func (c *CloudBackend) IsAvailable(ctx context.Context) bool {
	req, err := http.NewRequestWithContext(ctx, "GET", c.baseURL+"/v1/models", nil)
	if err != nil {
		return false
	}
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	resp, err := c.client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == 200
}
