package main

import (
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

type uiConfig struct {
	Pinned []string `yaml:"pinned,omitempty"`
}

func loadUIConfig() (*uiConfig, string) {
	configDir := resolveConfigDir()
	if err := os.MkdirAll(configDir, 0o755); err != nil {
		return &uiConfig{}, filepath.Join(configDir, "ui.yaml")
	}
	path := filepath.Join(configDir, "ui.yaml")
	data, err := os.ReadFile(path)
	if err != nil {
		return &uiConfig{}, path
	}
	var cfg uiConfig
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return &uiConfig{}, path
	}
	return &cfg, path
}

func saveUIConfig(cfg *uiConfig, path string) error {
	if cfg == nil {
		cfg = &uiConfig{}
	}
	data, err := yaml.Marshal(cfg)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}

func resolveConfigDir() string {
	dir, err := os.UserConfigDir()
	if err != nil {
		dir = "."
	}
	return filepath.Join(dir, "gpt-creator")
}
