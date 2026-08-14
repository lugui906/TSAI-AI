package storage

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"
)

var (
	encKey     []byte
	configDir  string
	configFile string
	initOnce   sync.Once
)

type Config struct {
	APIKeys     map[string]string `json:"api_keys"`
	RemoteToken string            `json:"remote_token"`
	Backend     string            `json:"backend"`
	VLLMHost    string            `json:"vllm_host"`
	CloudURL    string            `json:"cloud_url"`
	ServePort   int               `json:"serve_port"`
}

func DefaultConfig() *Config {
	return &Config{
		APIKeys:   make(map[string]string),
		Backend:   "vllm",
		VLLMHost:  "http://localhost:8000",
		ServePort: 21526,
	}
}

func ensureInit() error {
	var initErr error
	initOnce.Do(func() {
		home, err := os.UserHomeDir()
		if err != nil {
			initErr = err
			return
		}
		configDir = filepath.Join(home, ".config", "aim")
		if err := os.MkdirAll(configDir, 0700); err != nil {
			initErr = err
			return
		}
		configFile = filepath.Join(configDir, "config.json.enc")
		keyFile := filepath.Join(configDir, ".key")
		if _, err := os.Stat(keyFile); os.IsNotExist(err) {
			key := make([]byte, 32)
			if _, err := rand.Read(key); err != nil {
				initErr = err
				return
			}
			if err := os.WriteFile(keyFile, key, 0600); err != nil {
				initErr = err
				return
			}
			encKey = key
		} else {
			key, err := os.ReadFile(keyFile)
			if err != nil {
				initErr = err
				return
			}
			encKey = key
		}
	})
	return initErr
}

func encrypt(plaintext []byte) ([]byte, error) {
	block, err := aes.NewCipher(encKey)
	if err != nil {
		return nil, err
	}
	aesGCM, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	nonce := make([]byte, aesGCM.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, err
	}
	return aesGCM.Seal(nonce, nonce, plaintext, nil), nil
}

func decrypt(ciphertext []byte) ([]byte, error) {
	block, err := aes.NewCipher(encKey)
	if err != nil {
		return nil, err
	}
	aesGCM, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	nonceSize := aesGCM.NonceSize()
	if len(ciphertext) < nonceSize {
		return nil, errors.New("ciphertext too short")
	}
	nonce, ciphertext := ciphertext[:nonceSize], ciphertext[nonceSize:]
	return aesGCM.Open(nil, nonce, ciphertext, nil)
}

func SaveConfig(cfg *Config) error {
	if err := ensureInit(); err != nil {
		return err
	}
	data, err := json.Marshal(cfg)
	if err != nil {
		return err
	}
	enc, err := encrypt(data)
	if err != nil {
		return err
	}
	return os.WriteFile(configFile, enc, 0600)
}

func LoadConfig() (*Config, error) {
	if err := ensureInit(); err != nil {
		return nil, err
	}
	if _, err := os.Stat(configFile); os.IsNotExist(err) {
		cfg := DefaultConfig()
		if err := SaveConfig(cfg); err != nil {
			return nil, err
		}
		return cfg, nil
	}
	enc, err := os.ReadFile(configFile)
	if err != nil {
		return nil, err
	}
	data, err := decrypt(enc)
	if err != nil {
		return nil, err
	}
	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}
	if cfg.APIKeys == nil {
		cfg.APIKeys = make(map[string]string)
	}
	return &cfg, nil
}

type LogEntry struct {
	Time    string `json:"time"`
	Command string `json:"command"`
	Args    string `json:"args"`
	Status  string `json:"status"`
	Detail  string `json:"detail"`
	Remote  bool   `json:"remote"`
}

var (
	logMu   sync.Mutex
	logFile string
	logInit sync.Once
)

func InitLogger() error {
	var err error
	logInit.Do(func() {
		home, e := os.UserHomeDir()
		if e != nil {
			err = e
			return
		}
		logDir := filepath.Join(home, ".local", "share", "aim")
		if e := os.MkdirAll(logDir, 0700); e != nil {
			err = e
			return
		}
		logFile = filepath.Join(logDir, "aim.log.jsonl")
	})
	return err
}

func LogOperation(cmd, args, user, status, detail string, remote bool) error {
	InitLogger()
	logMu.Lock()
	defer logMu.Unlock()

	f, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer f.Close()

	entry := LogEntry{
		Time:    time.Now().Format(time.RFC3339),
		Command: cmd,
		Args:    args,
		Status:  status,
		Detail:  detail,
		Remote:  remote,
	}
	data, err := json.Marshal(entry)
	if err != nil {
		return err
	}
	_, err = f.Write(append(data, '\n'))
	return err
}

func QueryLogs(limit int) ([]LogEntry, error) {
	InitLogger()
	if limit <= 0 {
		limit = 50
	}
	data, err := os.ReadFile(logFile)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}

	lines := splitLines(string(data))
	var entries []LogEntry
	start := 0
	if len(lines) > limit {
		start = len(lines) - limit
	}
	for i := start; i < len(lines); i++ {
		if lines[i] == "" {
			continue
		}
		var e LogEntry
		if err := json.Unmarshal([]byte(lines[i]), &e); err == nil {
			entries = append(entries, e)
		}
	}
	return entries, nil
}

func splitLines(s string) []string {
	var lines []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == '\n' {
			lines = append(lines, s[start:i])
			start = i + 1
		}
	}
	if start < len(s) {
		lines = append(lines, s[start:])
	}
	return lines
}
