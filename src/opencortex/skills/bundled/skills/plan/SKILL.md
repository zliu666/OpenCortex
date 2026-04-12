---
name: plan
version: 1.0.0
description: Design an implementation plan before coding.
author: OpenCortex Team
trigger_keywords:
  - plan
  - design
  - architect
  - "how should I"
  - "help me plan"
  - "implementation plan"
required_tools:
  - read_file
  - glob
  - lsp
parameters:
  - name: detail_level
    type: string
    required: false
    default: "standard"
    description: Level of detail: "brief", "standard", or "detailed"
---

# Plan

Design an implementation plan before coding to ensure a structured approach to development tasks.

## When to use

Use this skill when the user asks to:
- Plan, design, or architect a feature before implementing it
- "How should I implement X?"
- Create a roadmap for a complex task
- Design a solution architecture
- Plan a refactoring effort

## Workflow

1. **Understand the requirement**:
   - What problem does this solve?
   - What are the constraints (performance, security, compatibility)?
   - What's the expected outcome?
   - Who will use this and how?

2. **Explore the codebase**:
   - Find existing functions/utilities that can be reused
   - Identify patterns used elsewhere in the project
   - Locate files that will need modification
   - Check for relevant tests and documentation
   - Understand the current architecture

3. **Design the approach**:
   - Break the work into discrete, testable steps
   - Identify dependencies between steps
   - Consider edge cases and error handling
   - Plan for backward compatibility if needed
   - Think about testing strategy

4. **Present the plan**:
   - **Context**: Why this change is needed
   - **Overview**: High-level approach
   - **Steps**: Concrete steps with file paths and line numbers
   - **Risks**: Potential issues and how to mitigate them
   - **Testing**: How to verify the implementation
   - **Alternatives**: Other approaches considered (if any)

## Rules

- **Read before suggesting**: Never propose changes to code you haven't read
- **Prefer editing**: Edit existing files over creating new ones
- **Reuse patterns**: Follow existing patterns and utilities in the codebase
- **Be specific**: Include file paths and line numbers when referencing code
- **Match complexity**: Don't over-plan simple tasks
- **Think about tests**: How will this be tested?
- **Consider impact**: What might break? How to handle it?

## Examples

### Example 1: Simple feature plan

```markdown
User: I need to add user authentication

Agent: I'll design a plan for adding user authentication.

[Reads existing code to find user models]
[Checks for existing auth utilities]
[Explores middleware patterns]
[Creates plan:]

## Context
Need to secure API endpoints with user authentication.

## Approach
Use JWT tokens with middleware-based authentication.

## Steps
1. Add authentication middleware at src/api/middleware/auth.py
2. Create login endpoint at src/api/endpoints/auth.py
3. Update user model to store password hashes at src/models/user.py
4. Add JWT utility functions at src/utils/jwt.py
5. Protect existing endpoints by applying middleware

## Testing
- Write unit tests for middleware
- Test login flow with valid/invalid credentials
- Verify protected endpoints reject unauthenticated requests
```

### Example 2: Refactoring plan

```markdown
User: The database layer is messy, help me plan a refactor

Agent: I'll analyze the database layer and create a refactoring plan.

[Reads database code]
[Identifies patterns and issues]
[Creates refactoring plan:]

## Context
Database queries are scattered and inconsistent, making maintenance difficult.

## Approach
Introduce a repository pattern to centralize data access.

## Steps
1. Create base repository class at src/db/repository.py
2. Migrate user queries to UserRepository at src/db/repositories/user.py
3. Migrate product queries to ProductRepository at src/db/repositories/product.py
4. Update service layer to use repositories
5. Remove old query code from service layer

## Testing
- Run existing test suite to ensure no regressions
- Add integration tests for each repository
- Verify query performance is not degraded
```

### Example 3: Bug fix plan

```markdown
User: Plan how to fix the memory leak in the image processor

Agent: I'll investigate and plan a fix for the memory leak.

[Reads image processing code]
[Identifies potential leak sources]
[Creates fix plan:]

## Context
Image processor is not releasing memory after processing large batches.

## Root Cause
Images are being cached indefinitely without size limits.

## Solution
Implement LRU cache with size limits and explicit cleanup.

## Steps
1. Add LRU cache utility at src/utils/cache.py
2. Update image loader to use cached images at src/image/loader.py
3. Add explicit cleanup method in processor at src/image/processor.py
4. Call cleanup after batch processing completes
5. Add memory usage monitoring

## Testing
- Process large batch and verify memory is released
- Check cache eviction works correctly
- Monitor memory usage over time
```

## See also

- `commit` - Committing planned changes
- `review` - Reviewing implementation plans
- `simplify` - Refactoring during planning
