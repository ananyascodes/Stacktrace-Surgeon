import os
import ast
import json
import litellm
from dotenv import load_dotenv

load_dotenv()

# Errors that are deterministically patchable by the LLM
PATCHABLE_ERRORS = {
    "ZeroDivisionError",
    "SyntaxError",
    "ImportError",
    "ModuleNotFoundError",
    "NameError",
    "TypeError",
    "IndexError",
    "KeyError",
    "AttributeError",
}

_TRIAGE_SYSTEM_PROMPT = """\
You are StackTrace Surgeon, an autonomous Python error triage and repair AI.

Given a Python traceback and surrounding code context, classify the error into exactly one of three modes:

## PATCHABLE
Use this when the error is deterministic and can be fixed by editing only the visible code:
- ZeroDivisionError, SyntaxError, ImportError/ModuleNotFoundError (stdlib or installed package swap)
- NameError (typo in visible code), TypeError, IndexError, KeyError, AttributeError

Respond with:
{"mode": "PATCHABLE", "patch_code": "<raw python, no markdown>", "start_line": <int>, "end_line": <int>}

## DIAGNOSABLE
Use this for ambiguous but explainable issues that require human action:
- Undefined functions or missing business logic
- TODO/NotImplemented placeholders
- Missing environment variables or config
- Missing files, resources, external APIs, or uninstalled packages requiring new installs
- Errors in hidden/external code not visible in the context

Respond with:
{"mode": "DIAGNOSABLE", "diagnosis": {"location": "<file:line or function>", "issue": "<one sentence>", "reason": "<one sentence>", "suggested_fix": "<one actionable sentence>"}}

## UNPATCHABLE
Use this when patching is unsafe or impossible:
- Circular imports
- Cascading unrelated failures
- Corrupted syntax across multiple scopes
- Incomplete project context making a correct patch impossible

Respond with:
{"mode": "UNPATCHABLE", "reason": "<one sentence, plain English>"}

STRICT RULES (never violate):
- Never invent business logic, fake imports, undefined functions, or fake APIs.
- Never assume hidden context not visible in the provided code.
- Prefer DIAGNOSABLE over guessing when in doubt.
- Prefer UNPATCHABLE if a correct patch is impossible given visible code.
- Output ONLY valid JSON. No markdown, no explanation, no code fences.
- patch_code must be raw Python only (no ``` fences).
- start_line and end_line are 1-indexed integers referring to the file.
"""

_DIAGNOSIS_SYSTEM_PROMPT = """\
You are StackTrace Surgeon, a Python error diagnosis assistant.

Given a Python traceback and surrounding code context, provide a DIAGNOSABLE analysis.
Do not generate any patch code — only diagnose.

Respond with ONLY this JSON (no markdown, no explanation):
{"mode": "DIAGNOSABLE", "diagnosis": {"location": "<file:line or function name>", "issue": "<one sentence describing the problem>", "reason": "<one sentence explaining why it happens>", "suggested_fix": "<one actionable sentence a developer can act on immediately>"}}

RULES:
- Use simple, beginner-friendly language.
- Be concise and specific.
- Never invent business logic or assume hidden context.
- Output ONLY valid JSON.
"""


class PatchEngine:
    """
    Engine to interface with LLM completions to triage, diagnose, and generate code patches.
    Supports PATCHABLE / DIAGNOSABLE / UNPATCHABLE classification before any mutation.
    """

    def __init__(self):
        self._check_api_key()
        if os.environ.get("GEMINI_API_KEY"):
            self.model = "gemini/gemini-2.5-flash"
        elif os.environ.get("OPENAI_API_KEY"):
            self.model = "openai/gpt-4o-mini"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            self.model = "anthropic/claude-3-5-haiku-20241022"
        else:
            self.model = "gemini/gemini-2.5-flash"

    @staticmethod
    def _check_api_key():
        """Raises a clean error if no API key is configured."""
        keys = ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
        if not any(os.environ.get(k) for k in keys):
            print("[Surgeon] No API key found.")
            print("[Action]  Add GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY in .env")
            raise RuntimeError("No API key configured. See [Action] above.")

    def find_enclosing_function(self, file_path: str, error_line: int) -> dict | None:
        """
        Attempts to locate the enclosing function name, code, and line range using AST.
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            lines = content.splitlines()
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = node.lineno
                    end = node.end_lineno if hasattr(node, "end_lineno") else node.lineno
                    if start <= error_line <= end:
                        func_lines = lines[start - 1:end]
                        return {
                            "name": node.name,
                            "start_line": start,
                            "end_line": end,
                            "code": "\n".join(func_lines),
                        }
        except Exception:
            pass
        return None

    def _build_user_content(
        self,
        file_path: str,
        global_imports: list[str],
        sliding_window: list[str],
        start_line: int,
        error_line: int,
        traceback: str,
    ) -> tuple[str, int, int]:
        """
        Builds the user message content and determines the replace line range.
        Returns (user_content, replace_start, replace_end).
        """
        func_info = self.find_enclosing_function(file_path, error_line)
        imports_block = "\n".join(global_imports)

        if func_info:
            user_content = (
                f"FILE PATH: {file_path}\n\n"
                f"GLOBAL IMPORTS:\n{imports_block}\n\n"
                f"ENCLOSING FUNCTION '{func_info['name']}' "
                f"(lines {func_info['start_line']}–{func_info['end_line']}):\n"
                f"{func_info['code']}\n\n"
                f"TRACEBACK:\n{traceback}\n\n"
                "The error is inside this function. "
                "If PATCHABLE, rewrite the entire function. "
                f"start_line={func_info['start_line']}, end_line={func_info['end_line']}."
            )
            replace_start = func_info["start_line"]
            replace_end = func_info["end_line"]
        else:
            context_block = ""
            for idx, line in enumerate(sliding_window):
                line_num = start_line + idx
                marker = "--> " if line_num == error_line else "    "
                context_block += f"{marker}{line_num:4d}: {line}\n"

            user_content = (
                f"FILE PATH: {file_path}\n\n"
                f"GLOBAL IMPORTS:\n{imports_block}\n\n"
                f"CODE CONTEXT:\n{context_block}\n\n"
                f"Error on line {error_line}: {sliding_window[error_line - start_line]}\n\n"
                f"TRACEBACK:\n{traceback}\n\n"
                f"If PATCHABLE, provide the corrected replacement for line {error_line} only. "
                f"start_line={error_line}, end_line={error_line}."
            )
            replace_start = error_line
            replace_end = error_line

        return user_content, replace_start, replace_end

    def _call_llm(self, system_prompt: str, user_content: str) -> dict:
        """
        Makes the LLM call and parses the JSON response into a dict.
        """
        response = litellm.completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
        )
        raw = (response.choices[0].message.content or "").strip()

        # Strip markdown fences if the model wraps despite instructions
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: treat the whole response as an UNPATCHABLE reason
            return {"mode": "UNPATCHABLE", "reason": f"LLM returned non-JSON response: {raw[:120]}"}

    def get_patch(
        self,
        file_path: str,
        global_imports: list[str],
        sliding_window: list[str],
        start_line: int,
        error_line: int,
        traceback: str,
    ) -> dict:
        """
        Triages the error and returns one of:
          {"mode": "PATCHABLE",   "patch_code": ..., "start_line": ..., "end_line": ...}
          {"mode": "DIAGNOSABLE", "diagnosis": {"location", "issue", "reason", "suggested_fix"}}
          {"mode": "UNPATCHABLE", "reason": ...}
        """
        user_content, replace_start, replace_end = self._build_user_content(
            file_path, global_imports, sliding_window, start_line, error_line, traceback
        )

        result = self._call_llm(_TRIAGE_SYSTEM_PROMPT, user_content)

        mode = result.get("mode", "UNPATCHABLE")

        if mode == "PATCHABLE":
            patch_code = self._clean_patch(result.get("patch_code", ""))
            # Prefer LLM-reported line range if valid, else fall back to AST-detected range
            s = result.get("start_line", replace_start)
            e = result.get("end_line", replace_end)
            if not isinstance(s, int) or not isinstance(e, int):
                s, e = replace_start, replace_end
            return {"mode": "PATCHABLE", "patch_code": patch_code, "start_line": s, "end_line": e}

        if mode == "DIAGNOSABLE":
            diag = result.get("diagnosis", {})
            return {
                "mode": "DIAGNOSABLE",
                "diagnosis": {
                    "location": diag.get("location", file_path),
                    "issue": diag.get("issue", ""),
                    "reason": diag.get("reason", ""),
                    "suggested_fix": diag.get("suggested_fix", ""),
                },
            }

        # UNPATCHABLE or unknown
        return {"mode": "UNPATCHABLE", "reason": result.get("reason", "Repair not possible.")}

    def get_diagnosis(
        self,
        file_path: str,
        global_imports: list[str],
        sliding_window: list[str],
        start_line: int,
        error_line: int,
        traceback: str,
    ) -> dict:
        """
        Diagnosis-only call. Always returns a DIAGNOSABLE result. Used by `surgeon diagnose`.
        """
        user_content, _, _ = self._build_user_content(
            file_path, global_imports, sliding_window, start_line, error_line, traceback
        )
        result = self._call_llm(_DIAGNOSIS_SYSTEM_PROMPT, user_content)
        diag = result.get("diagnosis", {})
        return {
            "mode": "DIAGNOSABLE",
            "diagnosis": {
                "location": diag.get("location", file_path),
                "issue": diag.get("issue", ""),
                "reason": diag.get("reason", ""),
                "suggested_fix": diag.get("suggested_fix", ""),
            },
        }

    def _clean_patch(self, patch: str) -> str:
        """
        Strips markdown fences or commentary formatting from the LLM output.
        """
        cleaned = patch.strip()
        if cleaned.startswith("```python"):
            cleaned = cleaned[len("```python"):].lstrip()
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:].lstrip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()
        return cleaned.strip("\n\r")

    def apply_patch(self, file_path: str, patch_code: str, start_line: int, end_line: int) -> bool:
        """
        Dynamically applies the patch to the target source file in the line range [start_line, end_line].
        Uses AST parsing to validate the modified file's syntactic correctness before writing.

        Returns:
            True if the patch was successfully applied, False otherwise.
        """
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()

        start_idx = start_line - 1
        end_idx = end_line  # 1-indexed end line matches slice index directly

        before = lines[:start_idx]
        after = lines[end_idx:]

        patch_lines = patch_code.splitlines()
        candidate_lines = before + patch_lines + after
        candidate_content = "\n".join(candidate_lines)

        # Syntactic validation via AST
        try:
            ast.parse(candidate_content)
        except SyntaxError as e:
            print(f"[Surgeon] Generated patch failed syntax check: {e}")
            return False

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(candidate_content + "\n")

        return True
