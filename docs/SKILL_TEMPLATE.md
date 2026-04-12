# Skill Template

Use this template to create new skills for OpenCortex. Skills are reusable behaviors that the agent can invoke based on user requests.

## File Structure

```
skills/
└── my-skill/
    └── SKILL.md
```

The skill file must be named `SKILL.md` and placed in a directory named after the skill.

---

```yaml
---
name: my-skill
version: 1.0.0
description: A concise one-line description of what this skill does.
author: Your Name <email@example.com>
trigger_keywords:
  - keyword1
  - keyword2
  - "phrase with spaces"
required_tools:
  - tool_name_1
  - tool_name_2
parameters:
  - name: param1
    type: string
    required: true
    description: Description of what this parameter controls
  - name: param2
    type: integer
    required: false
    default: 10
    description: Optional parameter with default value
---

# Skill Title (Human-Readable)

A brief human-readable description of what this skill does and when to use it.

## When to use

Describe the scenarios or user requests that should trigger this skill. Be specific about:
- What problem it solves
- When it's appropriate to invoke
- Any prerequisites or context needed

## Workflow

Step-by-step instructions for the agent to follow when using this skill:

1. **Step one**: Brief description of what to do
2. **Step two**: Brief description of what to do
3. **Step three**: Brief description of what to do

Each step should be actionable and specific.

## Rules

Constraints and guidelines the agent must follow:

- **Rule one**: Specific constraint or guideline
- **Rule two**: Specific constraint or guideline  
- **Rule three**: Specific constraint or guideline

## Examples

### Example 1: Simple scenario

```markdown
User: [example user input]

Agent: [expected agent response using this skill]
```

### Example 2: Complex scenario

```markdown
User: [example user input]

Agent: [expected agent response using this skill]
```

## See also

- Related skill 1
- Related skill 2
- Relevant documentation
```

---

## Frontmatter Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique skill identifier (kebab-case) |
| `version` | string | Yes | Semantic version (e.g., 1.0.0) |
| `description` | string | Yes | One-line description for the skill registry |
| `author` | string | No | Author name and email |
| `trigger_keywords` | list[string] | No | Keywords that suggest using this skill |
| `required_tools` | list[string] | No | Tools this skill requires to function |
| `parameters` | list[object] | No | Configuration parameters for the skill |

### Parameter Schema

Each parameter in `parameters` must have:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Parameter identifier (snake_case) |
| `type` | string | Yes | Data type (string, integer, boolean, list) |
| `required` | boolean | Yes | Whether the parameter is required |
| `description` | string | Yes | What the parameter controls |
| `default` | any | No | Default value if not required |

## Best Practices

1. **Keep skills focused**: Each skill should do one thing well
2. **Be explicit**: Clear instructions are better than vague guidelines
3. **Include examples**: Show, don't just tell
4. **Version your skills**: Update version when changing behavior
5. **Document dependencies**: List required tools and parameters

## Testing Your Skill

After creating a skill, test it by:

1. Restarting the agent to reload the skill registry
2. Invoking the skill via the `skill` tool: `skill(name="your-skill-name")`
3. Verifying the agent follows the workflow correctly
4. Checking edge cases and error scenarios
