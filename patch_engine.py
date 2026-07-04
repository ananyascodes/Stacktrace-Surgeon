import os
import ast
import litellm

class PatchEngine:
    """
    Engine to interface with LLM completions to generate and validate code patches.
    Supports function-level rewrite or line-level fallback rewrite based on AST analysis.
    """
    def __init__(self):
        # Determine model to use based on available API keys in environment
        if os.environ.get("GEMINI_API_KEY"):
            self.model = "gemini/gemini-2.5-flash"
        elif os.environ.get("OPENAI_API_KEY"):
            self.model = "openai/gpt-4o-mini"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            self.model = "anthropic/claude-3-5-haiku-20241022"
        else:
            self.model = "gemini/gemini-2.5-flash"

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
                    end = node.end_lineno if hasattr(node, 'end_lineno') else node.lineno
                    if start <= error_line <= end:
                        func_lines = lines[start - 1:end]
                        return {
                            "name": node.name,
                            "start_line": start,
                            "end_line": end,
                            "code": "\n".join(func_lines)
                        }
        except Exception:
            pass
        return None

    def get_patch(self, file_path: str, global_imports: list[str], sliding_window: list[str], start_line: int, error_line: int, traceback: str) -> dict:
        """
        Requests a targeted patch from the LLM. Automatically detects if the error is inside
        a function and prompts for a function-level rewrite, otherwise falls back to a line-level rewrite.
        
        Returns:
            A dictionary with 'patch_code', 'start_line', and 'end_line' to be replaced.
        """
        func_info = self.find_enclosing_function(file_path, error_line)
        imports_block = "\n".join(global_imports)
        
        system_prompt = (
            "You are StackTrace Surgeon, an autonomous test-repair AI. "
            "You receive the global imports, the traceback of the failure, and the surrounding code context.\n\n"
            "Your task is to fix the error.\n"
            "CRITICAL RULES:\n"
            "1. Output ONLY the raw corrected Python code. Do not include markdown code block blocks (e.g. ```python or ```).\n"
            "2. Do not write any markdown commentary, notes, or explanations. Only Python code.\n"
            "3. Ensure the replacement lines integrate perfectly with the context and maintain correct indentation."
        )

        if func_info:
            # Function-level rewrite
            user_content = (
                f"FILE PATH: {file_path}\n\n"
                f"GLOBAL IMPORTS:\n{imports_block}\n\n"
                f"We found the enclosing function '{func_info['name']}' which contains the error (lines {func_info['start_line']} to {func_info['end_line']}):\n"
                f"```python\n{func_info['code']}\n```\n\n"
                f"TRACEBACK:\n{traceback}\n\n"
                "Please rewrite the entire function body and signature to fix the error. "
                "Provide ONLY the raw replacement Python code for the function:"
            )
            replace_start = func_info['start_line']
            replace_end = func_info['end_line']
        else:
            # Line-level fallback rewrite
            context_block = ""
            for idx, line in enumerate(sliding_window):
                line_num = start_line + idx
                marker = "--> " if line_num == error_line else "    "
                context_block += f"{marker}{line_num:4d}: {line}\n"

            user_content = (
                f"FILE PATH: {file_path}\n\n"
                f"GLOBAL IMPORTS:\n{imports_block}\n\n"
                f"CODE CONTEXT:\n{context_block}\n\n"
                f"The failure occurs on line {error_line}: {sliding_window[error_line - start_line]}\n\n"
                f"TRACEBACK:\n{traceback}\n\n"
                "Please provide the corrected replacement Python code for the error line. "
                "Provide ONLY the raw replacement Python code:"
            )
            replace_start = error_line
            replace_end = error_line

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        response = litellm.completion(
            model=self.model,
            messages=messages,
            temperature=0.0
        )

        raw_patch = response.choices[0].message.content or ""
        cleaned_patch = self._clean_patch(raw_patch)

        return {
            "patch_code": cleaned_patch,
            "start_line": replace_start,
            "end_line": replace_end
        }

    def _clean_patch(self, patch: str) -> str:
        """
        Strips markdown fences or commentary formatting from the LLM output.
        """
        cleaned = patch.strip()
        
        # Remove opening markdown code fences
        if cleaned.startswith("```python"):
            cleaned = cleaned[len("```python"):].lstrip()
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:].lstrip()
            
        # Remove closing markdown code fences
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
        end_idx = end_line # 1-indexed end line matches slice index directly

        before = lines[:start_idx]
        after = lines[end_idx:]

        patch_lines = patch_code.splitlines()
        candidate_lines = before + patch_lines + after
        candidate_content = "\n".join(candidate_lines)

        # Syntactic validation via AST
        try:
            ast.parse(candidate_content)
        except SyntaxError as e:
            print(f"[PatchEngine] Generated patch failed AST parsing: {e}")
            return False

        # Write syntactically valid content to disk
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(candidate_content + "\n")
            
        return True
