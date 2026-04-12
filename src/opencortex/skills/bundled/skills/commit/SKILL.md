---
name: commit
version: 1.0.0
description: Create clean, well-structured git commits.
author: OpenCortex Team
trigger_keywords:
  - commit
  - "git commit"
  - "create commit"
  - "save changes"
  - "prepare for review"
required_tools:
  - bash
parameters:
  - name: amend
    type: boolean
    required: false
    default: false
    description: Whether to amend the previous commit (use with caution)
  - name: stage_all
    type: boolean
    required: false
    default: false
    description: Whether to stage all changes automatically
---

# Git Commit

Create clean, well-structured git commits following best practices for version control.

## When to use

Use this skill when the user:
- Asks to commit changes
- Mentions creating a PR or preparing code for review
- Wants to save work with a meaningful commit message
- Needs to organize changes into logical commits

## Workflow

1. **Check status**: Run `git status` to see what changed
2. **Review changes**: Run `git diff` to understand the nature and scope of changes
3. **Categorize changes**: Determine if it's a feature, fix, refactor, docs, test, etc.
4. **Draft commit message**:
   - First line: imperative mood, under 72 chars, describes the "why"
   - Body (if needed): explain context, trade-offs, or breaking changes
   - Include Co-Authored-By if pair programming
5. **Stage files**: Use specific `git add <file>` for targeted changes
6. **Create commit**: Run `git commit -m "<message>"`
7. **Verify**: Check that the commit was created successfully

## Rules

- **Message format**: Use imperative mood ("Add feature" not "Added feature")
- **Line length**: Keep first line under 72 characters
- **Content**: Explain "why" not "what" (code shows what)
- **Staging**: Prefer `git add <file>` over `git add -A` for precision
- **Safety**: Never stage credentials, .env files, or large binaries
- **Hooks**: Never use `--no-verify` unless explicitly requested
- **Amending**: Never amend published commits unless explicitly asked
- **Fixing hooks**: If a pre-commit hook fails, create a NEW commit (don't --amend)

## Examples

### Example 1: Simple feature commit

```markdown
User: Commit my authentication changes

Agent: I'll create a commit for your authentication changes.

[Checks git status - sees auth.py modified]
[Reviews git diff - sees JWT token validation added]
[Stages auth.py]
[Creates commit: "Add JWT token validation for authentication"]
```

### Example 2: Bug fix commit

```markdown
User: I fixed the null pointer crash in the user service

Agent: I'll commit that bug fix.

[Checks git status - sees user_service.py modified]
[Reviews git diff - sees null check added before user access]
[Stages user_service.py]
[Creates commit: "Fix null pointer crash when user data is missing

Added defensive null check before accessing user properties.
Prevents crashes when user service returns incomplete data."]
```

### Example 3: Multi-file refactor

```markdown
User: Commit the database refactoring

Agent: I'll commit the database refactoring changes.

[Checks git status - sees models.py, queries.py, tests/ changed]
[Reviews git diff - sees query interface standardized]
[Stages all related files]
[Creates commit: "Refactor database queries to use standardized interface

Migrated all queries to use new QueryBuilder interface.
This improves consistency and makes testing easier.

Breaking change: Query results now return dicts instead of tuples."]
```

## See also

- `review` - Code review practices
- `plan` - Planning multi-commit features
