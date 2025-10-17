package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type telemetryEvent struct {
	Event     string            `json:"event"`
	Timestamp time.Time         `json:"ts"`
	Fields    map[string]string `json:"fields,omitempty"`
}

type telemetryLogger struct {
	path string
	mu   sync.Mutex
}

func newTelemetryLogger(path string) *telemetryLogger {
	dir := filepath.Dir(path)
	_ = os.MkdirAll(dir, 0o755)
	return &telemetryLogger{path: path}
}

func (t *telemetryLogger) Emit(event string, fields map[string]string) {
	if event == "" || t == nil {
		return
	}
	t.mu.Lock()
	defer t.mu.Unlock()

	record := telemetryEvent{
		Event:     event,
		Timestamp: time.Now().UTC(),
		Fields:    fields,
	}
	data, err := json.Marshal(record)
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
