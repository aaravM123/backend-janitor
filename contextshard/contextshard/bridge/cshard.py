"""
Bridge between Python and the Go cshard binary.

This module calls the Go binary for performance-critical operations:
- Indexing codebases
- Sharding
- Token counting

Python receives JSON output and converts to Python objects.
"""

import json
import subprocess
import os
from pathlib import Path
from typing import Optional

from ..models.shard import CodeShard, FileInfo


class CShardBridge:
    """
    Bridge to the Go cshard binary.

    The Go binary handles:
    - Fast file walking (100k+ files)
    - AST parsing for imports/exports
    - Dependency graph building
    - Graph partitioning for sharding
    - Token counting

    Python calls it via subprocess and receives JSON.
    """

    def __init__(self, binary_path: Optional[str] = None):
        """
        Initialize the bridge.

        Args:
            binary_path: Path to cshard binary. If None, looks in:
                1. contextshard/bin/cshard
                2. System PATH
        """
        if binary_path:
            self.binary = Path(binary_path)
        else:
            # Look for bundled binary
            bundled = Path(__file__).parent.parent / "bin" / "cshard"
            if os.name == 'nt':  # Windows
                bundled = bundled.with_suffix('.exe')

            if bundled.exists():
                self.binary = bundled
            else:
                # Fall back to PATH
                self.binary = Path("cshard")

    def _run(self, *args, check: bool = True) -> str:
        """Run the cshard binary with arguments."""
        cmd = [str(self.binary)] + list(args) + ["--json"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=check,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"cshard failed: {e.stderr}") from e
        except FileNotFoundError:
            raise RuntimeError(
                f"cshard binary not found at {self.binary}. "
                "Please build it with: cd cshard && go build"
            )

    def index(self, codebase_path: str, exclude_dirs: Optional[list[str]] = None) -> dict:
        """
        Index a codebase.

        Args:
            codebase_path: Path to the codebase root
            exclude_dirs: List of directory names to exclude from indexing

        Returns:
            Dictionary with:
            - files: List of file info
            - total_files: Count
            - total_tokens: Estimated tokens
            - languages: Language breakdown
            - dependencies: Import graph
        """
        args = ["index", codebase_path]
        for d in (exclude_dirs or []):
            args.append(f"--exclude={d}")
        output = self._run(*args)
        return json.loads(output)

    def shard(
        self,
        index_or_path: str | dict,
        num_shards: int = 4,
        max_tokens: int = 100000,
    ) -> list[CodeShard]:
        """
        Shard a codebase into partitions.

        Args:
            index_or_path: Either a path to index.json or index dict
            num_shards: Target number of shards
            max_tokens: Maximum tokens per shard

        Returns:
            List of CodeShard objects
        """
        # If dict, write to temp file
        if isinstance(index_or_path, dict):
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(index_or_path, f)
                index_path = f.name
        else:
            index_path = index_or_path

        output = self._run(
            "shard",
            index_path,
            f"--num={num_shards}",
            f"--max-tokens={max_tokens}",
        )

        result = json.loads(output)
        return [CodeShard.from_dict(s) for s in result.get("shards", [])]

    def count_tokens(self, path: str) -> int:
        """
        Count tokens in a file or directory.

        Args:
            path: File or directory path

        Returns:
            Estimated token count
        """
        output = self._run("tokens", path)
        result = json.loads(output)
        return result.get("tokens", 0)

    def is_available(self) -> bool:
        """Check if the cshard binary is available."""
        try:
            self._run("--help", check=False)
            return True
        except RuntimeError:
            return False


# Global instance for convenience
_bridge: Optional[CShardBridge] = None


def get_bridge() -> CShardBridge:
    """Get or create the global bridge instance."""
    global _bridge
    if _bridge is None:
        _bridge = CShardBridge()
    return _bridge
