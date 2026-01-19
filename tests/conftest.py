"""
Pytest configuration and shared fixtures for Backend Janitor tests.
"""

import pytest
import sys
from pathlib import Path

# Add tools directory to Python path
tools_dir = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(tools_dir))


@pytest.fixture
def sample_project(tmp_path):
    """Create a sample project structure for testing."""
    # Create directories
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()

    # Create main.py with some issues
    (tmp_path / "app" / "main.py").write_text('''
import os
import sys  # unused
import json

def main():
    """Main entry point."""
    data = json.loads('{"key": "value"}')
    return data

if __name__ == "__main__":
    main()
''')

    # Create db.py with SQL injection vulnerability
    (tmp_path / "app" / "db.py").write_text('''
def get_user(user_id):
    """Get user by ID - VULNERABLE."""
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return execute_query(query)

def execute_query(query):
    pass
''')

    # Create utils.py with unused imports
    (tmp_path / "app" / "utils.py").write_text('''
import os
import sys
import re
import json

def helper():
    return "hello"
''')

    # Create complex.py with complex function
    (tmp_path / "app" / "complex.py").write_text('''
def process_data(data, options, config, flags, mode):
    result = []
    if data is None:
        return None
    for item in data:
        if item.get('type') == 'A':
            if item.get('status') == 'active':
                if item.get('valid'):
                    result.append(item)
        elif item.get('type') == 'B':
            if mode == 'strict':
                if item.get('verified'):
                    result.append(item)
            else:
                result.append(item)
    return result
''')

    # Create a simple test file
    (tmp_path / "tests" / "test_main.py").write_text('''
def test_placeholder():
    assert True
''')

    return tmp_path


@pytest.fixture
def clean_project(tmp_path):
    """Create a clean project with no issues."""
    (tmp_path / "app").mkdir()

    (tmp_path / "app" / "main.py").write_text('''
"""Clean main module."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b
''')

    return tmp_path


@pytest.fixture
def security_findings_sample():
    """Sample security findings from semgrep."""
    return {
        "critical": [
            {
                "file": "app/db.py",
                "start_line": 3,
                "end_line": 4,
                "rule_id": "python.sqlalchemy.security.sql-injection",
                "message": "SQL injection vulnerability",
                "code_snippet": 'query = f"SELECT * FROM users WHERE id = {user_id}"'
            }
        ],
        "high": [],
        "medium": [],
        "low": [],
        "unknown": [],
        "total_count": 1
    }


@pytest.fixture
def ruff_findings_sample():
    """Sample ruff findings."""
    return {
        "unused_imports": [
            {
                "file": "app/utils.py",
                "line": 2,
                "column": 1,
                "code": "F401",
                "message": "'sys' imported but unused",
                "severity": "medium",
                "fix_available": True
            },
            {
                "file": "app/utils.py",
                "line": 3,
                "column": 1,
                "code": "F401",
                "message": "'re' imported but unused",
                "severity": "medium",
                "fix_available": True
            },
            {
                "file": "app/utils.py",
                "line": 4,
                "column": 1,
                "code": "F401",
                "message": "'json' imported but unused",
                "severity": "medium",
                "fix_available": True
            }
        ],
        "dead_code": [],
        "complexity": [],
        "style": [],
        "errors": [],
        "total_count": 3,
        "files_scanned": 1
    }


@pytest.fixture
def complexity_findings_sample():
    """Sample complexity findings."""
    return {
        "functions": [
            {
                "name": "process_data",
                "file": "app/complex.py",
                "line": 1,
                "cyclomatic_complexity": 12,
                "lines_of_code": 20,
                "max_nesting_depth": 4,
                "parameter_count": 5,
                "recommendation": "split",
                "issues": ["High cyclomatic complexity (12 > 10)"]
            }
        ],
        "summary": {
            "total_functions": 1,
            "functions_needing_attention": 1
        }
    }
