---
name: diagnose
version: 1.0.0
description: Diagnose why an agent run failed, regressed, or produced unexpected output.
author: OpenCortex Team
trigger_keywords:
  - diagnose
  - "why did this fail"
  - "what went wrong"
  - "investigate failure"
  - "analyze run"
  - "unexpected output"
  - regression
required_tools:
  - read_file
  - glob
  - bash
parameters:
  - name: run_id
    type: string
    required: false
    description: Specific run ID to diagnose (uses latest if not specified)
  - name: compare_run_id
    type: string
    required: false
    description: Run ID to compare against (for regression analysis)
---

# Diagnose

Diagnose why an agent run failed, regressed, or produced unexpected output — using structured evidence instead of intuition.

## When to use

Use this skill when the user asks:
- "Why did this run fail?"
- "What changed between this run and the last one?"
- "The output looks wrong — what happened?"
- "Why is this run worse than before?"
- "Investigate this failed run"

## Workflow

1. **Locate the run artifacts**:
   - Check `artifacts/runs/<run_id>/` or the latest run directory
   - Look for key files:
     - `manifest.json` — run metadata, task type, input hash, timestamps
     - `execution_trace.jsonl` — the full tool-call chain, one event per line
     - `verification_report.json` — what was verified and whether it passed
     - `failure_signature.json` — which stage failed and why (if present)

2. **Read the failure signature first**:
   - If it exists, it already localizes the failure
   - Identifies the specific stage (routing, execution, verification, governance)
   - Provides error details and context

3. **Trace the execution chain**:
   - Walk `execution_trace.jsonl` forward chronologically
   - Find where output diverged from expectation
   - Note tool calls, parameters, and results
   - Look for errors, timeouts, or unexpected behavior

4. **Compare with a passing run**:
   - If a previous run succeeded, diff the two manifests
   - Compare execution traces to identify what changed
   - Look for differences in:
     - Tool calls or parameters
     - Intermediate results
     - Timing or performance
     - External dependencies

5. **Identify the failure layer**:
   - **Routing**: Wrong task type or profile selected
   - **Execution**: Tool call error, permission block, or unexpected result
   - **Verification**: Output produced but did not match expected artifact
   - **Governance**: Run was halted by a safety or boundary check

6. **Report with evidence**:
   - Cite specific file paths, line numbers in the trace
   - Reference field values from the manifest
   - Quote relevant log entries
   - Never summarize without pointing to the source

## Rules

- **Evidence before intuition**: Always read the trace before forming a hypothesis
- **Localize before explaining**: Identify which stage failed before describing why
- **Compare, don't guess**: If a previous run succeeded, diff it — don't speculate
- **Be specific**: Reference exact files, lines, and field values
- **No artifacts = no diagnosis**: If no artifacts exist, say so clearly and ask the user to re-run with archive mode enabled
- **Structured reporting**: Organize findings by stage and evidence type

## Examples

### Example 1: Simple failure with signature

```markdown
User: Why did run abc123 fail?

Agent: I'll investigate run abc123.

[Locates artifacts/runs/abc123/failure_signature.json]
[Reads failure: "execution" stage, "tool_call_error" in bash command]
[Checks execution_trace.jsonl for the tool call]
[Finds the command had a syntax error]
[Reports: "Run failed at execution stage due to bash syntax error on line 42"]
```

### Example 2: Regression investigation

```markdown
User: Run xyz789 produced worse output than the previous run

Agent: I'll compare run xyz789 with the previous run.

[Locates both run directories]
[Reads both manifest.json files]
[Compares input hashes - same input]
[Diffs execution traces]
[Finds the tool call parameters changed]
[Identifies which parameter caused the regression]
[Reports: "Regression caused by temperature parameter change from 0.7 to 0.9"]
```

### Example 3: No artifacts available

```markdown
User: Diagnose why my run failed

Agent: I need the run artifacts to diagnose the failure.

[Checks for artifacts directory]
[No artifacts found for the specified run]
[Explains: "No run artifacts found. Please re-run with archive mode enabled to capture execution traces."]
```

## See also

- `debug` - Debugging code issues
- `review` - Reviewing execution logs
- `test` - Writing tests to prevent future failures
