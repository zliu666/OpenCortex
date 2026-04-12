# OpenCortex Bundled Skills

This directory contains the bundled skills that ship with OpenCortex. Each skill is a reusable behavior pattern that the agent can invoke based on user requests.

## Directory Structure

```
skills/
├── commit/
│   └── SKILL.md
├── debug/
│   └── SKILL.md
├── diagnose/
│   └── SKILL.md
├── plan/
│   └── SKILL.md
├── review/
│   └── SKILL.md
├── simplify/
│   └── SKILL.md
├── test/
│   └── SKILL.md
└── README.md
```

## Available Skills

### commit
Create clean, well-structured git commits.
- **When**: User asks to commit changes, create a PR, or prepare code for review
- **Tools**: bash
- **Parameters**: amend, stage_all

### debug
Diagnose and fix bugs systematically.
- **When**: User reports a bug, error, or unexpected behavior
- **Tools**: bash, grep, read_file
- **Parameters**: max_attempts

### diagnose
Diagnose why an agent run failed, regressed, or produced unexpected output.
- **When**: User asks "why did this fail?" or similar questions about agent runs
- **Tools**: read_file, glob, bash
- **Parameters**: run_id, compare_run_id

### plan
Design an implementation plan before coding.
- **When**: User asks to plan, design, or architect a feature
- **Tools**: read_file, glob, lsp
- **Parameters**: detail_level

### review
Review code for bugs, security issues, and quality.
- **When**: User asks to review code, a PR, or a diff
- **Tools**: read_file, lsp, grep
- **Parameters**: focus, severity

### simplify
Refactor code to be simpler and more maintainable.
- **When**: User asks to simplify, clean up, or refactor code
- **Tools**: read_file, lsp, edit_file
- **Parameters**: aggressive

### test
Write and run tests for code.
- **When**: User asks to write tests, verify behavior, or improve coverage
- **Tools**: bash, read_file, write_file
- **Parameters**: test_framework, coverage_target

## Adding New Skills

To add a new bundled skill:

1. Create a new directory: `mkdir skills/your-skill`
2. Create a `SKILL.md` file following the template in `docs/SKILL_TEMPLATE.md`
3. Follow the development guide in `docs/SKILL_DEV_GUIDE.md`
4. Test the skill by loading it in the agent

## Skill Metadata Format

Each `SKILL.md` file uses YAML frontmatter with the following fields:

```yaml
---
name: skill-name
version: 1.0.0
description: One-line description
author: Author Name
trigger_keywords:
  - keyword1
  - keyword2
required_tools:
  - tool1
  - tool2
parameters:
  - name: param1
    type: string
    required: true
    description: Parameter description
---
```

## See Also

- [Skill Template](../../../docs/SKILL_TEMPLATE.md)
- [Skill Development Guide](../../../docs/SKILL_DEV_GUIDE.md)
- [Skill Loader](../loader.py)
- [Skill Registry](../registry.py)
