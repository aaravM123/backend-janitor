package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/spf13/cobra"
)

// FileInfo represents a single file in the codebase
type FileInfo struct {
	Path       string   `json:"path"`
	Language   string   `json:"language"`
	Size       int64    `json:"size"`
	TokenCount int      `json:"token_count"`
	Imports    []string `json:"imports"`
	Exports    []string `json:"exports"`
}

// CodebaseIndex is the complete index of a codebase
type CodebaseIndex struct {
	RootPath     string              `json:"root_path"`
	Files        []FileInfo          `json:"files"`
	TotalFiles   int                 `json:"total_files"`
	TotalTokens  int                 `json:"total_tokens"`
	Languages    map[string]int      `json:"languages"`
	Dependencies map[string][]string `json:"dependencies"` // file -> files it imports
	IndexedAt    string              `json:"indexed_at"`
	DurationMs   int64               `json:"duration_ms"`
}

// Supported file extensions and their languages
var languageExtensions = map[string]string{
	".py":   "python",
	".js":   "javascript",
	".ts":   "typescript",
	".tsx":  "typescript",
	".jsx":  "javascript",
	".go":   "go",
	".rs":   "rust",
	".java": "java",
	".rb":   "ruby",
	".php":  "php",
	".c":    "c",
	".cpp":  "cpp",
	".h":    "c",
	".hpp":  "cpp",
}

// Directories to skip
var skipDirs = map[string]bool{
	"node_modules":   true,
	".git":           true,
	"__pycache__":    true,
	".venv":          true,
	"venv":           true,
	"vendor":         true,
	"target":         true,
	"build":          true,
	"dist":           true,
	".next":          true,
	".nuxt":          true,
	"coverage":       true,
	".pytest_cache":  true,
	".mypy_cache":    true,
	".tox":           true,
	"egg-info":       true,
}

var indexCmd = &cobra.Command{
	Use:   "index <path>",
	Short: "Index a codebase and output file/dependency information",
	Long: `Index a codebase by walking all source files, extracting imports/exports,
and building a dependency graph.

Output is JSON containing:
  - List of all source files with metadata
  - Import/export information per file
  - Dependency graph
  - Token count estimates

Example:
  cshard index ./my-project --json`,
	Args: cobra.ExactArgs(1),
	RunE: runIndex,
}

func init() {
	rootCmd.AddCommand(indexCmd)
	indexCmd.Flags().Int("workers", 8, "Number of parallel workers for file processing")
	indexCmd.Flags().StringSlice("exclude", []string{}, "Additional directories to exclude")
}

func runIndex(cmd *cobra.Command, args []string) error {
	startTime := time.Now()
	rootPath := args[0]
	jsonOutput, _ := cmd.Flags().GetBool("json")
	workers, _ := cmd.Flags().GetInt("workers")
	excludeDirs, _ := cmd.Flags().GetStringSlice("exclude")

	// Add user-specified exclusions
	for _, dir := range excludeDirs {
		skipDirs[dir] = true
	}

	// Resolve absolute path
	absPath, err := filepath.Abs(rootPath)
	if err != nil {
		return fmt.Errorf("failed to resolve path: %w", err)
	}

	// Check path exists
	if _, err := os.Stat(absPath); os.IsNotExist(err) {
		return fmt.Errorf("path does not exist: %s", absPath)
	}

	// Collect all source files
	var files []string
	err = filepath.Walk(absPath, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil // Skip files we can't access
		}

		// Skip directories
		if info.IsDir() {
			if skipDirs[info.Name()] {
				return filepath.SkipDir
			}
			return nil
		}

		// Check if it's a source file we care about
		ext := strings.ToLower(filepath.Ext(path))
		if _, ok := languageExtensions[ext]; ok {
			files = append(files, path)
		}

		return nil
	})
	if err != nil {
		return fmt.Errorf("failed to walk directory: %w", err)
	}

	// Process files in parallel
	fileInfos := processFilesParallel(files, absPath, workers)

	// Build dependency graph
	dependencies := buildDependencyGraph(fileInfos, absPath)

	// Count languages
	languages := make(map[string]int)
	totalTokens := 0
	for _, f := range fileInfos {
		languages[f.Language]++
		totalTokens += f.TokenCount
	}

	// Create index
	index := CodebaseIndex{
		RootPath:     absPath,
		Files:        fileInfos,
		TotalFiles:   len(fileInfos),
		TotalTokens:  totalTokens,
		Languages:    languages,
		Dependencies: dependencies,
		IndexedAt:    time.Now().UTC().Format(time.RFC3339),
		DurationMs:   time.Since(startTime).Milliseconds(),
	}

	// Output
	if jsonOutput {
		encoder := json.NewEncoder(os.Stdout)
		encoder.SetIndent("", "  ")
		return encoder.Encode(index)
	}

	// Human-readable output
	fmt.Printf("Indexed: %s\n", absPath)
	fmt.Printf("Files: %d\n", index.TotalFiles)
	fmt.Printf("Tokens: %d (estimated)\n", index.TotalTokens)
	fmt.Printf("Duration: %dms\n", index.DurationMs)
	fmt.Println("\nLanguages:")
	for lang, count := range languages {
		fmt.Printf("  %s: %d files\n", lang, count)
	}

	return nil
}

func processFilesParallel(files []string, rootPath string, workers int) []FileInfo {
	var wg sync.WaitGroup
	fileChan := make(chan string, len(files))
	resultChan := make(chan FileInfo, len(files))

	// Start workers
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for path := range fileChan {
				info := processFile(path, rootPath)
				resultChan <- info
			}
		}()
	}

	// Send files to workers
	for _, f := range files {
		fileChan <- f
	}
	close(fileChan)

	// Wait for workers to finish
	go func() {
		wg.Wait()
		close(resultChan)
	}()

	// Collect results
	var results []FileInfo
	for info := range resultChan {
		results = append(results, info)
	}

	return results
}

func processFile(path string, rootPath string) FileInfo {
	// Get relative path
	relPath, _ := filepath.Rel(rootPath, path)

	// Get file info
	stat, err := os.Stat(path)
	if err != nil {
		return FileInfo{Path: relPath}
	}

	// Determine language
	ext := strings.ToLower(filepath.Ext(path))
	language := languageExtensions[ext]

	// Read file content for analysis
	content, err := os.ReadFile(path)
	if err != nil {
		return FileInfo{
			Path:     relPath,
			Language: language,
			Size:     stat.Size(),
		}
	}

	// Extract imports and exports
	imports, exports := extractImportsExports(string(content), language)

	// Estimate tokens (rough: ~4 chars per token)
	tokenCount := len(content) / 4

	return FileInfo{
		Path:       relPath,
		Language:   language,
		Size:       stat.Size(),
		TokenCount: tokenCount,
		Imports:    imports,
		Exports:    exports,
	}
}

func extractImportsExports(content string, language string) ([]string, []string) {
	var imports, exports []string

	lines := strings.Split(content, "\n")

	switch language {
	case "python":
		for _, line := range lines {
			line = strings.TrimSpace(line)
			// Import statements
			if strings.HasPrefix(line, "import ") {
				parts := strings.Fields(line)
				if len(parts) >= 2 {
					imports = append(imports, parts[1])
				}
			} else if strings.HasPrefix(line, "from ") {
				parts := strings.Fields(line)
				if len(parts) >= 2 {
					imports = append(imports, parts[1])
				}
			}
			// Exports (function and class definitions)
			if strings.HasPrefix(line, "def ") {
				name := extractFunctionName(line)
				if name != "" && !strings.HasPrefix(name, "_") {
					exports = append(exports, name)
				}
			} else if strings.HasPrefix(line, "class ") {
				name := extractClassName(line)
				if name != "" && !strings.HasPrefix(name, "_") {
					exports = append(exports, name)
				}
			}
		}

	case "javascript", "typescript":
		for _, line := range lines {
			line = strings.TrimSpace(line)
			// Import statements
			if strings.HasPrefix(line, "import ") {
				// Extract from 'module' or "module"
				if idx := strings.Index(line, "from "); idx != -1 {
					rest := line[idx+5:]
					module := extractQuotedString(rest)
					if module != "" {
						imports = append(imports, module)
					}
				}
			} else if strings.Contains(line, "require(") {
				module := extractRequire(line)
				if module != "" {
					imports = append(imports, module)
				}
			}
			// Exports
			if strings.HasPrefix(line, "export ") {
				if strings.Contains(line, "function ") {
					name := extractJSFunctionName(line)
					if name != "" {
						exports = append(exports, name)
					}
				} else if strings.Contains(line, "class ") {
					name := extractJSClassName(line)
					if name != "" {
						exports = append(exports, name)
					}
				} else if strings.Contains(line, "const ") || strings.Contains(line, "let ") {
					name := extractJSVarName(line)
					if name != "" {
						exports = append(exports, name)
					}
				}
			}
		}

	case "go":
		for _, line := range lines {
			line = strings.TrimSpace(line)
			// Import statements
			if strings.HasPrefix(line, "import ") || strings.HasPrefix(line, `"`) {
				module := extractQuotedString(line)
				if module != "" {
					imports = append(imports, module)
				}
			}
			// Exports (capitalized functions/types)
			if strings.HasPrefix(line, "func ") {
				name := extractGoFuncName(line)
				if name != "" && isExported(name) {
					exports = append(exports, name)
				}
			} else if strings.HasPrefix(line, "type ") {
				name := extractGoTypeName(line)
				if name != "" && isExported(name) {
					exports = append(exports, name)
				}
			}
		}
	}

	return imports, exports
}

func buildDependencyGraph(files []FileInfo, rootPath string) map[string][]string {
	deps := make(map[string][]string)

	// Build a map of module name -> file path
	moduleToFile := make(map[string]string)
	for _, f := range files {
		// Use file path without extension as module name
		moduleName := strings.TrimSuffix(f.Path, filepath.Ext(f.Path))
		moduleName = strings.ReplaceAll(moduleName, string(filepath.Separator), ".")
		moduleToFile[moduleName] = f.Path

		// Also map by just the filename
		baseName := strings.TrimSuffix(filepath.Base(f.Path), filepath.Ext(f.Path))
		moduleToFile[baseName] = f.Path
	}

	// For each file, resolve its imports to actual files
	for _, f := range files {
		var resolvedDeps []string
		for _, imp := range f.Imports {
			// Try to resolve import to a file in the codebase
			imp = strings.ReplaceAll(imp, ".", string(filepath.Separator))
			if targetFile, ok := moduleToFile[imp]; ok {
				resolvedDeps = append(resolvedDeps, targetFile)
			}
		}
		if len(resolvedDeps) > 0 {
			deps[f.Path] = resolvedDeps
		}
	}

	return deps
}

// Helper functions for parsing

func extractFunctionName(line string) string {
	// "def function_name(args):" -> "function_name"
	line = strings.TrimPrefix(line, "def ")
	if idx := strings.Index(line, "("); idx != -1 {
		return line[:idx]
	}
	return ""
}

func extractClassName(line string) string {
	// "class ClassName:" or "class ClassName(Base):" -> "ClassName"
	line = strings.TrimPrefix(line, "class ")
	if idx := strings.Index(line, "("); idx != -1 {
		return line[:idx]
	}
	if idx := strings.Index(line, ":"); idx != -1 {
		return line[:idx]
	}
	return ""
}

func extractQuotedString(s string) string {
	// Extract string between quotes
	for _, q := range []string{`"`, `'`, "`"} {
		if start := strings.Index(s, q); start != -1 {
			rest := s[start+1:]
			if end := strings.Index(rest, q); end != -1 {
				return rest[:end]
			}
		}
	}
	return ""
}

func extractRequire(line string) string {
	if idx := strings.Index(line, "require("); idx != -1 {
		rest := line[idx+8:]
		return extractQuotedString(rest)
	}
	return ""
}

func extractJSFunctionName(line string) string {
	if idx := strings.Index(line, "function "); idx != -1 {
		rest := line[idx+9:]
		if end := strings.Index(rest, "("); end != -1 {
			return strings.TrimSpace(rest[:end])
		}
	}
	return ""
}

func extractJSClassName(line string) string {
	if idx := strings.Index(line, "class "); idx != -1 {
		rest := line[idx+6:]
		if end := strings.IndexAny(rest, " {"); end != -1 {
			return strings.TrimSpace(rest[:end])
		}
	}
	return ""
}

func extractJSVarName(line string) string {
	for _, keyword := range []string{"const ", "let ", "var "} {
		if idx := strings.Index(line, keyword); idx != -1 {
			rest := line[idx+len(keyword):]
			if end := strings.IndexAny(rest, " ="); end != -1 {
				return strings.TrimSpace(rest[:end])
			}
		}
	}
	return ""
}

func extractGoFuncName(line string) string {
	line = strings.TrimPrefix(line, "func ")
	// Handle methods: (receiver) FuncName
	if strings.HasPrefix(line, "(") {
		if idx := strings.Index(line, ")"); idx != -1 {
			line = strings.TrimSpace(line[idx+1:])
		}
	}
	if idx := strings.Index(line, "("); idx != -1 {
		return line[:idx]
	}
	return ""
}

func extractGoTypeName(line string) string {
	line = strings.TrimPrefix(line, "type ")
	if idx := strings.IndexAny(line, " ["); idx != -1 {
		return line[:idx]
	}
	return ""
}

func isExported(name string) bool {
	if len(name) == 0 {
		return false
	}
	first := name[0]
	return first >= 'A' && first <= 'Z'
}
