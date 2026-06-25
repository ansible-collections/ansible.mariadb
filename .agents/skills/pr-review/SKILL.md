---
name: pr-review
description: Reviews pull requests and code changes in the ansible.mysql Ansible collection against project standards and the Ansible Collection Review Checklist. Use when asked to review a PR, patch, diff, or set of code changes. Do not use for GitHub Issues or general Q&A.
---

# Skill: pr-reviewer

## Purpose

Review pull requests and code changes in the `ansible.mysql` Ansible collection.

## When to Invoke

TRIGGER when:
- A user asks to review a PR, patch, diff, or set of code changes
- Validating changes against project standards before merge

DO NOT TRIGGER when:
- Reviewing GitHub Issues (not PRs/code changes)
- General Q&A, documentation lookup, or debugging unrelated to a changeset

## Inputs

- `target` (optional): PR number, branch name, commit hash, or file path.
  - If omitted, review the current working changes via `git diff HEAD`.

## Approach

### Step 1 — Gather the changeset

Obtain the diff using the appropriate method:
- PR number provided → read changed files and their diffs
- Branch or commit reference → run `git diff <base>..<ref>` or `git show <ref>`
- File path provided → read the file and review it in full
- No target → run `git diff HEAD` to capture all current changes

Read every changed file completely before forming any judgment.

### Step 2 — Run all review checks in parallel

Execute all checks in the checklist below concurrently. Collect findings per category. For categories not listed below, apply the rules from the corresponding sections in `AGENTS.md`.

### Step 3 — Report

Produce the structured report described in the **Output Format** section.

---

## Review Checklist

Architecture and Type Conversion categories are fully covered by `AGENTS.md` — apply those sections directly.

### Collection Metadata

- `galaxy.yml`: `version`, `description`, `tags`, `dependencies` are accurate and up to date.
- `meta/runtime.yml`: `requires_ansible` minimum version reflects any new Ansible features used.
- New Python dependencies added to both `requirements.txt` and `meta/ee-requirements.txt`.

### Module Documentation

- Every public parameter has a `description`, `type`, and `required` or `default`.
- The `EXAMPLES` block is present, valid YAML, and covers the primary use cases.
- The `RETURN` block accurately describes every key returned by the module.
- Module short description (`short_description`) is concise and accurate.
- `author` field is present and correctly formatted.

### Naming and Style

- Module file names follow the `mysql_<noun>` pattern.
- No abbreviations that reduce readability.

### Idempotency

- `result['changed']` is `False` when no real change is made.
- Repeated runs with the same arguments produce the same outcome with no spurious changes.

### Sensitive Data

- All sensitive parameters (passwords, tokens, secrets) set `no_log=True`.
- No sensitive data appears in `executed_statements` or module return values in plaintext.

### Error Handling

- All errors call `module.fail_json(msg=...)` with a descriptive, actionable message — no bare `raise` or `sys.exit()`.
- `mysql_info` and similar read-only modules handle privilege errors gracefully (return partial results, not a failure).
- Connection and query utilities from `module_utils/mysql.py` are used for database interactions.

### Testing

- Sanity checks pass: `ansible-test sanity <changed_file> --docker -v`
- Unit tests are present for any new or modified logic in `module_utils` or non-trivial module functions. Located under `tests/unit/plugins/`.
- Integration tests are required for any non-refactoring, non-documentation code change. Located under `tests/integration/targets/<module_name>/`.
- Integration test pattern is followed:
  1. Call module → `register: result`
  2. `ansible.builtin.assert` on `result`
  3. Verify DB state using `ansible.mysql.mysql_query` → `register: result` → `ansible.builtin.assert`
- Each integration test target has `tests/integration/targets/<name>/meta/main.yml` declaring `setup_controller` as a dependency.
- Tests cover both the happy path and idempotency (running the same task twice).
- Tests cover the `state: absent` path where applicable.

### Backwards Compatibility

- No existing parameters are removed or renamed without a deprecation notice.
- No existing return values are removed or their types changed.
- Breaking changes are flagged explicitly and justified.
- Deprecations use the Ansible deprecation mechanism (`module.deprecate()`).

### Changelog Fragment

- Fragment content is concise, written in past tense, and references the module name.
- The changelog fragment must not be present when a pull request only contains a new Ansible module and related changes.

### Code Quality

- No dead code, commented-out blocks, or debug statements left in.
- No feature flags or backwards-compatibility shims for hypothetical future use.
- No premature abstractions (helpers/utilities created for a single use case).
- No security vulnerabilities: no shell injection, no unvalidated external input passed to queries, no hardcoded credentials.

### Additional checks when reviewing a new Ansible module

This section is also partly applicable to module interface changes such as new arguments and return values.

Check thoroughly that:
- All facts stated in the DOCUMENTATION block and in the PR description if provided are correct. Use the official documentation of the entity the module automates.
- The module interface (arguments) is clear and follows the [module format and documentation guide](https://docs.ansible.com/projects/ansible/devel/dev_guide/developing_modules_documenting.html).
- Check mode support must be full, unless there are technical obstacles on the underlying technology side we are automating that are impossible to overcome.
- Check mode support must be explicitly stated in the DOCUMENTATION block under the attributes field.
- All the options from the documentation block and all their values are covered with CI
  - All corresponding tasks run in check mode; check if there's a task after each such task that checks the actual database state.
  - All corresponding tasks run in real mode (without check_mode: true); check if there's a task after each such task that checks the actual database state.
  - The same task runs again after each task to check idempotency: it must report nothing changed.
- All the examples from the EXAMPLES block are covered with integration tests.
- All the return values from the RETURN block are covered with integration tests.
- All functions do one logical action, are concise, and are covered with unit tests.
- The version_added field for the modules is set in the DOCUMENTATION block.
  - Individual arguments as well as the returned values must have version_added set only when they are added to an existing module.
- The DOCUMENTATION, EXAMPLE, and RETURNS sections follow the [style guide](https://docs.ansible.com/projects/ansible/devel/dev_guide/style_guide/index.html).
- The changelog fragment must not be present for the new Ansible module: a proper entry will be generated automatically by the antsibull-changelog tool during releasing based on the version_added field.

---

## Output Format

Structure the review as follows:

```
## PR Review: <target or "Current Changes">

### Summary
<One-paragraph overall assessment: scope of the change, general quality, primary concerns.>

### Findings

#### Blockers (must fix before merge)
- [CATEGORY] <File>:<line> — <description of the issue>

#### Warnings (should fix, not strictly blocking)
- [CATEGORY] <File>:<line> — <description of the issue>

#### Suggestions (optional improvements)
- [CATEGORY] <File>:<line> — <description of the issue>

### Checklist Status
| Category | Status | Notes |
|---|---|---|
| Collection Metadata | PASS / FAIL / N/A | ... |
| Module Documentation | PASS / FAIL / N/A | ... |
| Naming and Style | PASS / FAIL / N/A | ... |
| Architecture | PASS / FAIL / N/A | ... |
| Idempotency | PASS / FAIL / N/A | ... |
| check_mode | PASS / FAIL / N/A | ... |
| Sensitive Data | PASS / FAIL / N/A | ... |
| Error Handling | PASS / FAIL / N/A | ... |
| Type Conversion | PASS / FAIL / N/A | ... |
| Testing | PASS / FAIL / N/A | ... |
| Backwards Compatibility | PASS / FAIL / N/A | ... |
| Changelog Fragment | PASS / FAIL / N/A | ... |
| Code Quality | PASS / FAIL / N/A | ... |

### Verdict
APPROVE / REQUEST CHANGES / COMMENT

<One sentence justifying the verdict.>
```

Use `N/A` for categories that do not apply to the changeset (e.g., type conversion for a docs-only PR). Be specific: always reference the file and line number when citing a finding.

When reviewing a new module, save the report to a new .md file.
