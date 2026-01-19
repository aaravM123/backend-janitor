# Backend Janitor CLI Usage

The CLI is a thin wrapper around Goose recipes. It builds the right recipe
and parameters, then runs `goose run`.

## Commands

scan
- Run a scan without fixes.
- Modes: security, tech-debt, full (default: full).

fix
- Fix issues with approvals.
- Modes: security, tech-debt, full (default: full).
- Full mode strategy: safe, approved, all (default: safe).

pr
- Run full maintenance and open a PR.

report
- Alias for `scan --mode full`.

## Mode-specific flags

Security modes:
- --severity-filter all|medium|high|critical
- --semgrep-config auto|p/security-audit|p/owasp-top-ten|path

Tech-debt modes:
- --focus-area all|unused_code|complexity|style
- --complexity-threshold N

Full mode:
- --priority security_first|tech_debt_first|severity|quick_wins
- --strategy safe|approved|all (fix only)
- --create-pr
- --pr-title "Custom title"

## Common flags

- --project-path PATH
- --config PATH
- --goose-cmd PATH
- --interactive
- --debug
- --no-session
- --max-turns N
- --provider NAME
- --model NAME
- --output-format text|json
- --quiet
- --goose-arg "--flag" (repeatable)
- --dry-run
- --verbose

## Examples

python scripts/backend-janitor scan --mode full --project-path .
python scripts/backend-janitor scan --mode security --severity-filter high --project-path .
python scripts/backend-janitor scan --mode tech-debt --focus-area unused_code --project-path .
python scripts/backend-janitor fix --mode full --strategy safe --project-path .
python scripts/backend-janitor fix --mode security --severity-filter high --project-path .
python scripts/backend-janitor pr --project-path .

## PR Creator Dry Run

To validate PR steps without pushing, use:

python tools/pr_creator.py create --dry-run "Test PR"
