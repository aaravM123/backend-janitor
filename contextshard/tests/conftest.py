"""
Shared fixtures and mocks for ContextShard tests.
"""

import pytest
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, AsyncMock

# Add contextshard to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from contextshard.models.shard import CodeShard, FileInfo
from contextshard.models.context import (
    ContextUpdate,
    Export,
    Dependency,
    Finding,
    Question,
)
from contextshard.models.result import ShardResult, UnifiedResult, CrossShardIssue


# =============================================================================
# MOCK LLM RESPONSES
# =============================================================================

MOCK_DISCOVERY_RESPONSE = """Based on my analysis of the code in my shard:

1. EXPORTS:
EXPORT: function login in auth/login.py - Handles user authentication
EXPORT: class UserService in services/user.py - User management service
EXPORT: variable DB_CONFIG in config/database.py - Database configuration

2. IMPORTS:
IMPORT: query from db/queries.py - Used for database queries
IMPORT: validate from utils/validation.py - Input validation

3. INITIAL FINDINGS:
FINDING: [HIGH] sql_injection in api/routes.py:42 - SQL injection in user query
FINDING: [MEDIUM] hardcoded_secret in config/settings.py:15 - Hardcoded API key
"""

MOCK_ANALYSIS_RESPONSE = """Based on my analysis with cross-shard context:

1. SECURITY FINDINGS:
SECURITY: [CRITICAL] sql_injection in api/routes.py:42
Description: User input passed directly to SQL query without sanitization
Cross-shard context: The validate() function from shard 1 is not being used
Suggested fix: Use parameterized queries or ORM

SECURITY: [HIGH] command_injection in services/exec.py:28
Description: Shell command built with user input
Cross-shard context: None
Suggested fix: Use subprocess with list arguments

2. CROSS-SHARD ISSUES:
CROSS_SHARD: [CRITICAL] Unsanitized Data Flow
Shards involved: 0, 1, 2
Attack path: api/routes.py -> db/queries.py -> services/user.py
Description: User input flows from API to DB without validation

3. QUESTIONS:
QUESTION for shard 1: Does the validate() function sanitize SQL input?
Context: Need to determine if validation prevents injection
"""


# =============================================================================
# MOCK LLM CLIENT
# =============================================================================

@dataclass
class MockChoice:
    """Mock OpenAI choice object."""
    message: "MockMessage"


@dataclass
class MockMessage:
    """Mock OpenAI message object."""
    content: str
    role: str = "assistant"


@dataclass
class MockCompletion:
    """Mock OpenAI completion response."""
    choices: list[MockChoice]
    usage: Optional[dict] = None


class MockChatCompletions:
    """Mock for llm_client.chat.completions."""

    def __init__(self, responses: list[str] = None):
        self.responses = responses or [MOCK_DISCOVERY_RESPONSE, MOCK_ANALYSIS_RESPONSE]
        self.call_count = 0
        self.call_history = []

    async def create(self, **kwargs):
        """Return mock completion."""
        self.call_history.append(kwargs)
        response_content = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return MockCompletion(
            choices=[MockChoice(message=MockMessage(content=response_content))],
            usage={"total_tokens": 1000},
        )


class MockChat:
    """Mock for llm_client.chat."""

    def __init__(self, responses: list[str] = None):
        self.completions = MockChatCompletions(responses)


class MockLLMClient:
    """Mock LLM client for testing without API calls."""

    def __init__(self, responses: list[str] = None):
        self.chat = MockChat(responses)


# =============================================================================
# FIXTURES - DATA MODELS
# =============================================================================

@pytest.fixture
def sample_file_info():
    """Create sample FileInfo."""
    return FileInfo(
        path="api/routes.py",
        language="python",
        size=1500,
        token_count=500,
        imports=["from db import query", "from utils import validate"],
        exports=["handle_request", "process_user"],
    )


@pytest.fixture
def sample_file_info_list():
    """Create list of FileInfo objects."""
    return [
        FileInfo(
            path="api/routes.py",
            language="python",
            size=1500,
            token_count=500,
            imports=["from db import query"],
            exports=["handle_request"],
        ),
        FileInfo(
            path="api/auth.py",
            language="python",
            size=800,
            token_count=250,
            imports=["from utils import hash_password"],
            exports=["login", "logout"],
        ),
        FileInfo(
            path="api/utils.py",
            language="python",
            size=400,
            token_count=100,
            imports=[],
            exports=["sanitize", "validate"],
        ),
    ]


@pytest.fixture
def sample_code_shard(sample_file_info_list):
    """Create sample CodeShard."""
    return CodeShard(
        id=0,
        files=sample_file_info_list,
        token_count=850,
        internal_deps=2,
        external_deps=["db/queries.py", "services/user.py"],
        exported_to=[1, 2],
    )


@pytest.fixture
def sample_export():
    """Create sample Export."""
    return Export(
        name="login",
        type="function",
        file="auth/login.py",
        shard_id=0,
        signature="def login(username: str, password: str) -> User",
    )


@pytest.fixture
def sample_dependency():
    """Create sample Dependency."""
    return Dependency(
        from_file="api/routes.py",
        from_shard=0,
        to_file="db/queries.py",
        to_shard=1,
        symbol="query",
    )


@pytest.fixture
def sample_finding():
    """Create sample Finding."""
    return Finding(
        shard_id=0,
        file="api/routes.py",
        line=42,
        severity="high",
        category="sql_injection",
        message="SQL injection vulnerability in user query",
        code_snippet='query = f"SELECT * FROM users WHERE id = {user_id}"',
        suggested_fix="Use parameterized queries",
        cross_shard_context=None,
    )


@pytest.fixture
def sample_question():
    """Create sample Question."""
    return Question(
        from_shard=0,
        to_shard=1,
        question="Does the validate() function sanitize SQL input?",
        context="Need to determine if validation prevents injection attacks",
        answered=False,
        answer=None,
    )


@pytest.fixture
def sample_context_update(sample_export, sample_dependency, sample_finding, sample_question):
    """Create sample ContextUpdate with data."""
    return ContextUpdate(
        round_num=1,
        exports=[sample_export],
        dependencies=[sample_dependency],
        findings=[sample_finding],
        questions=[sample_question],
    )


@pytest.fixture
def empty_context_update():
    """Create empty ContextUpdate."""
    return ContextUpdate(round_num=0)


@pytest.fixture
def sample_shard_result(sample_export, sample_finding):
    """Create sample ShardResult."""
    return ShardResult(
        shard_id=0,
        round_num=0,
        discovered_exports=[sample_export],
        discovered_dependencies=[],
        security_findings=[sample_finding],
        quality_findings=[],
        questions_for_others=[],
        answers=[],
        raw_response=MOCK_DISCOVERY_RESPONSE,
        tokens_used=500,
        duration_ms=1000,
    )


@pytest.fixture
def sample_cross_shard_issue():
    """Create sample CrossShardIssue."""
    return CrossShardIssue(
        title="Unsanitized Data Flow",
        severity="critical",
        involved_shards=[0, 1, 2],
        attack_path=["api/routes.py", "db/queries.py", "services/user.py"],
        description="User input flows from API to DB without validation",
        recommendation="Add input validation at API layer",
    )


@pytest.fixture
def sample_unified_result(sample_finding, sample_cross_shard_issue):
    """Create sample UnifiedResult."""
    result = UnifiedResult(
        findings=[sample_finding],
        cross_shard_issues=[sample_cross_shard_issue],
        total_files_analyzed=10,
        total_tokens_processed=5000,
        num_shards=4,
        num_rounds=3,
        files_with_issues=["api/routes.py"],
        clean_files=["api/utils.py", "config/settings.py"],
        shard_summaries=[
            {"id": 0, "files": 3, "tokens": 850, "findings": 1},
            {"id": 1, "files": 2, "tokens": 600, "findings": 0},
        ],
        total_duration_ms=5000,
    )
    return result


# =============================================================================
# FIXTURES - MOCK CLIENTS
# =============================================================================

@pytest.fixture
def mock_llm_client():
    """Create mock LLM client."""
    return MockLLMClient()


@pytest.fixture
def mock_llm_client_with_custom_responses():
    """Factory fixture for custom mock responses."""
    def _create(responses: list[str]):
        return MockLLMClient(responses)
    return _create


# =============================================================================
# FIXTURES - TEMPORARY FILES
# =============================================================================

@pytest.fixture
def sample_codebase(tmp_path):
    """Create a temporary sample codebase for testing."""
    # Create directory structure
    (tmp_path / "api").mkdir()
    (tmp_path / "db").mkdir()
    (tmp_path / "services").mkdir()

    # Create sample files with intentional vulnerabilities
    (tmp_path / "api" / "routes.py").write_text('''
"""API routes with SQL injection vulnerability."""

def get_user(user_id):
    # SQL INJECTION - user_id not sanitized
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return execute_query(query)

def search_users(name):
    # Another SQL injection
    query = "SELECT * FROM users WHERE name = '%s'" % name
    return execute_query(query)
''')

    (tmp_path / "api" / "auth.py").write_text('''
"""Authentication with hardcoded secret."""

# HARDCODED SECRET
API_KEY = "sk-secret-key-12345"
PASSWORD = "admin123"

def login(username, password):
    if password == PASSWORD:
        return generate_token(API_KEY)
    return None
''')

    (tmp_path / "db" / "queries.py").write_text('''
"""Database queries - uses input from api/routes.py."""
from api.routes import get_user

def execute_query(query):
    # Executes raw SQL - called by routes.py
    return db.execute(query)

def get_user_data(user_id):
    # Cross-shard dependency
    user = get_user(user_id)
    return process_user(user)
''')

    (tmp_path / "services" / "user_service.py").write_text('''
"""User service - depends on db/queries.py."""
from db.queries import get_user_data

class UserService:
    def get_profile(self, user_id):
        # Uses potentially tainted data
        data = get_user_data(user_id)
        return self.format_profile(data)

    def format_profile(self, data):
        return data
''')

    (tmp_path / "main.py").write_text('''
"""Main entry point."""
from api.routes import get_user, search_users
from services.user_service import UserService

def main():
    service = UserService()
    # User input flows through system
    user_id = input("Enter user ID: ")
    profile = service.get_profile(user_id)
    print(profile)

if __name__ == "__main__":
    main()
''')

    return tmp_path


# =============================================================================
# FIXTURES - MULTIPLE SHARDS
# =============================================================================

@pytest.fixture
def multiple_shards():
    """Create multiple CodeShard objects for testing."""
    return [
        CodeShard(
            id=0,
            files=[
                FileInfo(path="api/routes.py", language="python", size=1000, token_count=300,
                        imports=["from db import query"], exports=["get_user"]),
                FileInfo(path="api/auth.py", language="python", size=500, token_count=150,
                        imports=[], exports=["login"]),
            ],
            token_count=450,
            internal_deps=1,
            external_deps=["db/queries.py"],
            exported_to=[1],
        ),
        CodeShard(
            id=1,
            files=[
                FileInfo(path="db/queries.py", language="python", size=800, token_count=250,
                        imports=["from api import get_user"], exports=["execute_query"]),
                FileInfo(path="db/connection.py", language="python", size=300, token_count=100,
                        imports=[], exports=["connect"]),
            ],
            token_count=350,
            internal_deps=1,
            external_deps=["api/routes.py"],
            exported_to=[0, 2],
        ),
        CodeShard(
            id=2,
            files=[
                FileInfo(path="services/user.py", language="python", size=600, token_count=200,
                        imports=["from db import execute_query"], exports=["UserService"]),
            ],
            token_count=200,
            internal_deps=0,
            external_deps=["db/queries.py"],
            exported_to=[],
        ),
    ]


@pytest.fixture
def multiple_shard_results():
    """Create ShardResult objects for multiple shards."""
    return [
        ShardResult(
            shard_id=0,
            round_num=0,
            discovered_exports=[
                Export(name="get_user", type="function", file="api/routes.py", shard_id=0),
                Export(name="login", type="function", file="api/auth.py", shard_id=0),
            ],
            discovered_dependencies=[],
            security_findings=[
                Finding(shard_id=0, file="api/routes.py", line=42, severity="critical",
                       category="sql_injection", message="SQL injection", code_snippet="..."),
            ],
            quality_findings=[],
            questions_for_others=[{"to_shard": 1, "question": "Is query sanitized?"}],
        ),
        ShardResult(
            shard_id=1,
            round_num=0,
            discovered_exports=[
                Export(name="execute_query", type="function", file="db/queries.py", shard_id=1),
            ],
            discovered_dependencies=[
                Dependency(from_file="db/queries.py", from_shard=1,
                          to_file="api/routes.py", to_shard=0, symbol="get_user"),
            ],
            security_findings=[],
            quality_findings=[],
            questions_for_others=[],
        ),
        ShardResult(
            shard_id=2,
            round_num=0,
            discovered_exports=[
                Export(name="UserService", type="class", file="services/user.py", shard_id=2),
            ],
            discovered_dependencies=[],
            security_findings=[
                Finding(shard_id=2, file="services/user.py", line=10, severity="medium",
                       category="logging", message="Sensitive data logged", code_snippet="..."),
            ],
            quality_findings=[],
            questions_for_others=[],
        ),
    ]
