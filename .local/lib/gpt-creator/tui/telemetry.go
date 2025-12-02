package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type telemetryEvent struct {
	SessionID string            `json:"session_id"`
	UserID    string            `json:"user_id,omitempty"`
	Timestamp time.Time         `json:"timestamp"`
	Event     string            `json:"event"`
	Project   string            `json:"project,omitempty"`
	Feature   string            `json:"feature,omitempty"`
	ItemID    string            `json:"item_id,omitempty"`
	ExtraJSON map[string]string `json:"extra_json,omitempty"`
}

type telemetryLogger struct {
	path      string
	sessionID string
	userID    string
	mu        sync.Mutex
}

func newTelemetryLogger(path, sessionID, userID string) *telemetryLogger {
	dir := filepath.Dir(path)
	_ = os.MkdirAll(dir, 0o755)
	return &telemetryLogger{
		path:      path,
		sessionID: strings.TrimSpace(sessionID),
		userID:    strings.TrimSpace(userID),
	}
}

func (t *telemetryLogger) Emit(event telemetryEvent) {
	if t == nil || strings.TrimSpace(event.Event) == "" {
		return
	}
	if event.SessionID == "" {
		event.SessionID = t.sessionID
	}
	userID := strings.TrimSpace(event.UserID)
	if userID == "" {
		userID = t.userID
	}
	event.UserID = strings.TrimSpace(userID)
	if event.Timestamp.IsZero() {
		event.Timestamp = time.Now().UTC()
	}
	if len(event.ExtraJSON) == 0 {
		event.ExtraJSON = nil
	}

	t.mu.Lock()
	defer t.mu.Unlock()

	data, err := json.Marshal(event)
	if err != nil {
		return
	}
	data = append(data, '\n')
	f, err := os.OpenFile(t.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = f.Write(data)
}

func newTelemetrySessionID() string {
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err == nil {
		return hex.EncodeToString(buf)
	}
	return fmt.Sprintf("%x", time.Now().UnixNano())
}

func resolveTelemetryUserID() string {
	candidates := []string{
		os.Getenv("GC_ANALYTICS_USER_ID"),
		os.Getenv("GC_REPORTER"),
		os.Getenv("USER"),
		os.Getenv("USERNAME"),
	}
	for _, candidate := range candidates {
		if trimmed := strings.TrimSpace(candidate); trimmed != "" {
			return trimmed
		}
	}
	return ""
}
