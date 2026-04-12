---
name: review
version: 1.0.0
description: Review code for bugs, security issues, and quality.
author: OpenCortex Team
trigger_keywords:
  - review
  - "code review"
  - "check this code"
  - "any issues"
  - audit
  - inspect
required_tools:
  - read_file
  - lsp
  - grep
parameters:
  - name: focus
    type: string
    required: false
    default: "all"
    description: Review focus: "all", "security", "performance", "bugs", or "style"
  - name: severity
    type: string
    required: false
    default: "all"
    description: Minimum severity to report: "critical", "major", "minor", or "all"
---

# Code Review

Review code for bugs, security issues, performance problems, and quality concerns.

## When to use

Use this skill when the user asks to:
- Review code, a PR, or a diff
- Check for bugs or security issues
- Audit code quality
- Inspect specific files or changes
- "Look at this code and tell me if there are any issues"

## Workflow

1. **Read the code thoroughly**:
   - Read all changed files or the target diff
   - Understand the context and purpose of the changes
   - Note the scope and impact of the changes

2. **Check for issues**:

   **Bugs**:
   - Logic errors and off-by-one errors
   - Null/undefined access and missing error handling
   - Race conditions and concurrency issues
   - Incorrect assumptions about data

   **Security**:
   - Injection vulnerabilities (SQL, command, XSS)
   - Hardcoded secrets and credentials
   - Path traversal and file access issues
   - Missing authentication or authorization
   - Insecure cryptography or random number generation

   **Performance**:
   - N+1 queries and inefficient database access
   - Unnecessary allocations or copies
   - Missing indexes or database optimization
   - Inefficient algorithms or data structures
   - Resource leaks (unclosed files, connections)

   **Tests**:
   - Are new code paths covered by tests?
   - Are edge cases tested?
   - Are tests independent and deterministic?
   - Do tests verify behavior, not implementation?

   **Style & Maintainability**:
   - Naming consistency and clarity
   - Dead code and unused variables
   - Unnecessary complexity or over-engineering
   - Inconsistent patterns with the rest of the codebase
   - Missing or outdated documentation

3. **Prioritize findings**:
   - **Critical**: Security vulnerabilities, data loss risks
   - **Major**: Bugs that break functionality
   - **Minor**: Style issues, minor optimizations
   - **Nit**: Small improvements that don't affect behavior

4. **Provide actionable feedback**:
   - Include file:line references for each issue
   - Explain why it's a problem
   - Suggest specific fixes
   - Prioritize by severity
   - Acknowledge good patterns too

## Rules

- **Be specific**: "line 42 may throw if `user` is null" not "check for null"
- **Suggest fixes**: Don't just point out problems — provide solutions
- **Be balanced**: Acknowledge good patterns and well-written code
- **Prioritize**: Focus on critical and major issues first
- **Avoid nitpicks**: Don't comment on formatting if there's a linter
- **Explain context**: Help the author understand why something is problematic
- **Be constructive**: Tone should be helpful, not critical

## Examples

### Example 1: Security-focused review

```markdown
User: Review this authentication code for security issues

Agent: I'll review the authentication code for security vulnerabilities.

[Reads the authentication code]
[Checks for common security issues]
[Reports:]

## Security Issues

### Critical: SQL Injection Vulnerability
**File:** src/auth/login.py:42
**Issue:** User input is directly interpolated into SQL query
```python
query = f"SELECT * FROM users WHERE username = '{username}'"
```
**Fix:** Use parameterized queries:
```python
query = "SELECT * FROM users WHERE username = ?"
cursor.execute(query, (username,))
```

### Major: Timing Attack Vulnerability
**File:** src/auth/password.py:18
**Issue:** String comparison is vulnerable to timing attacks
```python
if stored_hash == user_hash:
```
**Fix:** Use constant-time comparison:
```python
import hmac
if hmac.compare_digest(stored_hash, user_hash):
```

## Good Practices
+ Password hashing uses bcrypt with appropriate work factor
+ Session tokens are generated with cryptographically secure RNG
```

### Example 2: Performance review

```markdown
User: Review this database query code for performance issues

Agent: I'll review the database code for performance problems.

[Reads the query code]
[Analyzes query patterns]
[Reports:]

## Performance Issues

### Major: N+1 Query Problem
**File:** src/services/user.py:55
**Issue:** Querying inside a loop causes N database calls
```python
for user_id in user_ids:
    user = db.query("SELECT * FROM users WHERE id = ?", (user_id,))
```
**Fix:** Batch the query:
```python
users = db.query("SELECT * FROM users WHERE id IN ({})".format(
    ','.join('?' * len(user_ids))
), user_ids)
```

### Minor: Missing Index
**File:** src/services/user.py:62
**Issue:** Query filters on `email` but no index exists
```sql
SELECT * FROM users WHERE email = ?
```
**Fix:** Add index on `email` column for faster lookups

## Good Practices
+ Connection pooling is configured correctly
+ Queries use LIMIT to prevent large result sets
```

### Example 3: General code review

```markdown
User: Review my changes to the payment processor

Agent: I'll review the payment processor changes.

[Reads the diff]
[Checks various aspects]
[Reports:]

## Critical Issues

### Missing Error Handling
**File:** src/payment/processor.py:78
**Issue:** No exception handling for payment gateway failures
**Impact:** Payment failures could crash the entire process
**Fix:** Wrap in try-except and handle gateway errors gracefully

## Major Issues

### Inconsistent Error Codes
**File:** src/payment/processor.py:95
**Issue:** Error codes don't match the documentation
**Fix:** Update error codes to match API spec

## Minor Issues

### Unclear Variable Name
**File:** src/payment/processor.py:23
**Issue:** Variable `data` is too generic
**Fix:** Rename to `payment_request` for clarity

## Positive Notes
+ Good separation of concerns
+ Comprehensive logging added
+ Tests cover edge cases
```

## See also

- `debug` - Debugging issues found during review
- `simplify` - Refactoring complex code found during review
- `test` - Writing tests for issues found during review
