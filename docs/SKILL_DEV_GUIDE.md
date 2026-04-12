# Skill Development Guide

This guide explains how to create, test, and maintain skills for OpenCortex.

## What is a Skill?

A skill is a reusable behavior pattern that the agent can invoke based on user requests. Skills are defined in Markdown files with YAML frontmatter and loaded from:

- **Bundled skills**: `src/opencortex/skills/bundled/content/*.md`
- **User skills**: `~/.config/opencortex/skills/*/SKILL.md`
- **Plugin skills**: Defined in plugin manifests

## Skill System Architecture

```
┌─────────────────┐
│  User Request   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────┐
│ Skill Registry  │────►│ Skill Loader │
│                 │     └──────────────┘
│ - Bundled       │
│ - User          │
│ - Plugins       │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│ Skill Definition│
│ - name          │
│ - description   │
│ - content       │
│ - source        │
└─────────────────┘
```

## Creating a New Skill

### 1. Choose a Name

Use kebab-case for skill names:

- ✅ `git-commit`
- ✅ `code-review`
- ✅ `debug-error`
- ❌ `gitCommit` (camelCase)
- ❌ `git_commit` (snake_case)

### 2. Create the Directory Structure

For a **user skill**:

```bash
mkdir -p ~/.config/opencortex/skills/my-skill
```

For a **bundled skill**:

```bash
mkdir -p src/opencortex/skills/bundled/content
# Create file: src/opencortex/skills/bundled/content/my-skill.md
```

### 3. Write the Skill File

Use the template in `docs/SKILL_TEMPLATE.md` as a starting point.

#### Minimal Example

```yaml
---
name: my-skill
version: 1.0.0
description: Does one specific thing well.
---

# My Skill

Brief description of what this skill does.

## When to use

Use this when the user asks for X or needs Y.

## Workflow

1. Do this first
2. Then do that
3. Finally, validate results

## Rules

- Always do X before Y
- Never assume Z without verifying
```

#### Complete Example

```yaml
---
name: git-commit
version: 1.0.0
description: Create clean, well-structured git commits.
author: OpenCortex Team
trigger_keywords:
  - commit
  - "git commit"
  - "create commit"
required_tools:
  - bash
parameters:
  - name: include_all
    type: boolean
    required: false
    default: false
    description: Whether to stage all changes
---

# Git Commit

Create clean, well-structured git commits following best practices.

## When to use

Use when the user:
- Asks to commit changes
- Mentions creating a PR or preparing code for review
- Wants to save work with a meaningful message

## Workflow

1. **Check status**: Run `git status` to see what changed
2. **Review changes**: Run `git diff` to understand the changes
3. **Categorize**: Determine if it's a feature, fix, refactor, etc.
4. **Stage files**: Use `git add <file>` for specific files
5. **Write message**: Create a clear, imperative message
6. **Create commit**: Run `git commit -m "<message>"`

## Rules

- Use imperative mood ("Add feature" not "Added feature")
- Keep first line under 72 characters
- Include body for complex changes
- Never stage credentials, .env, or large binaries
- Use `git add <file>` instead of `git add -A` when possible

## Examples

### Example 1: Simple commit

```markdown
User: Commit my changes

Agent: I'll create a commit for your changes.

[Checks git status and diff]
[Stages relevant files]
[Creates commit with clear message]
```
```

## Skill Frontmatter Reference

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique skill identifier (kebab-case) |
| `version` | string | Semantic version (e.g., 1.0.0) |
| `description` | string | One-line description for the skill registry |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `author` | string | Author name and email |
| `trigger_keywords` | list[string] | Keywords that suggest using this skill |
| `required_tools` | list[string] | Tools this skill requires |
| `parameters` | list[object] | Configuration parameters |

## Skill Content Sections

### When to use

Describe:
- What problem the skill solves
- When it should be invoked
- Any prerequisites or context

### Workflow

Numbered step-by-step instructions:
1. **Step name**: Brief description
2. **Step name**: Brief description
3. **Step name**: Brief description

Each step should be:
- Actionable (use verbs)
- Specific (avoid vague instructions)
- Ordered (logical sequence)

### Rules

Constraints and guidelines:
- **Rule one**: Specific constraint
- **Rule two**: Specific constraint

Rules should be:
- Clear and unambiguous
- Testable (can verify if followed)
- Necessary (avoid stating the obvious)

### Examples

Show concrete examples of:
- User input that triggers the skill
- Expected agent behavior
- Edge cases and how to handle them

## Testing Skills

### Manual Testing

1. **Load the skill**:
   ```python
   from opencortex.skills.loader import load_skill_registry
   
   registry = load_skill_registry()
   skill = registry.get("my-skill")
   print(skill.content)
   ```

2. **Test the workflow**:
   - Invoke the skill via the agent
   - Verify each step is followed
   - Check edge cases

3. **Validate parsing**:
   ```python
   from opencortex.skills.bundled import _parse_frontmatter
   
   content = Path("my-skill.md").read_text()
   name, description = _parse_frontmatter("my-skill", content)
   print(f"Name: {name}, Description: {description}")
   ```

### Integration Testing

Test skills in context:
- With different tool configurations
- Alongside other skills
- With various user inputs

## Skill Versioning

Use semantic versioning:

- **1.0.0**: Initial stable version
- **1.1.0**: Add new functionality (backward compatible)
- **1.0.1**: Bug fix (backward compatible)
- **2.0.0**: Breaking change

Update version when:
- Changing workflow steps
- Modifying rules
- Adding/removing required tools
- Changing parameter schema

## Common Patterns

### Conditional Workflow

```yaml
## Workflow

1. **Check prerequisites**: Verify X is available
2. **Branch based on context**:
   - If condition A: Do this
   - If condition B: Do that
   - Otherwise: Use default approach
3. **Validate**: Ensure result meets criteria
```

### Error Handling

```yaml
## Rules

- If a tool fails, try X before giving up
- Log errors with context (file, line, error message)
- Never suppress errors without good reason
```

### Multi-Step Coordination

```yaml
## Workflow

1. **Phase 1**: Prepare and validate
2. **Phase 2**: Execute main logic
3. **Phase 3**: Cleanup and verify
```

## Troubleshooting

### Skill Not Loading

**Problem**: Skill doesn't appear in registry

**Solutions**:
- Check file is named `SKILL.md` (user skills) or `*.md` (bundled)
- Verify YAML frontmatter is valid (use `---` delimiters)
- Check for syntax errors in YAML
- Ensure directory structure is correct

### Description Not Parsed

**Problem**: Description shows as default value

**Solutions**:
- Verify `description:` field in frontmatter
- Check YAML indentation (use spaces, not tabs)
- Ensure description is quoted if contains special characters

### Workflow Not Followed

**Problem**: Agent doesn't follow the workflow

**Solutions**:
- Make steps more specific and actionable
- Add rules to enforce critical steps
- Include examples of correct behavior
- Check for conflicting instructions

## Best Practices

1. **Keep skills focused**: One skill = one clear purpose
2. **Be explicit**: Clear instructions > vague guidelines
3. **Version carefully**: Update version when behavior changes
4. **Document well**: Examples help users understand usage
5. **Test thoroughly**: Verify skill works in various scenarios
6. **Iterate**: Improve skills based on real usage

## See Also

- [Skill Template](SKILL_TEMPLATE.md) - Template for new skills
- [Skill Loader](../src/opencortex/skills/loader.py) - How skills are loaded
- [Skill Registry](../src/opencortex/skills/registry.py) - How skills are stored
- [Skill Types](../src/opencortex/skills/types.py) - Skill data structures
