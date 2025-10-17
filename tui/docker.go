package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os/exec"
	"strings"
	"time"
)

type composeServiceInfo struct {
	Service        string
	Name           string
	State          string
	Status         string
	Health         string
	Ports          string
	Endpoint       string
	Latency        string
	Restarts       int
	HealthJSON     string
	HasHealthcheck bool
	LogTail        []string
	Endpoints      []serviceEndpoint
}

type composeRow struct {
	Name    string `json:"Name"`
	Service string `json:"Service"`
	State   string `json:"State"`
	Status  string `json:"Status"`
	Ports   string `json:"Ports"`
}

type probeSpec struct {
	Port string
	Path string
}

type serviceEndpoint struct {
	URL        string `json:"url"`
	Path       string `json:"path"`
	Host       string `json:"host,omitempty"`
	Port       string `json:"port,omitempty"`
	Healthy    bool   `json:"healthy"`
	StatusCode int    `json:"statusCode,omitempty"`
	LatencyMS  int    `json:"latencyMs,omitempty"`
	Error      string `json:"error,omitempty"`
}

type probeResult struct {
	Latency   time.Duration
	Status    int
	Err       error
	IsHealthy bool
}

type containerDetails struct {
	HealthStatus   string
	HealthJSON     string
	HasHealthcheck bool
	RestartCount   int
}

var serviceProbeMap = map[string][]probeSpec{
	"api": {
		{Port: "3000", Path: "/health"},
	},
	"web": {
		{Port: "5173", Path: "/"},
		{Port: "8080", Path: "/"},
	},
	"admin": {
		{Port: "5174", Path: "/admin/"},
	},
	"proxy": {
		{Port: "8080", Path: "/"},
		{Port: "8080", Path: "/admin/"},
	},
}

func gatherServiceItems(project *discoveredProject, dockerAvailable bool) ([]featureItemDefinition, error) {
	if project == nil {
		return nil, fmt.Errorf("project required")
	}
	if !dockerAvailable {
		return nil, fmt.Errorf("Docker CLI not available")
	}

	services, err := composeServices(project.Path)
	if err != nil {
		return nil, err
	}
	if len(services) == 0 {
		return nil, nil
	}

	items := make([]featureItemDefinition, 0, len(services))
	for _, svc := range services {
		title := fmt.Sprintf("%s — %s", svc.Service, svc.State)
		healthLabel := strings.TrimSpace(svc.Health)
		if healthLabel == "" {
			if svc.HasHealthcheck {
				healthLabel = "unknown"
			} else {
				healthLabel = "n/a"
			}
		}
		if healthLabel != "" {
			title = fmt.Sprintf("%s — %s (%s)", svc.Service, svc.State, healthLabel)
		}

		var parts []string
		if svc.Status != "" {
			parts = append(parts, svc.Status)
		}
		if svc.Ports != "" {
			parts = append(parts, "Ports: "+svc.Ports)
		}
		if svc.Restarts > 0 {
			parts = append(parts, fmt.Sprintf("Restarts: %d", svc.Restarts))
		}
		if svc.Endpoint != "" {
			latency := svc.Latency
			if latency == "" {
				latency = "n/a"
			}
			parts = append(parts, fmt.Sprintf("Endpoint: %s (%s)", svc.Endpoint, latency))
		}

		desc := strings.Join(parts, " • ")
		if desc == "" {
			desc = "Service information unavailable"
		}

		meta := map[string]string{
			"serviceRow": "1",
			"service":    svc.Service,
			"container":  svc.Name,
			"state":      svc.State,
			"status":     svc.Status,
			"health":     healthLabel,
			"ports":      svc.Ports,
			"endpoint":   svc.Endpoint,
			"latency":    svc.Latency,
			"restarts":   fmt.Sprintf("%d", svc.Restarts),
			"healthJSON": svc.HealthJSON,
			"hasHealthcheck": func() string {
				if svc.HasHealthcheck {
					return "1"
				}
				return "0"
			}(),
			"requiresDocker": "1",
		}
		if len(svc.LogTail) > 0 {
			meta["logTail"] = strings.Join(svc.LogTail, "\n")
		}
		if len(svc.Endpoints) > 0 {
			if data, err := json.Marshal(svc.Endpoints); err == nil {
				meta["endpoints"] = string(data)
			}
			for _, ep := range svc.Endpoints {
				if ep.Healthy && strings.TrimSpace(ep.URL) != "" {
					meta["primaryEndpoint"] = ep.URL
					break
				}
			}
			if _, ok := meta["primaryEndpoint"]; !ok && strings.TrimSpace(svc.Endpoint) != "" {
				meta["primaryEndpoint"] = svc.Endpoint
			}
		} else if strings.TrimSpace(svc.Endpoint) != "" {
			meta["primaryEndpoint"] = svc.Endpoint
		}
		items = append(items, featureItemDefinition{
			Key:        "service-" + svc.Service,
			Title:      title,
			Desc:       desc,
			PreviewKey: "service:" + svc.Name,
			Meta:       meta,
		})
	}
	return items, nil
}

func composeServices(projectDir string) ([]composeServiceInfo, error) {
	rows, err := composePS(projectDir)
	if err != nil {
		return nil, err
	}

	var services []composeServiceInfo
	for _, row := range rows {
		info := composeServiceInfo{
			Service: row.Service,
			Name:    row.Name,
			State:   fallback(row.State, row.Status),
			Status:  row.Status,
			Ports:   row.Ports,
		}

		if details, err := inspectContainer(row.Name); err == nil {
			info.Health = details.HealthStatus
			info.HealthJSON = details.HealthJSON
			info.HasHealthcheck = details.HasHealthcheck
			info.Restarts = details.RestartCount
		}
		if logs, err := tailContainerLogs(row.Name, 30); err == nil {
			info.LogTail = logs
		}
		info.Endpoints = discoverEndpoints(projectDir, row)
		if len(info.Endpoints) > 0 {
			for _, ep := range info.Endpoints {
				if ep.Healthy && ep.URL != "" {
					info.Endpoint = ep.URL
					if ep.LatencyMS > 0 {
						info.Latency = fmt.Sprintf("%dms", ep.LatencyMS)
					}
					break
				}
			}
		}

		if info.Endpoint == "" && len(info.Endpoints) > 0 {
			first := info.Endpoints[0]
			info.Endpoint = first.URL
			if first.LatencyMS > 0 {
				info.Latency = fmt.Sprintf("%dms", first.LatencyMS)
			}
			if !first.Healthy && first.Error != "" && info.Health == "" {
				info.Health = "unreachable"
			}
		}

		services = append(services, info)
	}
	return services, nil
}

func composePS(projectDir string) ([]composeRow, error) {
	cmd := exec.Command("docker", "compose", "ps", "--format", "json")
	cmd.Dir = projectDir
	out, err := cmd.Output()
	if err != nil {
		return nil, err
	}

	out = bytes.TrimSpace(out)
	if len(out) == 0 {
		return nil, nil
	}

	var rows []composeRow
	if bytes.HasPrefix(out, []byte("[")) {
		if err := json.Unmarshal(out, &rows); err != nil {
			return nil, err
		}
		return rows, nil
	}

	lines := bytes.Split(out, []byte("\n"))
	for _, line := range lines {
		line = bytes.TrimSpace(line)
		if len(line) == 0 {
			continue
		}
		var row composeRow
		if err := json.Unmarshal(line, &row); err == nil {
			rows = append(rows, row)
		}
	}
	return rows, nil
}

func composePort(projectDir, service, targetPort string) (string, string, error) {
	cmd := exec.Command("docker", "compose", "port", service, targetPort)
	cmd.Dir = projectDir
	out, err := cmd.CombinedOutput()
	if err != nil {
		return "", "", err
	}
	line := strings.TrimSpace(string(out))
	if line == "" {
		return "", "", fmt.Errorf("no port mapping")
	}
	host, port, found := strings.Cut(line, ":")
	if !found {
		return "", "", fmt.Errorf("unexpected port output: %s", line)
	}
	host = strings.Trim(host, "[]")
	return host, port, nil
}

func tailContainerLogs(container string, limit int) ([]string, error) {
	if limit <= 0 {
		limit = 20
	}
	cmd := exec.Command("docker", "logs", fmt.Sprintf("--tail=%d", limit), container)
	out, err := cmd.CombinedOutput()
	if err != nil && len(out) == 0 {
		return nil, err
	}
	text := strings.ReplaceAll(string(out), "\r\n", "\n")
	lines := strings.Split(text, "\n")
	var trimmed []string
	for _, line := range lines {
		line = strings.TrimRight(line, " \t")
		if line == "" {
			continue
		}
		trimmed = append(trimmed, line)
	}
	if len(trimmed) > limit {
		trimmed = trimmed[len(trimmed)-limit:]
	}
	if len(trimmed) == 0 && err != nil {
		return nil, err
	}
	return trimmed, nil
}

func sanitizeHost(host string) string {
	switch host {
	case "", "0.0.0.0", "::", "[::]":
		return "localhost"
	default:
		return strings.Trim(host, "[]")
	}
}

func inspectContainer(container string) (containerDetails, error) {
	cmd := exec.Command("docker", "inspect", container)
	out, err := cmd.Output()
	if err != nil {
		return containerDetails{}, err
	}
	var payload []struct {
		RestartCount int `json:"RestartCount"`
		State        struct {
			Status string `json:"Status"`
			Health *struct {
				Status string `json:"Status"`
			} `json:"Health"`
		} `json:"State"`
		Config struct {
			Healthcheck *struct{} `json:"Healthcheck"`
		} `json:"Config"`
	}
	if err := json.Unmarshal(out, &payload); err != nil {
		return containerDetails{}, err
	}
	if len(payload) == 0 {
		return containerDetails{}, fmt.Errorf("no inspect data for %s", container)
	}
	entry := payload[0]
	result := containerDetails{
		RestartCount:   entry.RestartCount,
		HasHealthcheck: entry.Config.Healthcheck != nil,
	}
	if entry.State.Health != nil {
		status := strings.TrimSpace(entry.State.Health.Status)
		if status == "" {
			status = "unknown"
		}
		result.HealthStatus = status
		if data, err := json.Marshal(entry.State.Health); err == nil {
			result.HealthJSON = string(data)
		}
	} else if result.HasHealthcheck {
		result.HealthStatus = strings.TrimSpace(entry.State.Status)
		if result.HealthStatus == "" {
			result.HealthStatus = "starting"
		}
	} else {
		result.HealthStatus = "n/a"
	}
	return result, nil
}

func discoverEndpoints(projectDir string, row composeRow) []serviceEndpoint {
	probes := serviceProbeMap[row.Service]
	results := make([]serviceEndpoint, 0, len(probes))
	seen := make(map[string]bool)
	type mapping struct {
		host string
		port string
		err  error
	}
	cache := make(map[string]mapping)
	resolvePort := func(target string) (string, string, error) {
		if cached, ok := cache[target]; ok {
			return cached.host, cached.port, cached.err
		}
		host, port, err := composePort(projectDir, row.Service, target)
		cache[target] = mapping{host: host, port: port, err: err}
		return host, port, err
	}

	for _, probe := range probes {
		host, port, err := resolvePort(probe.Port)
		if err != nil || strings.TrimSpace(port) == "" {
			continue
		}
		hostForURL := sanitizeHost(host)
		url := fmt.Sprintf("http://%s:%s%s", hostForURL, port, probe.Path)
		if seen[url] {
			continue
		}
		result := probeHTTP(url)
		entry := serviceEndpoint{
			URL:        url,
			Path:       probe.Path,
			Host:       hostForURL,
			Port:       port,
			Healthy:    result.IsHealthy,
			StatusCode: result.Status,
			LatencyMS:  int(result.Latency / time.Millisecond),
		}
		if result.Err != nil {
			entry.Error = result.Err.Error()
		}
		results = append(results, entry)
		seen[url] = true
	}

	for _, port := range parsePublishedPorts(row.Ports) {
		url := fmt.Sprintf("http://%s:%s/", sanitizeHost(port.host), port.port)
		if seen[url] {
			continue
		}
		result := probeHTTP(url)
		entry := serviceEndpoint{
			URL:        url,
			Path:       "/",
			Host:       sanitizeHost(port.host),
			Port:       port.port,
			Healthy:    result.IsHealthy,
			StatusCode: result.Status,
			LatencyMS:  int(result.Latency / time.Millisecond),
		}
		if result.Err != nil {
			entry.Error = result.Err.Error()
		}
		results = append(results, entry)
		seen[url] = true
	}

	return results
}

type hostPort struct {
	host string
	port string
}

func parsePublishedPorts(raw string) []hostPort {
	if strings.TrimSpace(raw) == "" {
		return nil
	}
	var results []hostPort
	entries := strings.Split(raw, ",")
	for _, entry := range entries {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		left, _, found := strings.Cut(entry, "->")
		if !found {
			continue
		}
		left = strings.TrimSpace(left)
		if left == "" {
			continue
		}
		idx := strings.LastIndex(left, ":")
		if idx == -1 {
			continue
		}
		host := strings.TrimSpace(left[:idx])
		port := strings.TrimSpace(left[idx+1:])
		if port == "" {
			continue
		}
		if host == "" {
			host = "0.0.0.0"
		}
		results = append(results, hostPort{host: host, port: port})
	}
	return results
}

func probeHTTP(target string) probeResult {
	client := http.Client{Timeout: 1500 * time.Millisecond}
	start := time.Now()
	resp, err := client.Get(target)
	if err != nil {
		return probeResult{Latency: time.Since(start), Err: err}
	}
	defer resp.Body.Close()
	duration := time.Since(start)
	healthy := resp.StatusCode < 400
	return probeResult{
		Latency:   duration,
		Status:    resp.StatusCode,
		IsHealthy: healthy,
	}
}

func fallback(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}

func dockerCLIAvailable() bool {
	_, err := exec.LookPath("docker")
	return err == nil
}
