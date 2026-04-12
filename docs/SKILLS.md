# OpenCortex Skills System

The OpenCortex skills system provides reusable behavior patterns that the agent can invoke based on user requests. Skills are defined in Markdown files with YAML frontmatter and loaded from multiple sources.

## Overview

Skills are declarative descriptions of how the agent should handle specific types of tasks. Each skill includes:

- **Metadata**: Name, version, description, author
- **Trigger keywords**: Keywords that suggest using this skill
- **Required tools**: Tools needed to execute the skill
- **Parameters**: Configuration options for the skill
- **Workflow**: Step-by-step instructions for the agent
- **Rules**: Constraints and guidelines to follow
- **Examples**: Concrete examples of skill usage

## Skill Sources

Skills are loaded from three sources:

### 1. Bundled Skills
Located in `src/opencortex/skills/bundled/skills/*/SKILL.md`

These skills ship with OpenCortex and include:
- `commit` - Create clean git commits
- `debug` - Diagnose and fix bugs
- `diagnose` - Investigate agent run failures
- `plan` - Design implementation plans
- `review` - Review code for issues
- `simplify` - Refactor code for simplicity
- `test` - Write and run tests

### 2. User Skills
Located in `~/.config/opencortex/skills/*/SKILL.md`

Users can create custom skills for their specific workflows.

### 3. Plugin Skills
Defined in plugin manifests

Plugins can provide skills that extend OpenCortex's capabilities.

## Skill File Format

Skills use YAML frontmatter with a Markdown body:

```yaml
---
name: my-skill
version: 1.0.0
description: A concise one-line description
author: Your Name
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
    description: What this parameter controls
---

# Skill Title

Human-readable description of the skill.

## When to use

Describe scenarios that trigger this skill.

## Workflow

1. Step one
2. Step two
3. Step three

## Rules

- Rule one
- Rule two

## Examples

### Example 1

```markdown
User: [input]
Agent: [response]
```
```

## Creating Skills

### Quick Start

1. Use the template in `docs/SKILL_TEMPLATE.md`
2. Follow the development guide in `docs/SKILL_DEV_GUIDE.md`
3. Place your skill in the appropriate directory
4. Test by invoking: `skill(name="your-skill")`

### Best Practices

- **Keep skills focused**: One skill = one clear purpose
- **Be explicit**: Clear instructions > vague guidelines
- **Include examples**: Show, don't just tell
- **Version carefully**: Update version when behavior changes
- **Test thoroughly**: Verify skills work in various scenarios

## Skill Registry

The skill registry manages all loaded skills and provides:

- **Registration**: Add new skills to the registry
- **Lookup**: Retrieve skills by name
- **Listing**: Get all skills sorted by name

```python
from opencortex.skills.loader import load_skill_registry

registry = load_skill_registry()
skill = registry.get("commit")
print(skill.content)
```

## Documentation

- [Skill Template](SKILL_TEMPLATE.md) - Template for new skills
- [Skill Development Guide](SKILL_DEV_GUIDE.md) - How to create and maintain skills
- [Bundled Skills README](../src/opencortex/skills/bundled/skills/README.md) - Available bundled skills

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Skill System                        │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌─────────────┐      ┌──────────────┐                  │
│  │   Bundled   │      │     User     │                  │
│  │   Skills    │      │   Skills     │                  │
│  └──────┬──────┘      └──────┬───────┘                  │
│         │                    │                           │
│         └────────┬───────────┘                           │
│                  │                                       │
│                  ▼                                       │
│         ┌────────────────┐                              │
│         │  Skill Loader  │                              │
│         └────────┬───────┘                              │
│                  │                                       │
│                  ▼                                       │
│         ┌────────────────┐                              │
│         │ Skill Registry │                              │
│         │                │                              │
│         │ - get(name)    │                              │
│         │ - list_all()   │                              │
│         └────────────────┘                              │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

## Contributing

To contribute a new bundled skill:

1. Check existing skills to avoid duplication
2. Follow the skill template and development guide
3. Add comprehensive examples
4. Test the skill thoroughly
5. Submit a PR with your skill

## License

Bundled skills are part of OpenCortex and follow the same license.
