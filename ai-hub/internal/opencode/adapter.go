package opencode

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

const (
	OpenClawRunSessionKey = "agent:default:aim"
)

// Adapter builds engine-specific CLI argv so every aim command works with
// whichever engine is active (opencode or openclaw).
type Adapter struct {
	binary   string
	openclaw bool
}

// CurrentAdapter returns the adapter for the active, persisted engine.
func CurrentAdapter() *Adapter {
	binary := EnginePath
	return &Adapter{binary: binary, openclaw: binary == OpenClawEngineName}
}

func (a *Adapter) Binary() string   { return a.binary }
func (a *Adapter) IsOpenClaw() bool { return a.openclaw }

// baseArgs returns the leading argv shared by every openclaw invocation.
// --log-level error keeps openclaw's noisy informational logging off the
// terminal; real errors are still reported.
func (a *Adapter) baseArgs() []string {
	if a.openclaw {
		return []string{"--log-level", "error"}
	}
	return nil
}

// RunArgs builds argv for a one-shot prompt run.
// auto enables unrestricted tool access (opencode only); continueSession keeps
// the same conversation across invocations.
func (a *Adapter) RunArgs(prompt string, auto, continueSession bool) []string {
	if a.openclaw {
		key := OpenClawRunSessionKey
		if !continueSession {
			key = fmt.Sprintf("agent:default:aim:%d", time.Now().UnixNano())
		}
		return append(a.baseArgs(), "agent", "--local", "--json", "--session-key", key, "--message", prompt)
	}
	args := []string{"run", "--format", "json"}
	if auto {
		args = append(args, "--auto")
	}
	if continueSession {
		args = append(args, "--continue")
	}
	return append(args, prompt)
}

func (a *Adapter) ChatArgs() []string {
	if a.openclaw {
		return append(a.baseArgs(), "chat", "--local")
	}
	return []string{"run"}
}

func (a *Adapter) ModelsArgs(extra string) []string {
	if a.openclaw {
		if extra != "" {
			return append(a.baseArgs(), "models", "list", "--provider", extra)
		}
		return append(a.baseArgs(), "models", "list")
	}
	if extra != "" {
		return []string{"models", extra}
	}
	return []string{"models"}
}

func (a *Adapter) ProvidersArgs() []string {
	if a.openclaw {
		return append(a.baseArgs(), "configure", "--section", "model")
	}
	return []string{"providers"}
}

// ExtractText parses engine output into the text parts to print.
func (a *Adapter) ExtractText(output string) []string {
	if a.openclaw {
		return extractOpenClawText(output)
	}
	return extractOpenCodeText(output)
}

func extractOpenCodeText(output string) []string {
	var texts []string
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var evt struct {
			Type string `json:"type"`
			Part struct {
				Text string `json:"text"`
			} `json:"part"`
		}
		if err := json.Unmarshal([]byte(line), &evt); err != nil {
			continue
		}
		if evt.Type == "text" && evt.Part.Text != "" {
			texts = append(texts, evt.Part.Text)
		}
	}
	return texts
}

func extractOpenClawText(output string) []string {
	var doc struct {
		Payloads []struct {
			Text string `json:"text"`
		} `json:"payloads"`
	}
	if err := json.Unmarshal([]byte(output), &doc); err != nil {
		return nil
	}
	var texts []string
	for _, p := range doc.Payloads {
		if p.Text != "" {
			texts = append(texts, p.Text)
		}
	}
	return texts
}
