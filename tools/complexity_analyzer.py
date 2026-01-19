"""
Complexity Analyzer - Code Complexity Metrics

Analyzes code for complexity issues:
- Cyclomatic complexity (too many branches)
- Function length (too many lines)
- Nesting depth (too deeply nested)

Usage:
    from tools.complexity_analyzer import analyze_complexity, print_summary

    result = analyze_complexity("./my-project")
    print_summary(result)

Note: Uses AST parsing for Python. For other languages, uses heuristics.
"""

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FunctionComplexity:
    """Complexity metrics for a single function."""
    name: str
    file: str
    line: int
    cyclomatic_complexity: int  
    lines_of_code: int       
    max_nesting_depth: int    
    parameter_count: int      
    recommendation: str        
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "file": self.file,
            "line": self.line,
            "cyclomatic_complexity": self.cyclomatic_complexity,
            "lines_of_code": self.lines_of_code,
            "max_nesting_depth": self.max_nesting_depth,
            "parameter_count": self.parameter_count,
            "recommendation": self.recommendation,
            "issues": self.issues,
        }


@dataclass
class ComplexityResult:
    """Results from complexity analysis."""
    functions: list[FunctionComplexity] = field(default_factory=list)
    files_analyzed: int = 0
    total_functions: int = 0
    complex_functions: int = 0   
    average_complexity: float = 0.0

    def to_dict(self) -> dict:
        return {
            "functions": [f.to_dict() for f in self.functions],
            "files_analyzed": self.files_analyzed,
            "total_functions": self.total_functions,
            "complex_functions": self.complex_functions,
            "average_complexity": round(self.average_complexity, 2),
            "summary": {
                "ok": len([f for f in self.functions if f.recommendation == "ok"]),
                "review": len([f for f in self.functions if f.recommendation == "review"]),
                "split": len([f for f in self.functions if f.recommendation == "split"]),
                "refactor": len([f for f in self.functions if f.recommendation == "refactor"]),
            }
        }


COMPLEXITY_THRESHOLDS = {
    "cyclomatic": {
        "ok": 10,       
        "review": 20,  
        "split": 30,   

    },
    "lines": {
        "ok": 50,
        "review": 100,
        "split": 200,
    },
    "nesting": {
        "ok": 3,
        "review": 4,
        "split": 5,
    },
    "parameters": {
        "ok": 5,
        "review": 7,
        "split": 10,
    },
}


class ComplexityVisitor(ast.NodeVisitor):
    """AST visitor to calculate complexity metrics for Python code."""

    def __init__(self):
        self.functions: list[dict] = []
        self.current_complexity = 0
        self.current_nesting = 0
        self.max_nesting = 0

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._analyze_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._analyze_function(node)
        self.generic_visit(node)

    def _analyze_function(self, node):
        """Analyze a function node for complexity."""
        self.current_complexity = 1  
        self.current_nesting = 0
        self.max_nesting = 0

        complexity = self._calculate_complexity(node)

        if hasattr(node, 'end_lineno') and node.end_lineno:
            lines = node.end_lineno - node.lineno + 1
        else:
            lines = len(ast.unparse(node).split('\n')) if hasattr(ast, 'unparse') else 10

        params = len(node.args.args) + len(node.args.posonlyargs) + len(node.args.kwonlyargs)
        if node.args.vararg:
            params += 1
        if node.args.kwarg:
            params += 1

        self.functions.append({
            "name": node.name,
            "line": node.lineno,
            "complexity": complexity,
            "lines": lines,
            "nesting": self.max_nesting,
            "parameters": params,
        })

    def _calculate_complexity(self, node, depth=0) -> int:
        """
        Calculate cyclomatic complexity.

        Complexity increases with:
        - if/elif statements
        - for/while loops
        - except handlers
        - boolean operators (and/or)
        - comprehensions with conditions
        """
        complexity = 0
        self.current_nesting = depth

        if depth > self.max_nesting:
            self.max_nesting = depth

        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.IfExp)):
                complexity += 1
            elif isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                complexity += 1
            elif isinstance(child, ast.ExceptHandler):
                complexity += 1
            elif isinstance(child, ast.With):
                complexity += 1
            elif isinstance(child, ast.Assert):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
            elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                for generator in child.generators:
                    complexity += len(generator.ifs)

        return complexity + 1  


def _get_recommendation(complexity: int, lines: int, nesting: int, params: int) -> tuple[str, list[str]]:
    """
    Determine recommendation based on metrics.

    Returns: (recommendation, list of issues)
    """
    issues = []
    worst_rating = "ok"
    ratings = {"ok": 0, "review": 1, "split": 2, "refactor": 3}

    if complexity > COMPLEXITY_THRESHOLDS["cyclomatic"]["split"]:
        issues.append(f"Very high complexity ({complexity}) - consider breaking into smaller functions")
        if ratings["refactor"] > ratings[worst_rating]:
            worst_rating = "refactor"
    elif complexity > COMPLEXITY_THRESHOLDS["cyclomatic"]["review"]:
        issues.append(f"High complexity ({complexity}) - consider splitting")
        if ratings["split"] > ratings[worst_rating]:
            worst_rating = "split"
    elif complexity > COMPLEXITY_THRESHOLDS["cyclomatic"]["ok"]:
        issues.append(f"Moderate complexity ({complexity}) - review for simplification")
        if ratings["review"] > ratings[worst_rating]:
            worst_rating = "review"

    if lines > COMPLEXITY_THRESHOLDS["lines"]["split"]:
        issues.append(f"Very long function ({lines} lines) - split into smaller functions")
        if ratings["split"] > ratings[worst_rating]:
            worst_rating = "split"
    elif lines > COMPLEXITY_THRESHOLDS["lines"]["review"]:
        issues.append(f"Long function ({lines} lines) - consider splitting")
        if ratings["review"] > ratings[worst_rating]:
            worst_rating = "review"

    if nesting > COMPLEXITY_THRESHOLDS["nesting"]["split"]:
        issues.append(f"Deep nesting ({nesting} levels) - flatten with early returns or extraction")
        if ratings["split"] > ratings[worst_rating]:
            worst_rating = "split"
    elif nesting > COMPLEXITY_THRESHOLDS["nesting"]["review"]:
        issues.append(f"Moderate nesting ({nesting} levels) - consider flattening")
        if ratings["review"] > ratings[worst_rating]:
            worst_rating = "review"

    if params > COMPLEXITY_THRESHOLDS["parameters"]["split"]:
        issues.append(f"Too many parameters ({params}) - consider using a config object")
        if ratings["review"] > ratings[worst_rating]:
            worst_rating = "review"
    elif params > COMPLEXITY_THRESHOLDS["parameters"]["review"]:
        issues.append(f"Many parameters ({params}) - consider grouping")
        if ratings["review"] > ratings[worst_rating]:
            worst_rating = "review"

    return worst_rating, issues


def analyze_file(file_path: str) -> list[FunctionComplexity]:
    """Analyze a single Python file for complexity."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            source = f.read()
    except (IOError, OSError):
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    visitor = ComplexityVisitor()
    visitor.visit(tree)

    results = []
    for func in visitor.functions:
        recommendation, issues = _get_recommendation(
            func["complexity"],
            func["lines"],
            func["nesting"],
            func["parameters"],
        )

        results.append(FunctionComplexity(
            name=func["name"],
            file=file_path,
            line=func["line"],
            cyclomatic_complexity=func["complexity"],
            lines_of_code=func["lines"],
            max_nesting_depth=func["nesting"],
            parameter_count=func["parameters"],
            recommendation=recommendation,
            issues=issues,
        ))

    return results


def analyze_complexity(
    project_path: str,
    include_ok: bool = False,
    min_complexity: int = 1,
) -> ComplexityResult:
    """
    Analyze a project for code complexity.

    Args:
        project_path: Path to the project to analyze
        include_ok: Include functions with "ok" rating in results
        min_complexity: Minimum complexity to include in results

    Returns:
        ComplexityResult with all function metrics
    """
    project_path = str(Path(project_path).resolve())
    result = ComplexityResult()

    python_files = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in [
            'node_modules', 'venv', '.venv', 'env', '.env',
            '.git', '__pycache__', 'dist', 'build', '.tox',
            'egg-info', '.eggs', 'site-packages'
        ]]

        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))

    result.files_analyzed = len(python_files)

    all_functions = []
    for file_path in python_files:
        functions = analyze_file(file_path)
        all_functions.extend(functions)

    result.total_functions = len(all_functions)

    if include_ok:
        filtered = [f for f in all_functions if f.cyclomatic_complexity >= min_complexity]
    else:
        filtered = [f for f in all_functions if f.recommendation != "ok"]

    result.functions = sorted(filtered, key=lambda f: f.cyclomatic_complexity, reverse=True)

    result.complex_functions = len([f for f in all_functions if f.recommendation != "ok"])

    if all_functions:
        result.average_complexity = sum(f.cyclomatic_complexity for f in all_functions) / len(all_functions)

    return result


def print_summary(result: ComplexityResult) -> None:
    """Print a human-readable summary of the analysis."""
    print("\n" + "=" * 60)
    print("COMPLEXITY ANALYSIS")
    print("=" * 60)

    print(f"\nFiles analyzed:    {result.files_analyzed}")
    print(f"Total functions:   {result.total_functions}")
    print(f"Complex functions: {result.complex_functions}")
    print(f"Average complexity: {result.average_complexity:.1f}")

    summary = result.to_dict()["summary"]
    print("\n" + "-" * 40)
    print("BREAKDOWN")
    print("-" * 40)
    print(f"  OK (simple):       {summary['ok']}")
    print(f"  Review (moderate): {summary['review']}")
    print(f"  Split (complex):   {summary['split']}")
    print(f"  Refactor (severe): {summary['refactor']}")

    if result.functions:
        print("\n" + "-" * 40)
        print("TOP COMPLEX FUNCTIONS")
        print("-" * 40)

        for func in result.functions[:10]:
            print(f"\n  {func.name} ({func.file}:{func.line})")
            print(f"    Complexity: {func.cyclomatic_complexity}")
            print(f"    Lines: {func.lines_of_code}")
            print(f"    Nesting: {func.max_nesting_depth}")
            print(f"    Recommendation: {func.recommendation.upper()}")
            if func.issues:
                for issue in func.issues:
                    print(f"    - {issue}")

    print("\n" + "=" * 60)


def get_worst_functions(result: ComplexityResult, limit: int = 5) -> list[FunctionComplexity]:
    """Get the most complex functions that need attention."""
    return result.functions[:limit]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python complexity_analyzer.py <project_path> [--all]")
        print("\nOptions:")
        print("  --all    Include all functions (not just complex ones)")
        sys.exit(1)

    project = sys.argv[1]
    include_all = "--all" in sys.argv

    print(f"Analyzing complexity: {project}")
    result = analyze_complexity(project, include_ok=include_all)
    print_summary(result)
