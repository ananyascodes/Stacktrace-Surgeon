# StackTrace Surgeon

> **An Autonomous AI-Powered Debugging CLI for Python Developers**

StackTrace Surgeon is a command-line tool that automatically analyzes Python runtime failures, identifies the root cause, and attempts to repair deterministic errors using an LLM. For ambiguous or non-deterministic issues, it provides concise human-readable diagnostics instead of making unsafe assumptions.

The goal is to reduce debugging time by transforming AI from a passive coding assistant into an autonomous debugging agent.

---

# Features

- Automatic traceback parsing
- Context-aware AI patch generation
- Intelligent retry loop
- Automatic backup & rollback
- Human-readable diagnosis mode
- Static error analysis
- Safe patch validation using Python AST
- Supports `.env` API key loading
- Clean CLI interface

---

# Current Scope

Current MVP supports **Python** projects only.

Supported deterministic errors include:

- ZeroDivisionError
- SyntaxError
- ImportError
- ModuleNotFoundError
- NameError
- TypeError
- IndexError
- KeyError
- AttributeError

Ambiguous problems are diagnosed instead of being guessed, including:

- Undefined functions
- Missing environment variables
- Missing configuration files
- Missing external APIs
- Missing resources
- Missing business logic

---

# Project Structure

```
StackTrace-Surgeon/
│
├── cli.py
├── orchestrator.py
├── execution_engine.py
├── trace_parser.py
├── patch_engine.py
├── setup.py
├── readme.md
├── .gitignore
│
├── qa_tests/
│
└── test_sandbox/
```

---

# Installation

Clone the repository.

```bash
git clone https://github.com/ananyascodes/Stacktrace-Surgeon.git
```

Move into the project.

```bash
cd Stacktrace-Surgeon
```

Install the project.

```bash
pip install -e .
```

This registers the global command:

```bash
surgeon
```

---

# API Key Setup

Create a file named:

```
.env
```

Add one of the following:

```text
GEMINI_API_KEY=your_api_key
```

or

```text
OPENAI_API_KEY=your_api_key
```

or

```text
ANTHROPIC_API_KEY=your_api_key
```

The project automatically loads the `.env` file using `python-dotenv`.

---

# CLI Commands

## Auto Repair

Attempts to repair deterministic errors.

```bash
surgeon run "python app.py"
```

Example:

```bash
surgeon run "python calculator.py"
```

---

## Analyze

Displays the exact failure location without modifying code.

```bash
surgeon analyze "python app.py"
```

Output:

```
[File] app.py
[Line] 18
[Error] ZeroDivisionError
[Cause] division by zero
```

---

## Diagnose

Uses AI to explain ambiguous issues without modifying files.

```bash
surgeon diagnose "python app.py"
```

Output:

```
[Issue]
Undefined function calculate_tax

[Reason]
The function is called but is not defined.

[Suggested Fix]
Define or import the function.
```

---

## Rollback

Restore the original file from backup.

```bash
surgeon rollback app.py
```

---

# Workflow

```
User Command
      │
      ▼
Execution Engine
      │
      ▼
Program Executes
      │
      ▼
Failure?
      │
 ┌────┴────┐
 │         │
No        Yes
 │         │
Exit   Trace Parser
              │
              ▼
      Extract Context
              │
              ▼
        Patch Engine
              │
      ┌───────┴────────┐
      │                │
 PATCHABLE      DIAGNOSABLE
      │                │
Apply Patch      Explain Issue
      │
Re-run Program
      │
Success / Rollback
```

---

# Internal Architecture

### Execution Engine

- Executes arbitrary shell commands
- Streams stdout/stderr
- Captures exit codes

---

### Trace Parser

- Parses Python tracebacks
- Finds failing file and line
- Extracts surrounding code context
- Creates safe backups

---

### Patch Engine

- Sends contextual repair requests to the LLM
- Validates generated patches
- Distinguishes between:
  - PATCHABLE
  - DIAGNOSABLE
  - UNPATCHABLE

---

### Orchestrator

Coordinates the complete repair loop.

Features include:

- Retry budget
- Error signature tracking
- Cascade detection
- Automatic rollback
- Safe execution flow

---

# Safety Features

- Automatic `.surgeon.bak` backups
- Rollback on failure
- AST validation before writing
- No guessing for undefined business logic
- Stops repeated repair attempts
- Human-readable diagnostics for ambiguous failures

---

# Example

Suppose:

```python
print("Starting...")

x = 10
y = 0

print(x / y)
```

Run:

```bash
surgeon run "python app.py"
```

Typical output:

```
[Surgeon] Running...

[Surgeon] Failure detected.

[Issue]
ZeroDivisionError

[Surgeon] Creating backup...

[Surgeon] Attempt 1/3...

[Surgeon] Applying patch...

[Surgeon] Re-running...

[Surgeon] Success.
```

---

# Technologies Used

- Python 3.10+
- LiteLLM
- Python AST
- argparse
- subprocess
- python-dotenv

---

# Current Limitations

Current MVP supports only Python projects.

Future language adapters may include:

- JavaScript
- TypeScript
- Java
- Go
- C++

---

# Future Roadmap

- Multi-language support
- Docker sandbox execution
- GitHub Actions integration
- Pull Request generation
- VS Code extension
- IDE integration
- Diff viewer
- Patch confidence scoring
- Multi-file repair
- Secure containerized execution

---

# License

This project is intended for educational, research, and hackathon purposes.
