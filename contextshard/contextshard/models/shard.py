"""
Data models for code shards.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FileInfo:
    """Information about a single file."""
    path: str
    language: str
    size: int
    token_count: int
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)


@dataclass
class CodeShard:
    """
    A partition of the codebase assigned to one LLM instance.

    Like a parameter shard in FSDP, each CodeShard is "owned" by
    one LLM instance that deeply understands its contents.
    """
    id: int
    files: list[FileInfo] = field(default_factory=list)
    token_count: int = 0
    internal_deps: int = 0  # Dependencies within this shard
    external_deps: list[str] = field(default_factory=list)  # Files in other shards we need
    exported_to: list[int] = field(default_factory=list)  # Shard IDs that depend on us

    def file_list(self) -> str:
        """Get a formatted list of files for prompts."""
        return "\n".join(f"- {f.path} ({f.token_count} tokens)" for f in self.files)

    def get_content(self, root_path: str) -> dict[str, str]:
        """Read actual file contents from disk."""
        import os
        contents = {}
        for f in self.files:
            full_path = os.path.join(root_path, f.path)
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as file:
                    contents[f.path] = file.read()
            except Exception:
                contents[f.path] = f"# Error reading file: {f.path}"
        return contents

    def summary(self) -> str:
        """Generate a summary of this shard for other instances."""
        langs = {}
        for f in self.files:
            langs[f.language] = langs.get(f.language, 0) + 1

        all_exports = []
        for f in self.files:
            all_exports.extend(f.exports[:5])  # Top 5 exports per file

        return f"""Shard {self.id}:
- Files: {len(self.files)}
- Tokens: {self.token_count}
- Languages: {langs}
- Key exports: {', '.join(all_exports[:20])}
- External dependencies: {len(self.external_deps)} files
"""

    @classmethod
    def from_dict(cls, data: dict) -> "CodeShard":
        """Create a CodeShard from a dictionary (JSON from Go)."""
        files = [
            FileInfo(
                path=f["path"],
                language=f.get("language", "unknown"),
                size=f.get("size", 0),
                token_count=f.get("token_count", 0),
                imports=f.get("imports", []),
                exports=f.get("exports", []),
            )
            for f in data.get("files", [])
        ]

        return cls(
            id=data.get("id", 0),
            files=files,
            token_count=data.get("token_count", 0),
            internal_deps=data.get("internal_deps", 0),
            external_deps=data.get("external_deps", []),
            exported_to=data.get("exported_to", []),
        )
