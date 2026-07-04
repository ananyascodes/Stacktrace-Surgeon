# StackTrace Surgeon: The Autonomous Debugger CLI

**Document version:** 1.0
**Status:** Draft for MVP scoping
**Owner:** [Product/Eng Lead]
**Last updated:** July 2026

---

## 1. Executive Summary

StackTrace Surgeon ("Surgeon") is a local, terminal-native CLI tool that wraps a developer's existing test command (e.g., `pytest`), intercepts failures, and autonomously attempts to fix the underlying code using an LLM-driven patch-and-verify loop. Instead of a developer copying a traceback into a chat UI, Surgeon keeps the entire debug loop inside the terminal: run tests → capture failure → gather context → generate patch → re-run tests → repeat or roll back.

The MVP is intentionally narrow: a single language (Python), a single test runner (`pytest`), a single-function patch strategy, and a hard retry limit. The goal is to prove the core value proposition — "the terminal turns green by itself" — before expanding language support, sandboxing, or CI/CD integration.

---

## 2. Problem Statement

### 2.1 The current developer workflow
When a test fails, a developer must:
1. Read a large, often noisy stack trace.
2. Manually locate the offending file and line.
3. Open the file in an editor, reason about the bug.
4. Optionally paste the error into a separate AI chat tool, breaking terminal flow.
5. Write and apply a fix by hand.
6. Re-run the test and repeat if still broken.

This context-switching (terminal → browser → editor → terminal) is slow and interrupts flow state, especially for small, mechanical failures: missing imports, off-by-one errors, outdated assertions, type mismatches, incorrect method signatures.

### 2.2 Why existing tools don't solve this
- **Copilot-style tools** are assistive, not autonomous — they suggest, but the developer still drives the debug loop.
- **Web-based AI chat** requires manual copy-paste of errors and code, and has no direct access to the local filesystem, git state, or process execution.
- **CI/CD-only auto-fixers** operate too late in the loop (post-push) and don't help the tight local edit-test cycle.

### 2.3 Opportunity
A tool that operates *inside* the terminal, with direct filesystem and git access, can close the loop autonomously for a meaningful subset of failures — without requiring the developer to leave their workflow. Even a 30% autonomous fix rate on mechanical failures represents significant time savings and is a defensible wedge into the developer-tools market.

---

## 3. Goals & Non-Goals

### 3.1 Goals (MVP)
- G1: Provide a drop-in CLI wrapper (`surgeon run "<command>"`) for any shell test command.
- G2: Automatically detect test failures via exit code and stderr/stdout capture.
- G3: Parse Python tracebacks to identify the exact failing file, function, and line.
- G4: Generate a targeted, single-function patch via LLM call.
- G5: Apply the patch, back up the original, and re-run the test command automatically.
- G6: Retry up to a configurable limit (default 3) with the new error fed back into the loop.
- G7: Roll back to the original file state if all retries fail.
- G8: Present a clear, human-readable diff of any successful fix.
- G9: Require zero configuration beyond an API key to get first value.

### 3.2 Non-Goals (explicitly out of scope for MVP)
- NG1: No support for languages other than Python at MVP (Node/Vitest/Jest is Phase 2).
- NG2: No cloud platform, dashboard, or hosted service — CLI only, runs locally.
- NG3: No sandboxed/containerized execution of arbitrary code in MVP (see Section 8, Risks — this is a conscious scope cut, not an oversight).
- NG4: No multi-file or cross-module refactors — patches are scoped to a single function/block.
- NG5: No automatic PR creation or CI/CD integration in MVP.
- NG6: No autonomous merging of code to `main`/`master` under any circumstances.
- NG7: No support for non-deterministic/flaky test detection or handling.

---

## 4. Target Users & Personas

**Primary persona: "Solo/Small-Team Python Developer"**
- Works largely alone or in a small team, has full local repo access and permissions.
- Runs `pytest` locally many times per day during active development.
- Frequently hits mechanical, low-complexity failures (imports, typos, assertion drift after refactors).
- Values terminal-native tools; resistant to context-switching into browser-based AI chat.
- Comfortable reviewing a git diff before trusting a change, but wants the *first draft* of the fix done for them.

**Secondary persona: "Backend Team Lead evaluating tools"**
- Evaluating whether autonomous fixing tools are safe enough to recommend to a team.
- Cares about: rollback safety, audit trail (diffs, backups), and cost per fix (LLM token spend).

---

## 5. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|---------------|------------|
| US-1 | Developer | run my normal test command through `surgeon run` | I don't need to learn a new tool syntax |
| US-2 | Developer | see nothing extra happen when tests pass | Surgeon never gets in my way on the happy path |
| US-3 | Developer | have Surgeon automatically locate the failing code | I don't have to manually dig through a traceback |
| US-4 | Developer | see a git-style diff of any change made | I can review exactly what was changed before trusting it |
| US-5 | Developer | have my original file restored if the fix attempts all fail | I never end up with broken code and no way back |
| US-6 | Developer | control how many retry attempts are made | I can bound my LLM spend and wait time |
| US-7 | Developer | see which LLM provider/model is being used and roughly what it costs | I can make an informed tooling decision |
| Team Lead | Evaluator | see an audit log of every patch attempt, applied or not | I can assess safety and trust before team rollout |

---

## 6. Product Scope: MVP Definition

### 6.1 In-scope MVP feature set
1. `surgeon run "<test command>"` — primary entry point.
2. `surgeon config` — set/view API key, default model, retry limit.
3. Traceback parser for standard Python `pytest` output (including nested tracebacks and `assert` failures).
4. File-context extractor: failing function body + N lines of surrounding context (configurable, default 20 lines above/below).
5. LLM patch-generation call with a strict, constrained system prompt (code-only output, single function scope).
6. Git-based backup/restore mechanism (local, does not require a remote).
7. Patch application (targeted function/block replacement, not whole-file overwrite).
8. Automatic re-run of the original test command after each patch attempt.
9. Retry loop with new-error-to-LLM feedback, bounded by `--max-retries` (default 3).
10. Rollback on exhausted retries.
11. Terminal output: real-time status ("Attempt 1/3: patch applied, re-running tests..."), final diff on success, final failure summary with rollback confirmation.
12. Basic run log (local file) capturing each attempt, prompt sent, patch applied, and result — for auditability.

### 6.2 Explicit MVP constraints
- Single test runner: `pytest` only.
- Single language: Python only.
- Patches are scoped to one function or code block at a time — Surgeon will not attempt cross-file fixes in MVP.
- No network sandboxing beyond what the user's own machine/environment already provides — see Section 8 for the required disclosure and mitigations.

---

## 7. System Architecture

### 7.1 High-level flow

```
                 +-------------------+
                 |  Developer runs   |
                 |  surgeon run ...  |
                 +---------+---------+
                            |
                            v
                 +-------------------+
                 | Exec Test Runner  |
                 | (capture stdout/  |
                 |  stderr, exit code)|
                 +---------+---------+
                            |
                 [exit code == 0] --> Exit cleanly, print pass message
                            |
                       [exit code != 0]
                            v
                 +-------------------+
                 | Context Collector |
                 | - parse traceback |
                 | - locate file/line|
                 | - extract function|
                 |   + surrounding   |
                 |   context lines   |
                 +---------+---------+
                            v
                 +-------------------+
                 | Git Backup        |
                 | (snapshot current |
                 |  file state)      |
                 +---------+---------+
                            v
                 +-------------------+
                 | LLM Patch Request |
                 | (error + code +   |
                 |  strict prompt)   |
                 +---------+---------+
                            v
                 +-------------------+
                 | Apply Patch       |
                 | (targeted replace)|
                 +---------+---------+
                            v
                 +-------------------+
                 | Re-run Test Runner|
                 +---------+---------+
                            |
              +-------------+--------------+
              |                            |
        [tests pass]                [tests fail, retries left]
              |                            |
              v                            v
     +----------------+          +-------------------+
     | Print diff,     |          | Feed new error     |
     | keep changes,   |          | back into LLM       |
     | write run log   |          | Patch Request loop  |
     +----------------+          +-------------------+
                                            |
                                  [retries exhausted]
                                            v
                                  +-------------------+
                                  | Rollback via git   |
                                  | backup, print       |
                                  | failure summary     |
                                  +-------------------+
```

### 7.2 Component breakdown

| Component | Responsibility | Notes |
|---|---|---|
| **CLI Entrypoint** | Parse `surgeon run`/`config` commands, flags | Python `argparse` or `click` |
| **Process Runner** | Spawn and manage the test command as a subprocess | `subprocess.run`, capture stdout/stderr, exit code |
| **Traceback Parser** | Extract file path, line number, exception type/message from pytest output | Regex + Python `traceback` module conventions; must handle pytest's formatted output specifically |
| **Context Collector** | Read source file, isolate the relevant function/block via AST parsing, grab N lines of surrounding context | Python `ast` module for function boundary detection (more reliable than naive line-counting) |
| **Backup Manager** | Create a local git commit or stash-equivalent snapshot before any mutation | Uses local git only; does not require a remote or push |
| **LLM Client** | Send structured prompt, receive patch, validate response format | LiteLLM or direct provider SDK; provider-agnostic where possible |
| **Patch Applier** | Replace the identified function/block in the file with the LLM's output | Must validate syntactic correctness (e.g., `ast.parse` the new file) before writing |
| **Retry Controller** | Track attempt count, feed new errors back into the loop, enforce `--max-retries` | Simple bounded loop with state object |
| **Rollback Manager** | Restore original file(s) from backup on failure | Git checkout of the pre-patch snapshot |
| **Reporter** | Print live status, final diff (via `git diff`), failure summaries | Terminal output formatting; also writes structured run log to disk |

### 7.3 Data flow / state object (per run)

```
RunState {
  original_command: str
  target_files_touched: list[str]
  attempts: list[Attempt]
  status: "pending" | "success" | "failed_rolled_back"
}

Attempt {
  attempt_number: int
  error_captured: str
  file_context_sent: str
  llm_prompt: str
  llm_response: str
  patch_applied: bool
  test_result_after_patch: "pass" | "fail"
}
```

---

## 8. Risks, Constraints & Mitigations

This section is treated as a first-class part of the PRD, not an appendix, because the two hardest problems (execution safety and patch reliability) determine whether the MVP is trustworthy enough to use.

| Risk | Severity | Mitigation for MVP |
|---|---|---|
| **Running LLM-influenced code changes directly on the developer's host machine, with no sandbox** | High | MVP explicitly does **not** execute arbitrary LLM-generated *commands* — only the developer's own, pre-existing test command is executed, and only pre-approved code *patches* (not shell commands) come from the LLM. Patch content is validated via `ast.parse` before being written to disk. A visible, mandatory disclosure is shown on first run: "Surgeon will modify local files and re-run your test command automatically. All changes are backed up and can be rolled back." Full containerized sandboxing (Docker-based) is explicitly deferred to Phase 2 (see Section 10). |
| **LLM produces a syntactically invalid or semantically wrong patch** | Medium | Patch is validated for syntax before writing. If re-run still fails, the loop retries with the new error; if retries are exhausted, full rollback occurs automatically — the developer is never left in a broken state. |
| **LLM patch technically passes the test but is a "bad" fix (e.g., deletes the assertion instead of fixing the bug)** | High | MVP mitigation is procedural, not technical: every successful patch is presented as a `git diff` for mandatory human review before the developer commits it. Surgeon never auto-commits or auto-pushes. This should be stated clearly in the CLI output and README. |
| **Infinite or excessive retry loops driving up LLM cost** | Medium | Hard-coded default `--max-retries=3`, user-configurable, with a visible per-attempt cost estimate if the model/provider exposes token usage. |
| **Traceback parsing fails on non-standard pytest configurations (custom plugins, parametrized tests, etc.)** | Medium | MVP scopes explicitly to standard pytest output; unsupported formats should fail gracefully with a clear "could not parse traceback" message rather than attempting a blind patch. |
| **Multi-function or multi-file bugs where a single-function patch cannot fix the issue** | Medium | Out of scope for MVP by design; Surgeon should detect when the same file/function fails repeatedly across retries with no progress and exit early with a clear message rather than looping uselessly. |
| **Sensitive code/credentials being sent to a third-party LLM API** | High | Only the specific failing function + limited context lines are sent, not the full repo. This should be clearly documented. A `.surgeonignore` mechanism (Phase 2) can let users exclude sensitive files/directories entirely. |

---

## 9. Success Metrics

| Metric | Definition | MVP Target |
|---|---|---|
| **Autonomous fix rate** | % of intercepted test failures resolved without human intervention, across a benchmark set of common Python failure types | ≥ 30% |
| **False success rate** | % of "successful" patches later identified as semantically incorrect despite passing tests (measured via manual review of a sample) | Track and report; no hard target for MVP, but must be visible to users via diff review |
| **Time-to-fix (successful cases)** | Wall-clock time from failure detection to passing re-run | < 60 seconds for single-function fixes on typical hardware |
| **Rollback integrity** | % of failed runs that leave the repo in exactly its original state | 100% (non-negotiable — this is a trust-critical guarantee) |
| **Setup time** | Time from install to first successful `surgeon run` | < 5 minutes |
| **Retry efficiency** | Average number of attempts needed for successful fixes | Track as a health metric for prompt quality over time |

---

## 10. MVP Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.10+ | Matches MVP's target language; simplifies AST-based context extraction |
| CLI framework | `click` or `argparse` | Lightweight, no heavy dependency |
| Process management | `subprocess` (stdlib) | Sufficient for spawning and capturing test runs |
| Code parsing | `ast` (stdlib) | Reliable function-boundary detection, patch validation |
| Version control integration | local `git` CLI via subprocess | Backup/restore without needing a remote; developers already have git |
| AI orchestration | LiteLLM or direct provider SDK | Avoids heavy agent frameworks; keeps the LLM call surface small and auditable |
| Model | Fast/cheap model tier (e.g., a Haiku-class or "mini" tier model) | Short, targeted code-correction tasks don't need frontier-level reasoning; keeps cost and latency low |
| Logging | Local JSON or plaintext run log | No external service dependency for MVP |
| Distribution | `pip install stacktrace-surgeon` (PyPI) | Lowest-friction install path for target persona |

---

## 11. CLI Design (MVP Command Surface)

```bash
# First-time setup
surgeon config --set-api-key <key> --provider <provider>

# Core usage — wraps any test command
surgeon run "pytest tests/test_login.py"

# Optional flags
surgeon run "pytest" --max-retries 5
surgeon run "pytest" --context-lines 30
surgeon run "pytest" --dry-run       # show what would be sent to the LLM, no patch applied
surgeon run "pytest" --no-rollback   # advanced: keep failed patch attempts for manual inspection

# Inspect the audit log of the last run
surgeon log --last

# Manually roll back the most recent Surgeon-applied patch
surgeon rollback --last
```

**Sample terminal output (success case):**
```
$ surgeon run "pytest tests/test_login.py"

Running: pytest tests/test_login.py
✗ Test failed: AssertionError in test_login_valid_credentials (line 47)

[Surgeon] Locating failing function: authenticate_user() in auth.py
[Surgeon] Backing up auth.py (git snapshot created)
[Surgeon] Generating patch (attempt 1/3)...
[Surgeon] Patch applied. Re-running tests...

✓ Test passed on attempt 1.

--- Diff (auth.py) ---
- if user.password == password:
+ if check_password_hash(user.password_hash, password):
------------------------

Review the diff above and commit when ready.
```

---

## 12. Out of Scope for MVP (Deferred to Later Phases)

These are documented here so they are not silently forgotten, but they are **not** part of the MVP deliverable:

- **Phase 2:** Node.js support (`vitest`/`jest`), Docker-based sandboxed execution, `.surgeonignore` for sensitive files, cost estimation UI, multi-function patch support.
- **Phase 3:** CI/CD integration (GitHub Actions), automatic PR creation with patch + explanation, team-shared audit dashboards, support for additional languages (Go, Java).
- **Phase 4:** Cloud/hosted version, enterprise permissions model, org-wide policy controls (e.g., "never auto-patch files in `/auth`").

---

## 13. Open Questions

1. Which LLM provider(s) should be supported at launch — single-provider lock-in for simplicity, or multi-provider via LiteLLM from day one?
2. Should `--dry-run` be the default first-run behavior (safer default) or opt-in?
3. What is the acceptable false-success rate before this is considered unsafe for team recommendation (relevant to the secondary persona)?
4. Should the run log be local-only in MVP, or is there early value in an opt-in anonymized telemetry stream to measure autonomous fix rate across users?
5. How should Surgeon behave in a monorepo with multiple `pytest.ini`/`conftest.py` scopes?

---

## 14. Appendix: Example Failure Categories Targeted by MVP

- Missing or incorrect imports
- Basic type mismatches (e.g., string vs int comparison)
- Outdated test assertions after minor refactors
- Off-by-one / boundary condition errors
- Incorrect function signatures after a rename
- `AttributeError`/`KeyError` from small logic errors
- Simple `None`-handling / null-check omissions

Categories explicitly **not** targeted by MVP: architectural bugs, race conditions, distributed-systems bugs, multi-file logic errors, and anything requiring product/business context the LLM cannot infer from code + traceback alone.
