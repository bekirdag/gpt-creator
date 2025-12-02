package main

import (
	"bufio"
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	defaultTokensCostPerThousand = 0.002
	maxTokensPreviewRecords      = 24
)

type tokensRangeOption struct {
	Key      string
	Label    string
	Duration time.Duration
}

var tokensRangeOptions = []tokensRangeOption{
	{Key: "1d", Label: "Last 24 hours", Duration: 24 * time.Hour},
	{Key: "7d", Label: "Last 7 days", Duration: 7 * 24 * time.Hour},
	{Key: "30d", Label: "Last 30 days", Duration: 30 * 24 * time.Hour},
	{Key: "all", Label: "All time", Duration: 0},
}

type tokensGroupMode string

const (
	tokensGroupByDay     tokensGroupMode = "day"
	tokensGroupByCommand tokensGroupMode = "command"
)

type tokenLogRecord struct {
	Index            int
	Timestamp        time.Time
	RawTimestamp     string
	Command          string
	Model            string
	TotalTokens      int
	PromptTokens     int
	CompletionTokens int
	CachedTokens     int
	BillableUnits    int
	RequestUnits     int
	EstimatedCost    float64
	ExitCode         *int
	UsageCaptured    bool
	RawLine          string
}

type tokensTotals struct {
	Calls            int
	PromptTokens     int
	CompletionTokens int
	TotalTokens      int
	CachedTokens     int
	BillableUnits    int
	RequestUnits     int
	EstimatedCost    float64
}

type tokensUsage struct {
	Records  []tokenLogRecord
	Earliest time.Time
	Latest   time.Time
	Totals   tokensTotals
}

type tokensTableRow struct {
	Key              string
	Group            tokensGroupMode
	Label            string
	Secondary        string
	Calls            int
	Tokens           int
	Cost             float64
	Start            time.Time
	End              time.Time
	TopCommand       string
	TopCommandTokens int
	Models           map[string]int
	RecordRefs       []int
}

type tokensViewSummary struct {
	RangeKey         string
	RangeLabel       string
	RangeStart       time.Time
	RangeEnd         time.Time
	GroupLabel       string
	TotalCalls       int
	TotalTokens      int
	TotalCost        float64
	DistinctCommands int
	DistinctDays     int
	TopCommands      []tokensBreakdown
	Records          int
}

type tokensBreakdown struct {
	Label  string
	Calls  int
	Tokens int
	Cost   float64
}

type tokensViewData struct {
	Range   tokensRangeOption
	Group   tokensGroupMode
	Summary tokensViewSummary
	Rows    []tokensTableRow
	Records []tokenLogRecord
}

var (
	tokensCostOnce sync.Once
	tokensCostRate = defaultTokensCostPerThousand
)

func tokensCostPerThousand() float64 {
	tokensCostOnce.Do(func() {
		if value := strings.TrimSpace(os.Getenv("GC_TOKENS_COST_PER_1K")); value != "" {
			if parsed, err := strconv.ParseFloat(value, 64); err == nil && parsed >= 0 {
				tokensCostRate = parsed
			}
		}
	})
	return tokensCostRate
}

func readTokensUsage(path string) (*tokensUsage, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	buf := make([]byte, 0, 64*1024)
	scanner.Buffer(buf, 1024*1024)

	usage := &tokensUsage{}
	index := 0
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		record, ok := parseTokenLogRecord(line)
		if !ok {
			continue
		}
		record.Index = index
		index++
		usage.Records = append(usage.Records, record)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}

	if len(usage.Records) == 0 {
		return usage, nil
	}

	sort.Slice(usage.Records, func(i, j int) bool {
		li, lj := usage.Records[i].Timestamp, usage.Records[j].Timestamp
		if li.Equal(lj) {
			return usage.Records[i].Index < usage.Records[j].Index
		}
		return li.Before(lj)
	})
	for idx := range usage.Records {
		usage.Records[idx].Index = idx
		usage.addToTotals(usage.Records[idx])
	}
	usage.Earliest = usage.Records[0].Timestamp
	usage.Latest = usage.Records[len(usage.Records)-1].Timestamp
	return usage, nil
}

func parseTokenLogRecord(line string) (tokenLogRecord, bool) {
	var payload map[string]any
	if err := json.Unmarshal([]byte(line), &payload); err != nil {
		return tokenLogRecord{}, false
	}
	rec := tokenLogRecord{
		RawLine:      line,
		RawTimestamp: fmt.Sprint(payload["timestamp"]),
		Command:      sanitizeCommand(fmt.Sprint(payload["task"])),
		Model:        strings.TrimSpace(fmt.Sprint(payload["model"])),
	}
	if rec.Command == "" {
		rec.Command = sanitizeCommand(fmt.Sprint(payload["command"]))
	}
	if rec.Command == "" {
		rec.Command = sanitizeCommand(fmt.Sprint(payload["job"]))
	}
	if ts := parseUsageTimestamp(rec.RawTimestamp); !ts.IsZero() {
		rec.Timestamp = ts
	}
	rec.TotalTokens = parseUsageInt(payload["total_tokens"])
	rec.PromptTokens = parseUsageInt(payload["prompt_tokens"])
	rec.CompletionTokens = parseUsageInt(payload["completion_tokens"])
	rec.CachedTokens = parseUsageInt(payload["cached_tokens"])
	rec.BillableUnits = parseUsageInt(payload["billable_units"])
	rec.RequestUnits = parseUsageInt(payload["request_units"])
	if value, ok := payload["exit_code"]; ok {
		if parsed := parseUsageInt(value); parsed != 0 {
			rec.ExitCode = &parsed
		}
	}
	rec.UsageCaptured = asBool(payload["usage_captured"])
	if rec.TotalTokens < 0 {
		rec.TotalTokens = 0
	}
	rec.EstimatedCost = estimateTokensCost(rec.TotalTokens)
	return rec, true
}

func parseUsageTimestamp(raw string) time.Time {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return time.Time{}
	}
	if strings.HasSuffix(raw, "Z") {
		raw = strings.TrimSuffix(raw, "Z") + "+00:00"
	}
	if ts, err := time.Parse(time.RFC3339Nano, raw); err == nil {
		return ts
	}
	if ts, err := time.Parse(time.RFC3339, raw); err == nil {
		return ts
	}
	return time.Time{}
}

func sanitizeCommand(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	value = strings.TrimPrefix(value, "gpt-creator ")
	value = strings.TrimSpace(value)
	return value
}

func parseUsageInt(value any) int {
	switch v := value.(type) {
	case int:
		return v
	case int32:
		return int(v)
	case int64:
		return int(v)
	case float32:
		return int(v)
	case float64:
		return int(v)
	case string:
		trim := strings.TrimSpace(v)
		if trim == "" {
			return 0
		}
		if n, err := strconv.Atoi(trim); err == nil {
			return n
		}
		if strings.Contains(trim, ".") {
			if f, err := strconv.ParseFloat(trim, 64); err == nil {
				return int(f)
			}
		}
	}
	return 0
}

func asBool(value any) bool {
	switch v := value.(type) {
	case bool:
		return v
	case string:
		switch strings.ToLower(strings.TrimSpace(v)) {
		case "true", "1", "yes", "y":
			return true
		}
	case int:
		return v != 0
	case float64:
		return int(v) != 0
	}
	return false
}

func (u *tokensUsage) addToTotals(record tokenLogRecord) {
	u.Totals.Calls++
	u.Totals.TotalTokens += record.TotalTokens
	u.Totals.PromptTokens += record.PromptTokens
	u.Totals.CompletionTokens += record.CompletionTokens
	u.Totals.CachedTokens += record.CachedTokens
	u.Totals.BillableUnits += record.BillableUnits
	u.Totals.RequestUnits += record.RequestUnits
	u.Totals.EstimatedCost += record.EstimatedCost
}

func estimateTokensCost(totalTokens int) float64 {
	if totalTokens <= 0 {
		return 0
	}
	return (float64(totalTokens) / 1000.0) * tokensCostPerThousand()
}

func buildTokensView(usage *tokensUsage, option tokensRangeOption, group tokensGroupMode) (tokensViewData, error) {
	data := tokensViewData{
		Range: option,
		Group: group,
	}
	if usage == nil || len(usage.Records) == 0 {
		data.Summary = tokensViewSummary{
			RangeKey:   option.Key,
			RangeLabel: option.Label,
			GroupLabel: tokensGroupLabel(group),
		}
		return data, nil
	}

	filtered, start, end := filterTokensRecords(usage, option)
	data.Records = filtered
	data.Summary = summarizeTokens(filtered, option, group, start, end)
	data.Rows = aggregateTokensRows(filtered, group)
	return data, nil
}

func filterTokensRecords(usage *tokensUsage, option tokensRangeOption) ([]tokenLogRecord, time.Time, time.Time) {
	if usage == nil || len(usage.Records) == 0 {
		return nil, time.Time{}, time.Time{}
	}
	records := usage.Records
	end := usage.Latest
	if end.IsZero() {
		end = time.Now()
	}
	start := usage.Earliest
	if option.Duration > 0 {
		start = end.Add(-option.Duration)
	}
	loc := time.Local
	if loc == nil {
		loc = time.UTC
	}
	if !start.IsZero() {
		start = start.In(loc).Truncate(24 * time.Hour)
	}
	if !end.IsZero() {
		end = end.In(loc).Truncate(24 * time.Hour).Add(24*time.Hour - time.Nanosecond)
	}

	var filtered []tokenLogRecord
	for _, rec := range records {
		ts := rec.Timestamp
		if !start.IsZero() && ts.Before(start) {
			continue
		}
		if !end.IsZero() && ts.After(end) {
			continue
		}
		filtered = append(filtered, rec)
	}
	if len(filtered) == 0 {
		return filtered, start, end
	}
	start = filtered[0].Timestamp
	end = filtered[len(filtered)-1].Timestamp
	return filtered, start, end
}

func summarizeTokens(records []tokenLogRecord, option tokensRangeOption, group tokensGroupMode, start, end time.Time) tokensViewSummary {
	summary := tokensViewSummary{
		RangeKey:   option.Key,
		RangeLabel: formatRangeLabel(option, start, end),
		RangeStart: start,
		RangeEnd:   end,
		GroupLabel: tokensGroupLabel(group),
		Records:    len(records),
	}
	commandCounts := make(map[string]*tokensBreakdown)
	dayCounts := make(map[string]struct{})

	for _, rec := range records {
		summary.TotalCalls++
		summary.TotalTokens += rec.TotalTokens
		summary.TotalCost += rec.EstimatedCost

		if rec.Command != "" {
			entry := commandCounts[rec.Command]
			if entry == nil {
				entry = &tokensBreakdown{Label: rec.Command}
				commandCounts[rec.Command] = entry
			}
			entry.Calls++
			entry.Tokens += rec.TotalTokens
			entry.Cost += rec.EstimatedCost
		}
		dayKey := rec.Timestamp.In(time.Local).Format("2006-01-02")
		dayCounts[dayKey] = struct{}{}
	}
	summary.DistinctCommands = len(commandCounts)
	summary.DistinctDays = len(dayCounts)

	for _, entry := range commandCounts {
		summary.TopCommands = append(summary.TopCommands, *entry)
	}
	sort.Slice(summary.TopCommands, func(i, j int) bool {
		if summary.TopCommands[i].Tokens == summary.TopCommands[j].Tokens {
			return summary.TopCommands[i].Label < summary.TopCommands[j].Label
		}
		return summary.TopCommands[i].Tokens > summary.TopCommands[j].Tokens
	})
	if len(summary.TopCommands) > 8 {
		summary.TopCommands = summary.TopCommands[:8]
	}
	return summary
}

func aggregateTokensRows(records []tokenLogRecord, group tokensGroupMode) []tokensTableRow {
	if len(records) == 0 {
		return nil
	}
	switch group {
	case tokensGroupByCommand:
		return aggregateTokensByCommand(records)
	default:
		return aggregateTokensByDay(records)
	}
}

func aggregateTokensByDay(records []tokenLogRecord) []tokensTableRow {
	type dayAggregate struct {
		Day        time.Time
		Calls      int
		Tokens     int
		Cost       float64
		TopCommand string
		TopTokens  int
		CommandMap map[string]int
		Models     map[string]int
		Refs       []int
	}

	dayMap := make(map[string]*dayAggregate)
	for idx, rec := range records {
		dayKey := rec.Timestamp.In(time.Local).Format("2006-01-02")
		agg := dayMap[dayKey]
		if agg == nil {
			start := rec.Timestamp.In(time.Local).Truncate(24 * time.Hour)
			agg = &dayAggregate{
				Day:        start,
				CommandMap: make(map[string]int),
				Models:     make(map[string]int),
			}
			dayMap[dayKey] = agg
		}
		agg.Calls++
		agg.Tokens += rec.TotalTokens
		agg.Cost += rec.EstimatedCost
		if rec.Command != "" {
			agg.CommandMap[rec.Command] += rec.TotalTokens
			if agg.CommandMap[rec.Command] > agg.TopTokens {
				agg.TopTokens = agg.CommandMap[rec.Command]
				agg.TopCommand = rec.Command
			}
		}
		if rec.Model != "" {
			agg.Models[rec.Model]++
		}
		agg.Refs = append(agg.Refs, idx)
	}

	var rows []tokensTableRow
	for key, agg := range dayMap {
		secondary := "-"
		if agg.TopCommand != "" {
			secondary = fmt.Sprintf("%s • %s", agg.TopCommand, formatCompactTokens(agg.TopTokens))
		}
		rows = append(rows, tokensTableRow{
			Key:              "day:" + key,
			Group:            tokensGroupByDay,
			Label:            key,
			Secondary:        secondary,
			Calls:            agg.Calls,
			Tokens:           agg.Tokens,
			Cost:             agg.Cost,
			Start:            agg.Day,
			End:              agg.Day.Add(24*time.Hour - time.Nanosecond),
			TopCommand:       agg.TopCommand,
			TopCommandTokens: agg.TopTokens,
			Models:           agg.Models,
			RecordRefs:       append([]int(nil), agg.Refs...),
		})
	}
	sort.Slice(rows, func(i, j int) bool {
		left, right := rows[i], rows[j]
		if left.Label == right.Label {
			return left.Calls > right.Calls
		}
		return rows[i].Label > rows[j].Label
	})
	return rows
}

func aggregateTokensByCommand(records []tokenLogRecord) []tokensTableRow {
	type cmdAggregate struct {
		Command string
		Calls   int
		Tokens  int
		Cost    float64
		First   time.Time
		Last    time.Time
		Models  map[string]int
		Refs    []int
	}

	cmdMap := make(map[string]*cmdAggregate)
	for idx, rec := range records {
		command := rec.Command
		if command == "" {
			command = "(unknown)"
		}
		agg := cmdMap[command]
		if agg == nil {
			agg = &cmdAggregate{
				Command: command,
				Models:  make(map[string]int),
			}
			cmdMap[command] = agg
		}
		agg.Calls++
		agg.Tokens += rec.TotalTokens
		agg.Cost += rec.EstimatedCost
		if agg.First.IsZero() || rec.Timestamp.Before(agg.First) {
			agg.First = rec.Timestamp
		}
		if rec.Timestamp.After(agg.Last) {
			agg.Last = rec.Timestamp
		}
		if rec.Model != "" {
			agg.Models[rec.Model]++
		}
		agg.Refs = append(agg.Refs, idx)
	}

	var rows []tokensTableRow
	for _, agg := range cmdMap {
		label := agg.Command
		last := "-"
		if !agg.Last.IsZero() {
			last = agg.Last.Format("2006-01-02")
		}
		rows = append(rows, tokensTableRow{
			Key:        "cmd:" + label,
			Group:      tokensGroupByCommand,
			Label:      label,
			Secondary:  last,
			Calls:      agg.Calls,
			Tokens:     agg.Tokens,
			Cost:       agg.Cost,
			Start:      agg.First,
			End:        agg.Last,
			Models:     agg.Models,
			RecordRefs: append([]int(nil), agg.Refs...),
			TopCommand: label,
		})
	}

	sort.Slice(rows, func(i, j int) bool {
		left, right := rows[i], rows[j]
		if left.Tokens == right.Tokens {
			return left.Label < right.Label
		}
		return left.Tokens > right.Tokens
	})
	if len(rows) > 20 {
		rows = rows[:20]
	}
	return rows
}

func tokensGroupLabel(group tokensGroupMode) string {
	switch group {
	case tokensGroupByCommand:
		return "By command"
	default:
		return "Daily rollup"
	}
}

func formatRangeLabel(option tokensRangeOption, start, end time.Time) string {
	if start.IsZero() || end.IsZero() {
		return option.Label
	}
	startStr := start.In(time.Local).Format("Jan _2")
	endStr := end.In(time.Local).Format("Jan _2")
	if start.In(time.Local).Year() != end.In(time.Local).Year() {
		startStr = start.In(time.Local).Format("Jan _2 2006")
		endStr = end.In(time.Local).Format("Jan _2 2006")
	}
	if option.Duration == 0 || option.Key == "all" {
		return fmt.Sprintf("%s (%s → %s)", option.Label, startStr, endStr)
	}
	return fmt.Sprintf("%s (%s → %s)", option.Label, startStr, endStr)
}

func formatCompactTokens(tokens int) string {
	if tokens >= 1_000_000 {
		return fmt.Sprintf("%.1fM", float64(tokens)/1_000_000.0)
	}
	if tokens >= 1_000 {
		return fmt.Sprintf("%.1fk", float64(tokens)/1000.0)
	}
	return fmt.Sprintf("%d", tokens)
}

func formatCost(cost float64) string {
	if cost <= 0 {
		return "$0.00"
	}
	if cost >= 1 {
		return fmt.Sprintf("$%.2f", cost)
	}
	if cost >= 0.01 {
		return fmt.Sprintf("$%.2f", cost)
	}
	return fmt.Sprintf("$%.4f", cost)
}

func formatIntComma(value int) string {
	text := strconv.Itoa(value)
	n := len(text)
	if n <= 3 {
		return text
	}
	var parts []string
	for n > 3 {
		parts = append([]string{text[n-3:]}, parts...)
		text = text[:n-3]
		n = len(text)
	}
	parts = append([]string{text}, parts...)
	return strings.Join(parts, ",")
}

func renderTokensPreview(data tokensViewData, row tokensTableRow) string {
	if len(data.Records) == 0 || len(row.RecordRefs) == 0 {
		return "No usage entries in this range.\nPress [ or ] to adjust the range.\n"
	}

	var b strings.Builder
	title := ""
	switch row.Group {
	case tokensGroupByCommand:
		title = fmt.Sprintf("Command: %s", row.Label)
	default:
		title = fmt.Sprintf("Date: %s", row.Label)
	}
	b.WriteString(title + "\n")
	b.WriteString(strings.Repeat("─", len(title)))
	b.WriteString("\n\n")

	b.WriteString(fmt.Sprintf("Calls: %d • Tokens: %s • Est. cost: %s\n",
		row.Calls, formatIntComma(row.Tokens), formatCost(row.Cost)))
	if row.Calls > 0 {
		avg := row.Tokens / row.Calls
		b.WriteString(fmt.Sprintf("Avg tokens per call: %s\n", formatIntComma(avg)))
	}
	if row.Group == tokensGroupByDay && row.TopCommand != "" {
		b.WriteString(fmt.Sprintf("Top command: %s (%s tokens)\n", row.TopCommand, formatIntComma(row.TopCommandTokens)))
	}
	if row.Group == tokensGroupByCommand && !row.Start.IsZero() && !row.End.IsZero() {
		b.WriteString(fmt.Sprintf("First run: %s • Last run: %s\n",
			row.Start.In(time.Local).Format(time.RFC822),
			row.End.In(time.Local).Format(time.RFC822)))
	}

	if len(row.Models) > 0 {
		var pairs []string
		for model, count := range row.Models {
			pairs = append(pairs, fmt.Sprintf("%s (%d)", model, count))
		}
		sort.Strings(pairs)
		b.WriteString("Models: " + strings.Join(pairs, ", ") + "\n")
	}

	b.WriteString("\nBreakdown:\n")
	breakdowns := tokensRowBreakdown(data, row)
	maxEntries := 6
	for idx, entry := range breakdowns {
		if idx >= maxEntries {
			break
		}
		b.WriteString(fmt.Sprintf("  • %s — %d call(s), %s tokens, %s\n",
			entry.Label,
			entry.Calls,
			formatIntComma(entry.Tokens),
			formatCost(entry.Cost)))
	}
	if len(breakdowns) == 0 {
		b.WriteString("  (no additional detail)\n")
	} else if len(breakdowns) > maxEntries {
		b.WriteString(fmt.Sprintf("  …%d more entries\n", len(breakdowns)-maxEntries))
	}

	if data.Summary.Records > 0 {
		b.WriteString("\nRange totals: ")
		b.WriteString(fmt.Sprintf("%s • %s tokens • %s • %d commands\n",
			formatIntComma(data.Summary.TotalCalls),
			formatIntComma(data.Summary.TotalTokens),
			formatCost(data.Summary.TotalCost),
			data.Summary.DistinctCommands))
	}

	b.WriteString("\nSample NDJSON:\n")
	limit := maxTokensPreviewRecords
	if len(row.RecordRefs) < limit {
		limit = len(row.RecordRefs)
	}
	for i := 0; i < limit; i++ {
		rec := data.Records[row.RecordRefs[i]]
		ts := rec.Timestamp.Format(time.RFC3339)
		cmd := rec.Command
		if cmd == "" {
			cmd = "(unknown)"
		}
		b.WriteString(fmt.Sprintf("  %s • %s • %d tokens\n", ts, cmd, rec.TotalTokens))
	}
	if len(row.RecordRefs) > limit {
		b.WriteString(fmt.Sprintf("  …%d more entries\n", len(row.RecordRefs)-limit))
	}

	b.WriteString("\nKeys: -/= change range • g toggle grouping • e export CSV\n")
	return b.String()
}

func tokensRowBreakdown(data tokensViewData, row tokensTableRow) []tokensBreakdown {
	counter := make(map[string]*tokensBreakdown)
	for _, ref := range row.RecordRefs {
		if ref < 0 || ref >= len(data.Records) {
			continue
		}
		record := data.Records[ref]
		var key string
		if row.Group == tokensGroupByCommand {
			key = record.Timestamp.In(time.Local).Format("2006-01-02")
		} else {
			if record.Command != "" {
				key = record.Command
			} else {
				key = "(unknown)"
			}
		}
		entry := counter[key]
		if entry == nil {
			entry = &tokensBreakdown{Label: key}
			counter[key] = entry
		}
		entry.Calls++
		entry.Tokens += record.TotalTokens
		entry.Cost += record.EstimatedCost
	}
	var breakdowns []tokensBreakdown
	for _, entry := range counter {
		breakdowns = append(breakdowns, *entry)
	}
	sort.Slice(breakdowns, func(i, j int) bool {
		if breakdowns[i].Tokens == breakdowns[j].Tokens {
			return breakdowns[i].Label < breakdowns[j].Label
		}
		return breakdowns[i].Tokens > breakdowns[j].Tokens
	})
	return breakdowns
}

func writeTokensCSV(projectPath string, records []tokenLogRecord) (string, error) {
	if len(records) == 0 {
		return "", errors.New("no records to export")
	}
	dir := filepath.Join(projectPath, ".gpt-creator", "logs")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	name := fmt.Sprintf("tokens-%s.csv", time.Now().UTC().Format("20060102-150405"))
	path := filepath.Join(dir, name)

	file, err := os.Create(path)
	if err != nil {
		return "", err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	headers := []string{
		"timestamp",
		"command",
		"model",
		"total_tokens",
		"prompt_tokens",
		"completion_tokens",
		"cached_tokens",
		"billable_units",
		"request_units",
		"estimated_cost",
	}
	if err := writer.Write(headers); err != nil {
		return "", err
	}
	for _, rec := range records {
		row := []string{
			rec.Timestamp.Format(time.RFC3339),
			rec.Command,
			rec.Model,
			strconv.Itoa(rec.TotalTokens),
			strconv.Itoa(rec.PromptTokens),
			strconv.Itoa(rec.CompletionTokens),
			strconv.Itoa(rec.CachedTokens),
			strconv.Itoa(rec.BillableUnits),
			strconv.Itoa(rec.RequestUnits),
			fmt.Sprintf("%.6f", rec.EstimatedCost),
		}
		if err := writer.Write(row); err != nil {
			return "", err
		}
	}
	writer.Flush()
	if err := writer.Error(); err != nil {
		return "", err
	}
	return path, nil
}
