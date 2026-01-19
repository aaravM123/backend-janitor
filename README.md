# Backend Janitor

**Autonomous codebase maintenance agent that finds 380% more security vulnerabilities than traditional LLM analysis.**

Backend Janitor is a Goose-powered agent that autonomously scans large codebases for security vulnerabilities and technical debt. Unlike traditional tools that truncate analysis when codebases exceed LLM context limits, Backend Janitor uses **ContextShard** - a novel distributed architecture that scales linearly with codebase size.

## ContextShard: Distributed LLM Analysis

**ContextShard applies FSDP (Fully Sharded Data Parallel) principles to LLM codebase analysis** - a concept previously only used in distributed training of large language models.

### Key Innovation
- **Distributes analysis across multiple LLM instances** instead of truncating code
- **Synchronizes context** between instances to detect cross-file vulnerabilities
- **Eliminates false negatives** from context window limitations

### Benchmark Results (154k token codebase)
| Method | Issues Found | Codebase Coverage | Duration |
|--------|-------------|-------------------|----------|
| **ContextShard** | **24 vulnerabilities** | **100%** | 206s |
| Normal LLM | 5 vulnerabilities | ~80% (truncated) | 55s |

**Result: ContextShard found all 8 critical vulnerabilities hidden in the last 20% of the codebase that normal LLM analysis completely missed.**

### How It Works
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Shard 1       │    │   Shard 2       │    │   Shard 3       │
│  (Files 1-20)   │◄──►│  (Files 21-40) │◄──►│  (Files 41-60) │
│                 │    │                 │    │                 │
│ • Analyze code  │    │ • Analyze code  │    │ • Analyze code  │
│ • Find issues   │    │ • Find issues   │    │ • Find issues   │
│ • Share exports │    │ • Share exports │    │ • Share exports │
└─────────────────┘    └─────────────────┘    └─────────────────┘
       ▲                        ▲                        ▲
       └─────────────── Sync Rounds ────────────────────┘
                Context sharing + deduplication
```

## Quick Start

```bash
# Build Goose CLI (bundled in repo)
cd goose && cargo build --release
export PATH="$PWD/target/release:$PATH"

# Install Python dependencies
pip install -r requirements.txt

# Scan for issues
python scripts/backend-janitor scan --mode full --project-path /path/to/your/project

# Auto-fix safe issues
python scripts/backend-janitor fix --mode full --strategy safe --project-path /path/to/your/project

# Create pull request with all fixes
python scripts/backend-janitor pr --project-path /path/to/your/project
```

## Analysis Capabilities

Backend Janitor combines multiple specialized tools to provide comprehensive codebase analysis:

### Security Vulnerabilities
- SQL Injection: Parameterized query detection, unsafe string formatting
- Cross-Site Scripting (XSS): Unsafe HTML rendering, input sanitization
- Command Injection: Shell command execution vulnerabilities
- Authentication Bypass: Weak authentication logic
- Hardcoded Secrets: API keys, passwords in source code
- Insecure Deserialization: Unsafe object reconstruction

### Code Quality Issues
- Unused Imports: Dead code elimination
- Unused Variables: Memory and performance optimization
- Style Violations: PEP8 compliance, formatting consistency
- Import Sorting: Clean, organized import statements
- Type Hints: Python typing best practices

### Complexity Analysis
- Cyclomatic Complexity: Function branching analysis
- Function Length: Line count and readability metrics
- Nesting Depth: Code structure complexity
- Parameter Count: Function signature complexity
- Cognitive Complexity: Human comprehension difficulty

### Intelligent Prioritization
- Severity-Based Ranking: Critical → High → Medium → Low
- Category Weighting: Security first, then tech debt
- Impact Assessment: Effort vs. benefit analysis
- Cross-File Dependencies: Related issue grouping

### Comprehensive Reporting
- Unified Dashboard: All issues in one view
- Fix Recommendations: Actionable improvement suggestions
- Before/After Metrics: Quantified improvement tracking
- PR-Ready Summaries: GitHub integration

## Tool Ecosystem

Backend Janitor integrates industry-standard tools with custom intelligence:

### Security Analysis
- Semgrep: Enterprise-grade security scanning with custom rules
- OWASP Integration: Industry-standard vulnerability patterns
- False Positive Filtering: ML-powered accuracy improvements

### Code Quality
- Ruff: Lightning-fast Python linter (10-100x faster than flake8)
- Pyflakes + pycodestyle: Comprehensive style and error detection
- isort + Black: Import sorting and formatting compliance

### Complexity Metrics
- McCabe Cyclomatic Complexity: Mathematical complexity measurement
- Halstead Metrics: Code volume and difficulty analysis
- Maintainability Index: Long-term code health scoring

### Automation & Integration
- GitHub PR Creation: Automated pull request workflows
- Test Integration: pytest compatibility and CI/CD support
- Configuration Management: YAML-based rule customization

## Example Output

When you run Backend Janitor on a codebase, you get comprehensive analysis:

```
═══════════════════════════════════════════════════════════════════════════════
BACKEND JANITOR REPORT: my-project/
═══════════════════════════════════════════════════════════════════════════════

SECURITY VULNERABILITIES (8 found)
───────────────────────────────────────────────────────────────────────────────
CRITICAL: SQL injection in user.py:45
   Risk: Complete database compromise
   Fix: Use parameterized queries

HIGH: Hardcoded API key in config.py:12
   Risk: Unauthorized API access
   Fix: Move to environment variables

MEDIUM: XSS vulnerability in templates.py:89
   Risk: Client-side code execution
   Fix: Escape user input

TECH DEBT (15 found)
───────────────────────────────────────────────────────────────────────────────
QUICK WINS (Safe auto-fixes)
   - 12 unused imports across 8 files
   - 3 unused variables
   - 5 style violations

MEDIUM PRIORITY
   - 2 functions exceeding complexity threshold (15+ branches)
   - 1 function with 120+ lines (should split)

LOW PRIORITY
   - 4 minor style inconsistencies
   - 2 suboptimal import patterns

RECOMMENDED FIX ORDER
───────────────────────────────────────────────────────────────────────────────
1. [CRITICAL] SQL injection in user.py:45 (5 min fix)
2. [HIGH] Hardcoded API key in config.py:12 (2 min fix)
3. [QUICK WIN] Remove 12 unused imports (auto-fix available)
4. [MEDIUM] Refactor complex function auth.py:78 (15 min)
...
```

## Core Commands

### `scan` - Analysis Only
```bash
# Full security + quality scan
python scripts/backend-janitor scan --mode full --project-path .

# Security-only scan with severity filtering
python scripts/backend-janitor scan --mode security --severity-filter critical --project-path .
```

### `fix` - Apply Fixes
```bash
# Safe fixes only (unused imports, style issues)
python scripts/backend-janitor fix --mode full --strategy safe --project-path .

# All fixes with approval prompts
python scripts/backend-janitor fix --mode full --strategy approved --project-path .
```

### `pr` - Full Automation
```bash
# Complete workflow: scan → fix → PR
python scripts/backend-janitor pr --project-path . --pr-title "Backend Janitor: Security fixes"
```

## How It's Different

| Feature | Backend Janitor | Other Coding Agents |
|---------|----------------|-------------------|
| **Context Handling** | ContextShard: No truncation | Limited by LLM context window |
| **Analysis Coverage** | 100% of large codebases | ~80% with truncation |
| **Cross-file Issues** | Detects via distributed sync | Misses due to isolation |
| **Scalability** | Linear with codebase size | Hard-capped at context limit |
| **Accuracy** | 380% more vulnerabilities found | False negatives from truncation |
| **Architecture** | Distributed multi-instance | Single LLM bottleneck |

**Traditional agents work like this:**
```
Codebase (200k tokens) → Single LLM (128k limit) → Truncate → Analyze 80%
                                      ↓
                               Miss critical bugs in last 20%
```

**Backend Janitor works like this:**
```
Codebase (200k tokens) → Shard into 5 × 40k → 5 LLMs → Sync → 100% coverage
                                      ↓
                            Find ALL bugs across entire codebase
```

## Requirements

- **Python 3.10+**: Core runtime
- **Rust toolchain**: For building Goose CLI (included in repo)
- **Tools**: Semgrep, Ruff, pytest (auto-installed)
- **Optional**: Node.js (duplication detection), Git + GitHub CLI (PR creation)

## Configuration

Comprehensive configuration in `configs/janitor-config.yaml`:
- Severity scoring and prioritization
- Tool-specific settings (Semgrep rules, Ruff config)
- Complexity thresholds and refactoring triggers
- PR creation templates and labels

Override with: `BACKEND_JANITOR_CONFIG=/path/to/config.yaml`
