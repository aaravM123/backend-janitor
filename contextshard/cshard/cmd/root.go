package cmd

import (
	"github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{
	Use:   "cshard",
	Short: "Fast codebase indexing and sharding for ContextShard",
	Long: `CShard is the Go binary component of ContextShard.

It handles performance-critical operations:
  - Indexing large codebases (100k+ files)
  - Building dependency graphs
  - Semantic sharding with graph partitioning
  - Fast token counting

Python calls this binary via subprocess and receives JSON output.`,
}

// Execute runs the root command
func Execute() error {
	return rootCmd.Execute()
}

func init() {
	// Global flags
	rootCmd.PersistentFlags().Bool("json", false, "Output as JSON (for Python integration)")
	rootCmd.PersistentFlags().Bool("verbose", false, "Verbose output")
}
