---
name: simplify
version: 1.0.0
description: Refactor code to be simpler and more maintainable.
author: OpenCortex Team
trigger_keywords:
  - simplify
  - refactor
  - "clean up"
  - "too complex"
  - "make this simpler"
  - "reduce complexity"
required_tools:
  - read_file
  - lsp
  - edit_file
parameters:
  - name: aggressive
    type: boolean
    required: false
    default: false
    description: Whether to apply more aggressive simplification
---

# Simplify

Refactor code to be simpler and more maintainable while preserving behavior.

## When to use

Use this skill when the user asks to:
- Simplify complex code
- Clean up or refactor code
- Reduce complexity or improve maintainability
- "This is too complicated, can you simplify it?"
- Make code more readable

## Workflow

1. **Read the target code completely**:
   - Understand what the code does
   - Identify the inputs and outputs
   - Note any side effects
   - Understand the context and dependencies

2. **Identify complexity sources**:
   - **Unnecessary abstractions**: Layers of indirection that add no value
   - **Duplicated logic**: Similar code repeated multiple times
   - **Over-engineered patterns**: Factories, builders, strategies for simple cases
   - **Dead code paths**: Unused variables, unreachable code, commented-out code
   - **Confusing names**: Variables or functions with unclear names
   - **Long functions**: Functions that do too many things
   - **Nested conditionals**: Deep nesting that's hard to follow
   - **Magic numbers**: Unnamed constants

3. **Propose simplification changes**:
   - Remove unnecessary abstraction layers
   - Consolidate duplicated logic
   - Use simpler data structures or algorithms
   - Delete dead code entirely
   - Improve naming for clarity
   - Break up long functions
   - Flatten nested conditionals
   - Extract magic numbers to named constants
   - Reduce line count while preserving behavior

4. **Verify the refactored code**:
   - Ensure existing tests still pass
   - Check that behavior is preserved
   - Verify no new bugs were introduced
   - Confirm code is more readable

## Rules

- **Don't change behavior**: Simplification should be behavior-preserving
- **Don't add features**: Only simplify, don't add new functionality
- **Prefer deleting**: Remove code rather than refactoring it when possible
- **Three-line rule**: Three similar lines are better than a premature abstraction
- **Remove shims**: Delete backwards-compatibility code for removed features
- **No comments**: Don't add comments to explain simple code — rewrite the code instead
- **Preserve tests**: Ensure all existing tests still pass
- **Be careful**: Simplification can introduce bugs if not done carefully

## Examples

### Example 1: Removing unnecessary abstraction

```markdown
User: This factory pattern seems overkill for creating user objects

Agent: I'll simplify the user creation code.

[Reads the factory code]
[Identifies the abstraction layers]
[Simplifies to direct instantiation:]

Before:
```python
class UserFactory:
    def create_user(self, name, email):
        return User(name=name, email=email)

factory = UserFactory()
user = factory.create_user("Alice", "alice@example.com")
```

After:
```python
user = User(name="Alice", email="alice@example.com")
```
```

### Example 2: Consolidating duplicated logic

```markdown
User: I have duplicate validation code in multiple places

Agent: I'll consolidate the duplicated validation logic.

[Reads the validation code]
[Identifies the duplication]
[Creates a single validation function:]

Before:
```python
def validate_email(email):
    if not email or '@' not in email:
        raise ValueError("Invalid email")

def validate_user_input(email, name):
    if not email or '@' not in email:
        raise ValueError("Invalid email")
    if not name:
        raise ValueError("Invalid name")
```

After:
```python
def validate_email(email):
    if not email or '@' not in email:
        raise ValueError("Invalid email")

def validate_user_input(email, name):
    validate_email(email)
    if not name:
        raise ValueError("Invalid name")
```
```

### Example 3: Flattening nested conditionals

```markdown
User: This nested if-else is hard to follow

Agent: I'll flatten the nested conditionals for better readability.

[Reads the nested code]
[Identifies the logic flow]
[Flattens the structure:]

Before:
```python
def process_user(user):
    if user:
        if user.is_active:
            if user.has_permission:
                return "Access granted"
            else:
                return "No permission"
        else:
            return "User inactive"
    else:
        return "No user"
```

After:
```python
def process_user(user):
    if not user:
        return "No user"
    if not user.is_active:
        return "User inactive"
    if not user.has_permission:
        return "No permission"
    return "Access granted"
```
```

### Example 4: Removing dead code

```markdown
User: There's a lot of old code that's not used anymore

Agent: I'll identify and remove the dead code.

[Reads the codebase]
[Identifies unused functions and variables]
[Checks if they're called anywhere]
[Removes the dead code:]
```

## Common Simplification Patterns

### Remove Indirection
- Replace wrapper functions that only call one other function
- Inline trivial helper functions
- Remove unnecessary interfaces

### Consolidate Duplicates
- Extract common logic to shared functions
- Use loops instead of repeated similar statements
- Create utility functions for repeated patterns

### Improve Naming
- Rename variables to be self-documenting
- Use boolean `is_` prefix for clarity
- Avoid generic names like `data`, `info`, `handle`

### Reduce Nesting
- Use guard clauses to return early
- Extract nested logic to separate functions
- Use conditional expressions for simple cases

### Delete Dead Code
- Remove unused imports
- Delete commented-out code
- Remove unused variables and functions
- Clean up unreachable code

## See also

- `review` - Reviewing code for complexity issues
- `debug` - Debugging issues introduced during simplification
- `test` - Testing simplified code
