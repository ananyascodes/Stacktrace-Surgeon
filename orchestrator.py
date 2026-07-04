import os
import sys
import difflib
from execution_engine import ExecutionEngine, ExecutionResult
from trace_parser import TraceParser, TraceFrame
from patch_engine import PatchEngine

class Orchestrator:
    """
    Ties together execution, traceback parsing, and patch generation/application
    in a state machine repair loop.
    """
    def __init__(self, command: str, max_retries: int = 3, project_root: str = "."):
        self.command = command
        self.max_retries = max_retries
        self.execution_engine = ExecutionEngine()
        self.trace_parser = TraceParser(project_root=project_root)
        self.patch_engine = PatchEngine()
        
    def run_repair_loop(self) -> bool:
        """
        Runs the main repair loop. Runs test execution, parses stack trace,
        attempts patches, and rolls back if retries are exhausted.
        
        Returns:
            True if the test command was successfully repaired (exit code 0), False otherwise.
        """
        print(f"\n[Surgeon] Running: {self.command}")
        result = self.execution_engine.run_command(self.command)

        if result.exit_code == 0:
            print("\n[Surgeon] Tests passed initially. Nothing to repair.")
            return True

        # Intercepted failure, start repair flow
        error_output = result.stdout + "\n" + result.stderr
        parsed_frame = self.trace_parser.parse_traceback(error_output)

        if not parsed_frame:
            print("\n[Surgeon] Test failed, but could not parse a valid project traceback frame.")
            print("[Surgeon] Exiting loop without mutation.")
            return False

        target_file = parsed_frame.file_path
        print(f"\n[Surgeon] Intercepted failure: {parsed_frame.exception_type} on line {parsed_frame.line_number} of {os.path.basename(target_file)}")

        # Create safe backup of targeted file before any mutation
        print(f"[Surgeon] Creating backup of {os.path.basename(target_file)}...")
        backup_path = self.trace_parser.create_backup(target_file)
        
        # Track targeted files so we can clean up/rollback
        current_error_str = error_output
        repaired = False

        try:
            for attempt in range(1, self.max_retries + 1):
                print(f"\n[Surgeon] Attempt {attempt}/{self.max_retries}: Generating patch...")
                
                # Extract context map to feed to patch engine
                parsed_frame = self.trace_parser.parse_traceback(current_error_str)
                if not parsed_frame:
                    print("[Surgeon] Error: Could not parse traceback details for this attempt.")
                    break
                    
                context = self.trace_parser.get_context_map(parsed_frame.file_path, parsed_frame.line_number)
                
                # Fetch patch from LLM
                patch_data = self.patch_engine.get_patch(
                    file_path=target_file,
                    global_imports=context["global_imports"],
                    sliding_window=context["sliding_window"],
                    start_line=context["start_line"],
                    error_line=parsed_frame.line_number,
                    traceback=current_error_str
                )

                patch_code = patch_data["patch_code"]
                replace_start = patch_data["start_line"]
                replace_end = patch_data["end_line"]

                print(f"[Surgeon] Applying patch to {os.path.basename(target_file)} (lines {replace_start} to {replace_end})...")
                
                success_apply = self.patch_engine.apply_patch(
                    file_path=target_file,
                    patch_code=patch_code,
                    start_line=replace_start,
                    end_line=replace_end
                )

                if not success_apply:
                    print("[Surgeon] Patch failed syntax validation. Skipping retry on this patch.")
                    continue

                print("[Surgeon] Patch applied successfully. Re-running command...")
                result = self.execution_engine.run_command(self.command)

                if result.exit_code == 0:
                    print(f"\n[Surgeon] Tests passed on attempt {attempt}!")
                    self._show_diff(target_file, backup_path)
                    repaired = True
                    break
                else:
                    # Capture new error string for next attempt
                    print(f"[Surgeon] Attempt {attempt} failed.")
                    current_error_str = result.stdout + "\n" + result.stderr

        except Exception as e:
            print(f"\n[Surgeon] Unexpected error during repair loop: {e}")
        
        finally:
            # Complete state machine clean up
            if repaired:
                # Success: delete backup file
                if os.path.exists(backup_path):
                    os.remove(backup_path)
            else:
                # Failure: restore original file cleanly
                print(f"\n[Surgeon] Repair unsuccessful. Restoring original file: {os.path.basename(target_file)}...")
                restored = self.trace_parser.restore_from_backup(target_file)
                if restored:
                    print("[Surgeon] Rollback completed successfully.")
                if os.path.exists(backup_path):
                    os.remove(backup_path)

        return repaired

    def _show_diff(self, original_path: str, backup_path: str):
        """
        Calculates and displays a unified text diff of the modifications to the terminal.
        """
        with open(backup_path, "r", encoding="utf-8", errors="replace") as f:
            backup_lines = f.readlines()
        with open(original_path, "r", encoding="utf-8", errors="replace") as f:
            original_lines = f.readlines()

        diff = difflib.unified_diff(
            backup_lines,
            original_lines,
            fromfile=f"a/{os.path.basename(original_path)}",
            tofile=f"b/{os.path.basename(original_path)}"
        )
        
        diff_str = "".join(diff)
        if diff_str:
            print(f"\n--- Unified Diff ({os.path.basename(original_path)}) ---")
            print(diff_str)
            print("------------------------------------------")
        else:
            print("\n[Surgeon] No changes detected in diff.")
