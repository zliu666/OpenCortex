---
name: debug
version: 1.0.0
description: Diagnose and fix bugs systematically.
author: OpenCortex Team
trigger_keywords:
  - debug
  - bug
  - error
  - "not working"
  - "broken"
  - "fix this"
  - "unexpected behavior"
required_tools:
  - bash
  - grep
  - read_file
parameters:
  - name: max_attempts
    type: integer
    required: false
    default: 3
    description: Maximum fix attempts before asking for help
---

# Debug

Diagnose and fix bugs systematically using evidence-based debugging.

## When to use

Use this skill when the user:
- Reports a bug, error, or unexpected behavior
- Describes something "not working" or "broken"
- Provides an error message or stack trace
- Asks to investigate incorrect behavior

## Workflow

1. **Reproduce the issue**:
   - Understand the exact steps that trigger the problem
   - Note error messages, stack traces, or unexpected output
   - Identify the context (environment, input data, timing)

2. **Read the error**:
   - Parse stack traces to find the failure point
   - Note error types and messages
   - Look for relevant log messages or error codes

3. **Locate relevant code**:
   - Use grep to find error messages or stack trace locations
   - Read files mentioned in the stack trace
   - Examine related code paths

4. **Form a hypothesis**:
   - Based on evidence, form a theory about the root cause
   - Consider multiple possible causes
   - Prioritize most likely explanations

5. **Verify the hypothesis**:
   - Add logging or read surrounding code to confirm
   - Check if the hypothesis explains all symptoms
   - Look for contradictory evidence

6. **Implement a fix**:
   - Make the minimal change that addresses the root cause
   - Avoid changing unrelated code
   - Add comments if the fix is non-obvious

7. **Test the fix**:
   - Verify the fix resolves the issue
   - Check that it doesn't break other functionality
   - Consider edge cases

## Rules

- **Evidence first**: Read the error message carefully before searching code
- **Don't guess**: Verify your hypothesis before changing code
- **Root cause**: Fix the underlying problem, not just symptoms
- **Minimal changes**: Make the smallest change that fixes the issue
- **Persistence**: Don't retry the same approach if it failed — investigate why
- **Know when to ask**: If stuck after 3 attempts, explain what you've tried and ask for help
- **Test thoroughly**: Ensure the fix works and doesn't introduce regressions

## Examples

### Example 1: Simple error with stack trace

```markdown
User: I'm getting this error:

Traceback (most recent call last):
  File "app.py", line 42, in process_request
    result = database.query(user_id)
AttributeError: 'NoneType' object has no attribute 'query'

Agent: I'll investigate this database connection error.

[Reads app.py around line 42]
[Checks where database is initialized]
[Finds database is not initialized before process_request]
[Adds database initialization check]
[Tests the fix]
```

### Example 2: Logic bug without error

```markdown
User: The user count is always showing 0 even though we have users

Agent: I'll investigate why the user count is incorrect.

[Reads the user counting code]
[Checks the database query]
[Finds the query is using COUNT(*) on a filtered table]
[Discovers the filter is excluding all users]
[Fixes the filter logic]
[Verifies the count is now correct]
```

### Example 3: Race condition

```markdown
User: Sometimes the file upload fails with "file not found"

Agent: I'll investigate the intermittent file upload failure.

[Reads the file upload handler]
[Checks for timing issues between upload and processing]
[Finds the processing happens before file is fully written]
[Adds file existence check or waits for write completion]
[Tests with multiple concurrent uploads]
```

## See also

- `diagnose` - Diagnosing agent run failures
- `test` - Writing tests to prevent regressions
- `review` - Reviewing code for potential bugs
