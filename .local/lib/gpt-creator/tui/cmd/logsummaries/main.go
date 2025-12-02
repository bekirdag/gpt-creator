package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

type telemetrySnapshot struct {
	Timestamp time.Time `json:"timestamp"`
	Tokens    int64     `json:"tokens"`
	LatencyMs int64     `json:"latency_ms"`
	Line      int       `json:"line"`
}

type telemetryAggregate struct {
	StartLine     int       `json:"start_line"`
	EndLine       int       `json:"end_line"`
	StartTime     time.Time `json:"start_time"`
	EndTime       time.Time `json:"end_time"`
	TokensDelta   int64     `json:"tokens_delta"`
	TokensTotal   int64     `json:"tokens_total"`
	LatencyMsSum  int64     `json:"latency_ms_sum"`
	LatencyCount  int64     `json:"latency_count"`
	LatencyMedian float64   `json:"latency_median"`
	Anomalies     []string  `json:"anomalies"`
}

type telemetryReport struct {
	RunID        string               `json:"run_id"`
	Source       string               `json:"source"`
	Snapshots    []telemetryAggregate `json:"snapshots"`
	FinalSummary telemetryAggregate   `json:"final_summary"`
}

var (
	tokenBracedPattern    = regexp.MustCompile(`^\[([^]]+)\]\s+tokens used:\s*([0-9,]+)`)
	tokenInlinePattern    = regexp.MustCompile(`tokens_used:\s*([0-9,]+)`)
	durationInlinePattern = regexp.MustCompile(`duration:\s*([0-9]+)ms`)
	durationExecPattern   = regexp.MustCompile(`\s(?:succeeded|failed)\s+in\s+([0-9]+)ms`)
)

func main() {
	var inputPath string
	var outputPath string
	var interval int
	flag.StringVar(&inputPath, "in", "", "input log file path (required)")
	flag.StringVar(&outputPath, "out", "", "output JSON path (optional, defaults to stdout)")
	flag.IntVar(&interval, "interval", 5, "number of telemetry events per aggregated snapshot")
	flag.Parse()

	if inputPath == "" {
		exit(errors.New("missing --in path"))
	}
	if interval <= 0 {
		exit(errors.New("--interval must be positive"))
	}

	tokens, durations, err := parseTelemetry(inputPath)
	if err != nil {
		exit(fmt.Errorf("parse telemetry: %w", err))
	}

	report := buildReport(inputPath, tokens, durations, interval)

	encoded, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		exit(fmt.Errorf("encode report: %w", err))
	}

	if outputPath == "" {
		fmt.Println(string(encoded))
		return
	}
	if err := os.WriteFile(outputPath, append(encoded, '\n'), 0o644); err != nil {
		exit(fmt.Errorf("write output: %w", err))
	}
}

func exit(err error) {
	fmt.Fprintf(os.Stderr, "logsummaries: %v\n", err)
	os.Exit(1)
}

func parseTelemetry(path string) ([]telemetrySnapshot, []telemetrySnapshot, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, nil, err
	}
	defer file.Close()

	var (
		scanner   = bufio.NewScanner(file)
		lineNo    = 0
		tokens    []telemetrySnapshot
		durations []telemetrySnapshot
	)
	scanner.Buffer(make([]byte, 0, 256*1024), 16*1024*1024)

	for scanner.Scan() {
		lineNo++
		line := scanner.Text()

		if m := tokenBracedPattern.FindStringSubmatch(line); m != nil {
			ts := parseTimestamp(m[1])
			value, err := parseIntString(m[2])
			if err != nil {
				continue
			}
			tokens = append(tokens, telemetrySnapshot{
				Timestamp: ts,
				Tokens:    value,
				Line:      lineNo,
			})
			continue
		}

		if m := tokenInlinePattern.FindStringSubmatch(line); m != nil {
			ts := extractTimestamp(line)
			value, err := parseIntString(m[1])
			if err != nil {
				continue
			}
			tokens = append(tokens, telemetrySnapshot{
				Timestamp: ts,
				Tokens:    value,
				Line:      lineNo,
			})
			continue
		}

		if value := parseDuration(line); value >= 0 {
			ts := extractTimestamp(line)
			durations = append(durations, telemetrySnapshot{
				Timestamp: ts,
				LatencyMs: value,
				Line:      lineNo,
			})
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, nil, err
	}
	return tokens, durations, nil
}

func parseIntString(value string) (int64, error) {
	clean := strings.ReplaceAll(value, ",", "")
	var out int64
	_, err := fmt.Sscan(clean, &out)
	return out, err
}

func parseDuration(line string) int64 {
	if m := durationInlinePattern.FindStringSubmatch(line); m != nil {
		var value int64
		if _, err := fmt.Sscan(m[1], &value); err == nil {
			return value
		}
	}
	if strings.Contains(line, "in ") {
		if m := durationExecPattern.FindStringSubmatch(line); m != nil {
			var value int64
			if _, err := fmt.Sscan(m[1], &value); err == nil {
				return value
			}
		}
	}
	return -1
}

func extractTimestamp(line string) time.Time {
	start := strings.Index(line, "[")
	end := strings.Index(line, "]")
	if start != -1 && end > start+1 {
		return parseTimestamp(line[start+1 : end])
	}
	return time.Time{}
}

func parseTimestamp(raw string) time.Time {
	candidates := []string{
		time.RFC3339Nano,
		time.RFC3339,
		"2006-01-02T15:04:05",
	}
	value := strings.TrimSpace(raw)
	for _, layout := range candidates {
		if ts, err := time.Parse(layout, value); err == nil {
			return ts
		}
	}
	return time.Time{}
}

func buildReport(path string, tokens, durations []telemetrySnapshot, interval int) telemetryReport {
	if len(tokens) == 0 {
		return telemetryReport{
			RunID:  deriveRunID(path),
			Source: path,
		}
	}

	sort.Slice(tokens, func(i, j int) bool { return tokens[i].Timestamp.Before(tokens[j].Timestamp) })
	sort.Slice(durations, func(i, j int) bool { return durations[i].Timestamp.Before(durations[j].Timestamp) })

	tokens = dedupeTokens(tokens)

	runID := deriveRunID(path)

	var snapshots []telemetryAggregate
	for start := 0; start < len(tokens); start += interval {
		end := start + interval
		if end > len(tokens) {
			end = len(tokens)
		}
		segment := tokens[start:end]
		snapshots = append(snapshots, aggregateSegment(segment, durations))
	}

	final := aggregateSegment(tokens, durations)

	return telemetryReport{
		RunID:        runID,
		Source:       path,
		Snapshots:    snapshots,
		FinalSummary: final,
	}
}

func deriveRunID(path string) string {
	base := filepath.Base(path)
	return strings.TrimSuffix(base, filepath.Ext(base))
}

func aggregateSegment(segment []telemetrySnapshot, durations []telemetrySnapshot) telemetryAggregate {
	if len(segment) == 0 {
		return telemetryAggregate{}
	}
	start := segment[0]
	end := segment[len(segment)-1]

	firstTokens := start.Tokens
	lastTokens := end.Tokens
	tokensDelta := lastTokens - firstTokens
	tokensTotal := lastTokens

	latencyValues := collectLatency(durations, start.Timestamp, end.Timestamp)

	median := computeMedian(latencyValues)
	sum := int64(0)
	for _, v := range latencyValues {
		sum += v
	}

	anomalies := detectAnomalies(tokensDelta, latencyValues)

	return telemetryAggregate{
		StartLine:     start.Line,
		EndLine:       end.Line,
		StartTime:     start.Timestamp,
		EndTime:       end.Timestamp,
		TokensDelta:   tokensDelta,
		TokensTotal:   tokensTotal,
		LatencyMsSum:  sum,
		LatencyCount:  int64(len(latencyValues)),
		LatencyMedian: median,
		Anomalies:     anomalies,
	}
}

func collectLatency(all []telemetrySnapshot, start, end time.Time) []int64 {
	if len(all) == 0 {
		return nil
	}
	var out []int64
	for _, snap := range all {
		if !snap.Timestamp.IsZero() {
			if !snap.Timestamp.Before(start) && !snap.Timestamp.After(end) {
				out = append(out, snap.LatencyMs)
			}
		}
	}
	return out
}

func computeMedian(values []int64) float64 {
	if len(values) == 0 {
		return 0
	}
	sorted := append([]int64(nil), values...)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i] < sorted[j] })
	mid := len(sorted) / 2
	if len(sorted)%2 == 1 {
		return float64(sorted[mid])
	}
	return float64(sorted[mid-1]+sorted[mid]) / 2
}

func detectAnomalies(tokensDelta int64, latency []int64) []string {
	var out []string
	if tokensDelta < 0 {
		out = append(out, fmt.Sprintf("negative token delta (%d)", tokensDelta))
	}
	for _, v := range latency {
		if v > 60000 {
			out = append(out, fmt.Sprintf("latency spike %dms", v))
			break
		}
	}
	return out
}

func dedupeTokens(tokens []telemetrySnapshot) []telemetrySnapshot {
	if len(tokens) <= 1 {
		return tokens
	}
	out := make([]telemetrySnapshot, 0, len(tokens))
	out = append(out, tokens[0])
	lastVal := tokens[0].Tokens
	for i := 1; i < len(tokens); i++ {
		if tokens[i].Tokens == lastVal {
			continue
		}
		out = append(out, tokens[i])
		lastVal = tokens[i].Tokens
	}
	return out
}
