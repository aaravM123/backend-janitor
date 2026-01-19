package cmd

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"
)

var tokensCmd = &cobra.Command{
	Use:   "tokens <path>",
	Short: "Count tokens in a file or directory",
	Long: `Estimate the token count for a file or directory.

Uses a simple heuristic: ~4 characters per token (works reasonably
well for code). For more accurate counts, use a proper tokenizer.

Example:
  cshard tokens ./my-file.py
  cshard tokens ./my-project`,
	Args: cobra.ExactArgs(1),
	RunE: runTokens,
}

func init() {
	rootCmd.AddCommand(tokensCmd)
}

func runTokens(cmd *cobra.Command, args []string) error {
	path := args[0]
	jsonOutput, _ := cmd.Flags().GetBool("json")

	// Check if path exists
	info, err := os.Stat(path)
	if os.IsNotExist(err) {
		return fmt.Errorf("path does not exist: %s", path)
	}

	var totalTokens int
	var totalFiles int
	var totalBytes int64

	if info.IsDir() {
		// Walk directory
		err = filepath.Walk(path, func(p string, fi os.FileInfo, err error) error {
			if err != nil {
				return nil
			}
			if fi.IsDir() {
				if skipDirs[fi.Name()] {
					return filepath.SkipDir
				}
				return nil
			}

			// Only count source files
			ext := filepath.Ext(p)
			if _, ok := languageExtensions[ext]; ok {
				totalBytes += fi.Size()
				totalTokens += int(fi.Size()) / 4
				totalFiles++
			}
			return nil
		})
		if err != nil {
			return fmt.Errorf("failed to walk directory: %w", err)
		}
	} else {
		// Single file
		totalBytes = info.Size()
		totalTokens = int(info.Size()) / 4
		totalFiles = 1
	}

	if jsonOutput {
		fmt.Printf(`{"tokens": %d, "files": %d, "bytes": %d}`, totalTokens, totalFiles, totalBytes)
		fmt.Println()
	} else {
		fmt.Printf("Tokens: %d (estimated)\n", totalTokens)
		fmt.Printf("Files: %d\n", totalFiles)
		fmt.Printf("Bytes: %d\n", totalBytes)
	}

	return nil
}
