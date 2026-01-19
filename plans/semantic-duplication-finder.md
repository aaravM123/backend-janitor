# Project Plan: Semantic Duplication Finder

## 1. The Core Idea

A from-scratch tool to find "semantic" code duplication. This means finding code blocks that are logically the same, even if they use different variable names, comments, or formatting. This is a powerful feature that standard linters cannot perform.

## 2. The Pain Point It Solves

Developers often copy-paste code and make minor changes. These "code clones" are a huge maintenance problem:
- When a bug is fixed in the original code, it often isn't fixed in the clone because no one knows it exists.
- It bloats the codebase and makes refactoring difficult.
- Normal tools that search for exact text matches cannot find these "ghost clones."

## 3. The Technical Plan (High-Level)

The algorithm works by comparing the *structure* of code, not the text itself.

**Step 1: Parse to AST (Abstract Syntax Tree)**
- For each function in the codebase, convert its source code into an AST. An AST is a tree that represents the code's logical structure.

**Step 2: Normalize the AST**
- Traverse the AST and replace parts that don't affect the logic with generic placeholders.
  - All variable names (`my_var`, `x`) become a placeholder like `VAR`.
  - All literal values (`"hello"`, `123`) become a placeholder like `LITERAL`.
- After this step, `x = 1 + 2` and `y = 3 + 4` would have the same normalized structure.

**Step 3: Generate a Fingerprint (Hash)**
- Take the entire normalized AST for a function and compute a hash of it (e.g., using SHA-256).
- This creates a unique "fingerprint" representing the function's pure logic.

**Step 4: Find Clones by Comparing Fingerprints**
- Group all functions by their fingerprint.
- Any group with more than one function contains a set of logical code clones.
- The tool then reports these groups to the user for refactoring.

## 4. Why It's Impressive

- **Solves a Hard Problem:** Goes beyond simple text matching to understand code's meaning.
- **High Value:** Directly helps developers improve code quality and reduce bugs.
- **Demonstrates Deep Skill:** Proves understanding of compiler design (ASTs), algorithms (tree traversal), and hashing.
