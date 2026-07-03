import os
import re
import sys
import shutil
import ast
import sysconfig
from typing import NamedTuple, Optional

class TraceFrame(NamedTuple):
    """
    Data structure representing parsed information from a traceback frame.
    """
    file_path: str
    line_number: int
    exception_type: str
    exception_message: str

class TraceParser:
    """
    Deterministic traceback parser for Python error logs. Extracts the lowest user codebase frame,
    gathers local context (imports, code window), and manages backups.
    """
    def __init__(self, project_root: Optional[str] = None):
        """
        Initializes the parser.
        
        Args:
            project_root: Optional path to the project root directory. Defaults to the current working directory.
        """
        if project_root is None:
            self.project_root = os.path.abspath(os.getcwd())
        else:
            self.project_root = os.path.abspath(project_root)

    def is_project_path(self, path_str: str) -> bool:
        """
        Determines if a given path string belongs to the user's project codebase.
        Excludes site-packages, standard library paths, and non-project paths.
        
        Args:
            path_str: Path string from the traceback.
            
        Returns:
            True if the path belongs to the user's project codebase, False otherwise.
        """
        try:
            # Resolve relative and absolute paths against the project root
            abs_path = os.path.abspath(os.path.join(self.project_root, path_str))
        except Exception:
            return False

        # Ensure the path starts with project_root
        try:
            relative = os.path.relpath(abs_path, self.project_root)
            if relative.startswith("..") or os.path.isabs(relative):
                return False
        except Exception:
            return False

        # Ignore standard exclusion patterns (virtual environments, node_modules, git internals)
        exclusions = ["site-packages", "dist-packages", "node_modules", ".venv", "venv", ".git"]
        normalized_abs = abs_path.lower()
        for excl in exclusions:
            if excl in normalized_abs:
                return False

        # Exclude standard library paths
        stdlib_path = sysconfig.get_path("stdlib")
        if stdlib_path:
            stdlib_abs = os.path.abspath(stdlib_path).lower()
            if normalized_abs.startswith(stdlib_abs):
                return False

        return True

    def extract_exception(self, error_str: str) -> tuple[str, str]:
        """
        Extracts exception type and exception message from raw stderr or pytest output.
        Uses deterministic pattern matching.
        
        Args:
            error_str: Raw traceback or test execution output.
            
        Returns:
            A tuple of (exception_type, exception_message).
        """
        lines = [line.strip() for line in error_str.splitlines() if line.strip()]
        
        # 1. Check for pytest path:line: ExceptionType line (bottom-up)
        # e.g., "test_sandbox\temp_broken_test.py:2: AssertionError"
        pytest_err_line_pattern = re.compile(
            r'^.*\.py:\d+:\s*([a-zA-Z_][a-zA-Z0-9_]*)$'
        )
        for line in reversed(lines):
            match = pytest_err_line_pattern.match(line)
            if match:
                exc_type = match.group(1)
                # Now find the message. Look for a line starting with E in the vicinity
                original_lines = error_str.splitlines()
                for l in reversed(original_lines):
                    if l.startswith("E   ") or l.startswith("E  "):
                        content = l[1:].strip()
                        # If content starts with exc_type + ":", extract the rest
                        if content.startswith(f"{exc_type}:"):
                            return exc_type, content[len(exc_type)+1:].strip()
                        # Otherwise if it's an assertion, return the whole E content
                        if exc_type == "AssertionError":
                            return exc_type, content
                return exc_type, ""

        # 2. Look for pytest short summary output at the bottom (e.g. FAILED test.py::test_fn - ValueError: invalid)
        pytest_summary_pattern = re.compile(
            r'^FAILED\s+.*\s+-\s+([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)$'
        )
        for line in reversed(lines):
            match = pytest_summary_pattern.match(line)
            if match:
                return match.group(1), match.group(2)

        # 3. Look for pytest error details prefix (e.g. E       KeyError: 'age')
        original_lines = error_str.splitlines()
        for line in reversed(original_lines):
            if line.startswith("E   ") or line.startswith("E  "):
                content = line[1:].strip()
                if ":" in content:
                    parts = content.split(":", 1)
                    exc_type = parts[0].strip()
                    exc_msg = parts[1].strip()
                    if exc_type.isidentifier():
                        return exc_type, exc_msg
                else:
                    if content.isidentifier():
                        return content, ""

        # 4. Look for standard traceback exception lines (e.g. KeyError: 'age')
        for line in reversed(lines):
            if line.startswith("===") or line.startswith("---") or line.startswith("___"):
                continue
            if "File " in line and "line " in line:
                continue
            # Matches ExceptionType: message
            match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)$', line)
            if match:
                exc_type = match.group(1)
                # Verify that it is a valid exception identifier and not configuration key
                # By checking if it's in lowercase or a config variable
                if exc_type.isidentifier() and not exc_type.islower() and "mode" not in exc_type:
                    return exc_type, match.group(2)
            # Matches ExceptionType only
            if line.isidentifier() and (line.endswith("Error") or line.endswith("Exception") or line in ["SystemExit", "KeyboardInterrupt", "StopIteration"]):
                return line, ""

        return "UnknownException", ""

    def parse_traceback(self, error_str: str) -> Optional[TraceFrame]:
        """
        Parses the raw traceback string and extracts traceback frame details
        from the absolute lowest frame that belongs to the user's project codebase.
        
        Args:
            error_str: The raw traceback error string.
            
        Returns:
            A TraceFrame instance if a project frame is found, otherwise None.
        """
        # Patterns to locate traceback source lines
        patterns = [
            # Standard python tracebacks: File "path", line 123
            re.compile(r'File "([^"]+)", line (\d+)'),
            # Pytest or compiler-style trace lines: path:123 or path:123: ExceptionType
            re.compile(r'(?:^|\s)([a-zA-Z]:\\[^:\n]+|/[^:\n]+|[a-zA-Z0-9_\-\./\\]+\.py):(\d+)'),
        ]

        lines = error_str.splitlines()
        # Scan from the bottom of the error string upwards to identify the lowest codebase frame
        for line in reversed(lines):
            for pattern in patterns:
                for match in pattern.finditer(line):
                    path_str = match.group(1)
                    line_str = match.group(2)

                    try:
                        line_num = int(line_str)
                    except ValueError:
                        continue

                    # Validate that this is a project path and is an actual file on disk
                    if self.is_project_path(path_str):
                        abs_path = os.path.abspath(os.path.join(self.project_root, path_str))
                        if os.path.isfile(abs_path):
                            exc_type, exc_msg = self.extract_exception(error_str)
                            return TraceFrame(
                                file_path=abs_path,
                                line_number=line_num,
                                exception_type=exc_type,
                                exception_message=exc_msg
                            )
        return None

    def get_context_map(self, file_path: str, error_line: int) -> dict:
        """
        Opens the target file, extracts its global imports, and takes a sliding window
        of code (25 lines above the error, 15 lines below the error).
        
        Args:
            file_path: Absolute path to the source file.
            error_line: 1-indexed error line number.
            
        Returns:
            A dictionary containing context metadata, global imports, and the sliding code window.
        """
        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"Target file does not exist: {abs_path}")

        # Read file with safe encoding handling
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        lines = content.splitlines()
        total_lines = len(lines)

        # 1. Capture global imports using AST (fallback to line regex on syntax error)
        global_imports = []
        try:
            tree = ast.parse(content)
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    start = node.lineno - 1
                    end = node.end_lineno if hasattr(node, 'end_lineno') else node.lineno
                    global_imports.extend(lines[start:end])
        except Exception:
            # Fallback regex scanning if python file contains syntax errors
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    global_imports.append(line)

        # 2. Extract sliding code window
        start_idx = max(0, error_line - 1 - 25)
        end_idx = min(total_lines, error_line + 15)

        window_lines = lines[start_idx:end_idx]
        start_line_num = start_idx + 1

        return {
            "file_path": abs_path,
            "global_imports": global_imports,
            "sliding_window": window_lines,
            "start_line": start_line_num,
            "error_line": error_line
        }

    @staticmethod
    def create_backup(file_path: str) -> str:
        """
        Creates a backup copy of the target file before any mutations happen.
        Saved at `<file_path>.surgeon.bak`.
        
        Args:
            file_path: Path to the target file.
            
        Returns:
            The absolute path of the backup file.
        """
        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"Target file for backup does not exist: {abs_path}")

        backup_path = abs_path + ".surgeon.bak"
        shutil.copy2(abs_path, backup_path)
        return backup_path

    @staticmethod
    def restore_from_backup(file_path: str) -> bool:
        """
        Restores the targeted file from its `.surgeon.bak` file.
        
        Args:
            file_path: Path to the target file.
            
        Returns:
            True if the backup existed and was restored, False otherwise.
        """
        abs_path = os.path.abspath(file_path)
        backup_path = abs_path + ".surgeon.bak"
        if os.path.isfile(backup_path):
            shutil.copy2(backup_path, abs_path)
            return True
        return False
