package server

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestNewServer(t *testing.T) {
	svr := NewServer(21526, "test-token")
	if svr.port != 21526 {
		t.Errorf("expected port 21526, got %d", svr.port)
	}
	if svr.Token() != "test-token" {
		t.Errorf("expected 'test-token', got '%s'", svr.Token())
	}
}

func TestGenerateToken(t *testing.T) {
	token := generateToken()
	if len(token) != 64 {
		t.Errorf("expected 64-char hex token, got %d chars", len(token))
	}
}

func TestAutoGenerateToken(t *testing.T) {
	svr := NewServer(21526, "")
	if svr.Token() == "" {
		t.Error("expected auto-generated token")
	}
	if len(svr.Token()) != 64 {
		t.Errorf("expected 64-char token, got %d", len(svr.Token()))
	}
}

func TestSetToken(t *testing.T) {
	svr := NewServer(21526, "")
	svr.SetToken("new-token")
	if svr.Token() != "new-token" {
		t.Errorf("expected 'new-token', got '%s'", svr.Token())
	}
}

func TestHealthEndpoint(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" {
			w.WriteHeader(http.StatusOK)
			w.Write([]byte(`{"status":"ok"}`))
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/health")
	if err != nil {
		t.Fatalf("health check failed: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected 200, got %d", resp.StatusCode)
	}
}

func TestAuthMiddleware(t *testing.T) {
	svr := NewServer(21526, "valid-token")

	handler := svr.authMiddleware(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	tests := []struct {
		name       string
		authHeader string
		wantStatus int
	}{
		{"valid bearer", "Bearer valid-token", http.StatusOK},
		{"valid raw", "valid-token", http.StatusOK},
		{"invalid token", "Bearer wrong-token", http.StatusUnauthorized},
		{"no token", "", http.StatusUnauthorized},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest("GET", "/v1/chat", nil)
			if tt.authHeader != "" {
				req.Header.Set("Authorization", tt.authHeader)
			}
			w := httptest.NewRecorder()
			handler(w, req)
			if w.Code != tt.wantStatus {
				t.Errorf("expected status %d, got %d", tt.wantStatus, w.Code)
			}
		})
	}
}

func TestAuthMiddlewareQueryToken(t *testing.T) {
	svr := NewServer(21526, "valid-token")

	handler := svr.authMiddleware(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	// Token via query param
	req := httptest.NewRequest("GET", "/v1/chat?token=valid-token", nil)
	w := httptest.NewRecorder()
	handler(w, req)
	if w.Code != http.StatusOK {
		t.Errorf("expected 200 for query param token, got %d", w.Code)
	}
}

func TestHandleChat(t *testing.T) {
	svr := NewServer(21526, "test-token")

	handler := svr.authMiddleware(svr.handleChat)

	body := `{"model":"test-model","prompt":"hello"}`
	req := httptest.NewRequest("POST", "/v1/chat", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer test-token")
	req.Header.Set("Content-Type", "application/json")

	w := httptest.NewRecorder()
	handler(w, req)
	if w.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), "test-model") {
		t.Errorf("response should contain model name: %s", w.Body.String())
	}
}

func TestHandleChatMethodNotAllowed(t *testing.T) {
	svr := NewServer(21526, "test-token")

	handler := svr.authMiddleware(svr.handleChat)
	req := httptest.NewRequest("GET", "/v1/chat", nil)
	req.Header.Set("Authorization", "Bearer test-token")

	w := httptest.NewRecorder()
	handler(w, req)
	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected 405, got %d", w.Code)
	}
}

func TestHandleModels(t *testing.T) {
	svr := NewServer(21526, "test-token")
	handler := svr.authMiddleware(svr.handleModels)

	req := httptest.NewRequest("GET", "/v1/models", nil)
	req.Header.Set("Authorization", "Bearer test-token")

	w := httptest.NewRecorder()
	handler(w, req)
	if w.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), "list") {
		t.Errorf("response should contain object type: %s", w.Body.String())
	}
}
