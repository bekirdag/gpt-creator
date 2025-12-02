package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type artifactCategory struct {
	Key         string
	Title       string
	Paths       []string
	Description string
}

type artifactNode struct {
	Key         string
	Rel         string
	Name        string
	Level       int
	IsDir       bool
	Expanded    bool
	Loaded      bool
	Parent      string
	HasChildren bool
	Size        int64
	ModTime     time.Time
}

type artifactExplorer struct {
	projectPath string
	categoryKey string
	roots       []*artifactNode
	nodes       map[string]*artifactNode
	children    map[string][]*artifactNode
}

func buildArtifactCategories(projectPath string) []artifactCategory {
	candidates := []artifactCategory{
		{
			Key:   "staging",
			Title: "Staging Artifacts",
			Paths: []string{".gpt-creator/staging"},
		},
		{
			Key:   "apps",
			Title: "Applications",
			Paths: []string{"apps"},
		},
	}
	var categories []artifactCategory
	for _, cat := range candidates {
		desc := summarizeCategory(projectPath, cat.Paths)
		entry := cat
		entry.Description = desc
		categories = append(categories, entry)
	}
	return categories
}

func artifactCategoryHasContent(projectPath string, cat artifactCategory) bool {
	for _, rel := range cat.Paths {
		abs := filepath.Join(projectPath, filepath.FromSlash(rel))
		entries, err := os.ReadDir(abs)
		if err != nil {
			continue
		}
		if len(entries) > 0 {
			return true
		}
	}
	return false
}

func summarizeCategory(projectPath string, relPaths []string) string {
	var (
		totalItems int
		newest     time.Time
		exists     bool
	)
	for _, rel := range relPaths {
		abs := filepath.Join(projectPath, filepath.FromSlash(rel))
		info, err := os.Stat(abs)
		if err != nil || !info.IsDir() {
			continue
		}
		exists = true
		entries, err := os.ReadDir(abs)
		if err != nil {
			continue
		}
		totalItems += len(entries)
		for _, entry := range entries {
			fi, err := entry.Info()
			if err != nil {
				continue
			}
			if fi.ModTime().After(newest) {
				newest = fi.ModTime()
			}
		}
	}
	if !exists {
		return "Directory missing"
	}
	if totalItems == 0 {
		return "Empty"
	}
	if newest.IsZero() {
		return fmt.Sprintf("%d items", totalItems)
	}
	return fmt.Sprintf("%d items • updated %s", totalItems, formatRelativeTime(newest))
}

func newArtifactExplorer(projectPath, categoryKey string, roots []string) *artifactExplorer {
	ex := &artifactExplorer{
		projectPath: projectPath,
		categoryKey: categoryKey,
		nodes:       make(map[string]*artifactNode),
		children:    make(map[string][]*artifactNode),
	}
	for _, rel := range roots {
		clean := normalizeRel(rel)
		node := ex.newNode(clean, "", 0)
		ex.roots = append(ex.roots, node)
		ex.nodes[node.Key] = node
	}
	return ex
}

func (e *artifactExplorer) VisibleNodes() []artifactNode {
	var nodes []artifactNode
	for _, root := range e.roots {
		if root == nil {
			continue
		}
		nodes = append(nodes, *root)
		if root.IsDir && root.Expanded {
			nodes = append(nodes, e.collectVisible(root.Key)...)
		}
	}
	return nodes
}

func (e *artifactExplorer) collectVisible(key string) []artifactNode {
	children := e.children[key]
	if len(children) == 0 {
		return nil
	}
	out := make([]artifactNode, 0, len(children))
	for _, child := range children {
		if child == nil {
			continue
		}
		out = append(out, *child)
		if child.IsDir && child.Expanded {
			out = append(out, e.collectVisible(child.Key)...)
		}
	}
	return out
}

func (e *artifactExplorer) Toggle(key string) error {
	node := e.nodes[key]
	if node == nil || !node.IsDir {
		return nil
	}
	if node.Expanded {
		node.Expanded = false
		return nil
	}
	if !node.Loaded {
		if err := e.loadChildren(node); err != nil {
			return err
		}
	}
	node.Expanded = true
	return nil
}

func (e *artifactExplorer) Expand(key string) error {
	node := e.nodes[key]
	if node == nil || !node.IsDir {
		return nil
	}
	if !node.Loaded {
		if err := e.loadChildren(node); err != nil {
			return err
		}
	}
	node.Expanded = true
	return nil
}

func (e *artifactExplorer) Collapse(key string) {
	node := e.nodes[key]
	if node == nil || !node.IsDir {
		return
	}
	node.Expanded = false
}

func (e *artifactExplorer) loadChildren(node *artifactNode) error {
	if node == nil || !node.IsDir {
		return nil
	}
	abs := e.absPath(node.Rel)
	entries, err := os.ReadDir(abs)
	if err != nil {
		node.Loaded = true
		node.HasChildren = false
		return err
	}
	sort.Slice(entries, func(i, j int) bool {
		iname := entries[i].Name()
		jname := entries[j].Name()
		idir := entries[i].IsDir()
		jdir := entries[j].IsDir()
		if idir != jdir {
			return idir
		}
		return strings.ToLower(iname) < strings.ToLower(jname)
	})
	children := make([]*artifactNode, 0, len(entries))
	for _, entry := range entries {
		rel := joinRel(node.Rel, entry.Name())
		child := e.newNode(rel, node.Rel, node.Level+1)
		if entry.Type()&os.ModeSymlink != 0 {
			// best effort for symlinks; treat as file unless target dir
			if info, err := os.Stat(filepath.Join(e.projectPath, filepath.FromSlash(rel))); err == nil {
				child.IsDir = info.IsDir()
				child.Size = info.Size()
				child.ModTime = info.ModTime()
			}
		} else if info, err := entry.Info(); err == nil {
			if info.Mode().IsRegular() {
				child.Size = info.Size()
			}
			child.ModTime = info.ModTime()
		}
		if entry.IsDir() {
			child.IsDir = true
			child.HasChildren = true
		}
		e.nodes[child.Key] = child
		children = append(children, child)
	}
	node.Loaded = true
	node.HasChildren = len(children) > 0
	e.children[node.Key] = children
	return nil
}

func (e *artifactExplorer) newNode(rel, parent string, level int) *artifactNode {
	info, _ := os.Stat(e.absPath(rel))
	name := displayName(rel, level)
	node := &artifactNode{
		Key:    normalizeKey(e.categoryKey, rel),
		Rel:    rel,
		Name:   name,
		Level:  level,
		Parent: parent,
	}
	if info != nil {
		node.IsDir = info.IsDir()
		node.ModTime = info.ModTime()
		if !info.IsDir() {
			node.Size = info.Size()
		}
	}
	if level == 0 {
		node.IsDir = true
		node.HasChildren = true
	}
	if parent != "" {
		node.Parent = parent
	}
	return node
}

func (e *artifactExplorer) absPath(rel string) string {
	return filepath.Join(e.projectPath, filepath.FromSlash(rel))
}

func (e *artifactExplorer) Node(key string) *artifactNode {
	return e.nodes[key]
}

func (e *artifactExplorer) RootKeys() []string {
	keys := make([]string, 0, len(e.roots))
	for _, node := range e.roots {
		if node != nil {
			keys = append(keys, node.Key)
		}
	}
	return keys
}

func normalizeRel(rel string) string {
	if strings.TrimSpace(rel) == "" {
		return "."
	}
	clean := filepath.Clean(rel)
	clean = filepath.ToSlash(clean)
	if clean == "." {
		return "."
	}
	return strings.TrimPrefix(clean, "./")
}

func joinRel(parent, child string) string {
	if parent == "" || parent == "." {
		return normalizeRel(child)
	}
	return normalizeRel(filepath.Join(parent, child))
}

func displayName(rel string, level int) string {
	if level == 0 {
		return rel
	}
	trimmed := strings.TrimSuffix(rel, "/")
	slash := strings.LastIndex(trimmed, "/")
	if slash >= 0 {
		return trimmed[slash+1:]
	}
	return trimmed
}

func normalizeKey(categoryKey, rel string) string {
	return categoryKey + ":" + normalizeRel(rel)
}
