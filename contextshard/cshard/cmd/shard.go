package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"

	"github.com/spf13/cobra"
)

// Shard represents a partition of the codebase
type Shard struct {
	ID            int        `json:"id"`
	Files         []FileInfo `json:"files"`
	TokenCount    int        `json:"token_count"`
	InternalDeps  int        `json:"internal_deps"`  // Dependencies within this shard
	ExternalDeps  []string   `json:"external_deps"`  // Files in other shards we depend on
	ExportedTo    []int      `json:"exported_to"`    // Shard IDs that depend on us
}

// ShardResult is the output of the shard command
type ShardResult struct {
	Shards        []Shard `json:"shards"`
	NumShards     int     `json:"num_shards"`
	TotalTokens   int     `json:"total_tokens"`
	AvgTokens     int     `json:"avg_tokens_per_shard"`
	CrossShardDeps int    `json:"cross_shard_dependencies"`
}

var shardCmd = &cobra.Command{
	Use:   "shard <index.json>",
	Short: "Partition an indexed codebase into semantic shards",
	Long: `Take a codebase index and partition it into N shards.

The sharding algorithm:
  1. Groups files that import each other (minimize cross-shard deps)
  2. Balances token count across shards
  3. Respects max tokens per shard limit

Output is JSON containing:
  - List of shards with their files
  - Token counts per shard
  - Cross-shard dependency information

Example:
  cshard shard index.json --num=4 --json`,
	Args: cobra.ExactArgs(1),
	RunE: runShard,
}

func init() {
	rootCmd.AddCommand(shardCmd)
	shardCmd.Flags().Int("num", 4, "Number of shards to create")
	shardCmd.Flags().Int("max-tokens", 100000, "Maximum tokens per shard")
}

func runShard(cmd *cobra.Command, args []string) error {
	indexPath := args[0]
	jsonOutput, _ := cmd.Flags().GetBool("json")
	numShards, _ := cmd.Flags().GetInt("num")
	maxTokens, _ := cmd.Flags().GetInt("max-tokens")

	// Load the index
	indexData, err := os.ReadFile(indexPath)
	if err != nil {
		return fmt.Errorf("failed to read index file: %w", err)
	}

	var index CodebaseIndex
	if err := json.Unmarshal(indexData, &index); err != nil {
		return fmt.Errorf("failed to parse index JSON: %w", err)
	}

	// Calculate optimal number of shards if not enough specified
	minShards := (index.TotalTokens / maxTokens) + 1
	if numShards < minShards {
		numShards = minShards
	}

	// Create shards using graph-aware partitioning
	shards := partitionCodebase(index, numShards, maxTokens)

	// Calculate cross-shard dependencies
	crossShardDeps := calculateCrossShardDeps(shards, index.Dependencies)

	// Calculate totals
	totalTokens := 0
	for _, s := range shards {
		totalTokens += s.TokenCount
	}

	result := ShardResult{
		Shards:         shards,
		NumShards:      len(shards),
		TotalTokens:    totalTokens,
		AvgTokens:      totalTokens / len(shards),
		CrossShardDeps: crossShardDeps,
	}

	// Output
	if jsonOutput {
		encoder := json.NewEncoder(os.Stdout)
		encoder.SetIndent("", "  ")
		return encoder.Encode(result)
	}

	// Human-readable output
	fmt.Printf("Created %d shards\n", len(shards))
	fmt.Printf("Total tokens: %d\n", totalTokens)
	fmt.Printf("Average tokens per shard: %d\n", result.AvgTokens)
	fmt.Printf("Cross-shard dependencies: %d\n", crossShardDeps)
	fmt.Println("\nShards:")
	for _, s := range shards {
		fmt.Printf("  Shard %d: %d files, %d tokens, %d external deps\n",
			s.ID, len(s.Files), s.TokenCount, len(s.ExternalDeps))
	}

	return nil
}

// partitionCodebase splits the codebase into shards
// Uses a greedy algorithm that respects dependencies
func partitionCodebase(index CodebaseIndex, numShards int, maxTokens int) []Shard {
	// Build reverse dependency map (who depends on me)
	reverseDeps := make(map[string][]string)
	for file, deps := range index.Dependencies {
		for _, dep := range deps {
			reverseDeps[dep] = append(reverseDeps[dep], file)
		}
	}

	// Score files by connectivity (more connections = should be grouped first)
	type fileScore struct {
		file  FileInfo
		score int
	}
	var scoredFiles []fileScore
	for _, f := range index.Files {
		score := len(index.Dependencies[f.Path]) + len(reverseDeps[f.Path])
		scoredFiles = append(scoredFiles, fileScore{file: f, score: score})
	}

	// Sort by score descending (most connected first)
	sort.Slice(scoredFiles, func(i, j int) bool {
		return scoredFiles[i].score > scoredFiles[j].score
	})

	// Initialize shards
	shards := make([]Shard, numShards)
	for i := range shards {
		shards[i] = Shard{
			ID:    i,
			Files: []FileInfo{},
		}
	}

	// Assign files to shards
	fileToShard := make(map[string]int)

	for _, sf := range scoredFiles {
		f := sf.file

		// Find best shard for this file
		bestShard := findBestShard(f, shards, index.Dependencies, fileToShard, maxTokens)

		// Add file to shard
		shards[bestShard].Files = append(shards[bestShard].Files, f)
		shards[bestShard].TokenCount += f.TokenCount
		fileToShard[f.Path] = bestShard
	}

	// Calculate external dependencies for each shard
	for i := range shards {
		shards[i].ExternalDeps = findExternalDeps(shards[i], index.Dependencies, fileToShard)
		shards[i].InternalDeps = countInternalDeps(shards[i], index.Dependencies, fileToShard)
	}

	// Calculate which shards depend on each shard
	for i := range shards {
		shards[i].ExportedTo = findExportedTo(i, shards, fileToShard, reverseDeps)
	}

	return shards
}

// findBestShard finds the optimal shard for a file
func findBestShard(f FileInfo, shards []Shard, deps map[string][]string, fileToShard map[string]int, maxTokens int) int {
	bestShard := 0
	bestScore := -1

	for i, shard := range shards {
		// Skip if shard is too full
		if shard.TokenCount+f.TokenCount > maxTokens {
			continue
		}

		// Score based on how many of this file's dependencies are in this shard
		score := 0
		for _, dep := range deps[f.Path] {
			if shardID, ok := fileToShard[dep]; ok && shardID == i {
				score += 10 // Strong preference for keeping dependencies together
			}
		}

		// Slight preference for emptier shards (load balancing)
		score -= shard.TokenCount / 10000

		if score > bestScore || bestScore == -1 {
			bestScore = score
			bestShard = i
		}
	}

	return bestShard
}

// findExternalDeps finds files in other shards that this shard depends on
func findExternalDeps(shard Shard, deps map[string][]string, fileToShard map[string]int) []string {
	external := make(map[string]bool)

	for _, f := range shard.Files {
		for _, dep := range deps[f.Path] {
			if shardID, ok := fileToShard[dep]; ok && shardID != shard.ID {
				external[dep] = true
			}
		}
	}

	var result []string
	for dep := range external {
		result = append(result, dep)
	}
	return result
}

// countInternalDeps counts dependencies within the shard
func countInternalDeps(shard Shard, deps map[string][]string, fileToShard map[string]int) int {
	count := 0
	for _, f := range shard.Files {
		for _, dep := range deps[f.Path] {
			if shardID, ok := fileToShard[dep]; ok && shardID == shard.ID {
				count++
			}
		}
	}
	return count
}

// findExportedTo finds which shards depend on files in this shard
func findExportedTo(shardID int, shards []Shard, fileToShard map[string]int, reverseDeps map[string][]string) []int {
	exportedTo := make(map[int]bool)

	for _, f := range shards[shardID].Files {
		for _, depender := range reverseDeps[f.Path] {
			if otherShardID, ok := fileToShard[depender]; ok && otherShardID != shardID {
				exportedTo[otherShardID] = true
			}
		}
	}

	var result []int
	for id := range exportedTo {
		result = append(result, id)
	}
	sort.Ints(result)
	return result
}

// calculateCrossShardDeps counts total cross-shard dependencies
func calculateCrossShardDeps(shards []Shard, deps map[string][]string) int {
	total := 0
	for _, s := range shards {
		total += len(s.ExternalDeps)
	}
	return total
}
