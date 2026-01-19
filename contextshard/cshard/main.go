/*
CShard - Fast codebase indexing and sharding for ContextShard

This binary handles the heavy lifting:
- Indexing codebases (file walking, AST parsing)
- Building dependency graphs
- Semantic sharding (graph partitioning)
- Token counting

Python calls this binary and receives JSON output.

Usage:
  cshard index <path>           Index a codebase, output JSON
  cshard shard <index> --num=N  Split index into N shards
  cshard tokens <file>          Count tokens in a file
*/
package main

import (
	"fmt"
	"os"

	"github.com/backend-janitor/cshard/cmd"
)

func main() {
	if err := cmd.Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
