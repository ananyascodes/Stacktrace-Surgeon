import os
import sys
import difflib
from execution_engine import ExecutionEngine, ExecutionResult
from trace_parser import TraceParser, TraceFrame
from patch_engine import PatchEngine


class Orchestrator:
    """
    Ties together execution, traceback parsing, and patch generation/application
    in a state machine repair loop with error signature tracking and cascade detection.
    """

    def __init__(self, command: str, max_retries: int = 3, project_root: str = "."):
        self.command = command
        self.max_retries = max_retries
        self.execution_engine = ExecutionEngine()
        self.trace_parser = TraceParser(project_root=project_root)
        self.patch_engine = PatchEngine()

    @staticmethod
    def _error_signature(frame: TraceFrame) -> tuple:
        """Returns a hashable identity tuple for a parsed error frame."""
        return (frame.exception_type, frame.file_path, frame.line_number)

    def run_repair_loop(self) -> bool:
        """
        Runs the main repair loop. Executes the command, parses stack traces,
        attempts patches based on triage mode, and rolls back on failure.

        Returns:
            True if the command was successfully repaired (exit code 0), False otherwise.
        """
        print(f"\n[Surgeon] Running...")
        result = self.execution_engine.run_command(self.command)

        if result.exit_code == 0:
            print("\n[Surgeon] Success.")
            return True

        error_output = result.stdout + "\n" + result.stderr
        parsed_frame = self.trace_parser.parse_traceback(error_output)

        if not parsed_frame:
            print("\n[Surgeon] Failure detected.")
            print("[Surgeon] Could not parse a project traceback frame. Exiting.")
            return False

        print(f"\n[Surgeon] Failure detected.")
        print(f"[Issue]   {parsed_frame.exception_type}: {parsed_frame.exception_message}")

        target_file = parsed_frame.file_path
        print(f"\n[Surgeon] Creating backup...")
        backup_path = self.trace_parser.create_backup(target_file)

        seen_signatures: set[tuple] = set()
        cascade_count = 0
        current_error_str = error_output
        current_frame = parsed_frame
        repaired = False

        try:
            for attempt in range(1, self.max_retries + 1):
                sig = self._error_signature(current_frame)

                # Error signature tracking — stop if identical error recurs after a patch
                if sig in seen_signatures:
                    print("\n[Surgeon] Repeated identical error detected.")
                    print("[Action]  Stopping early.")
                    break
                seen_signatures.add(sig)

                # Cascade detection — new error in a different file
                if current_frame.file_path != target_file:
                    cascade_count += 1
                    if cascade_count > 1:
                        print("\n[Surgeon] New unrelated failure detected.")
                        print("[Action]  Switching to diagnosis.")
                        self._run_diagnosis(target_file, current_frame, current_error_str)
                        break

                print(f"\n[Surgeon] Attempt {attempt}/{self.max_retries}...")

                context = self.trace_parser.get_context_map(
                    current_frame.file_path, current_frame.line_number
                )

                patch_data = self.patch_engine.get_patch(
                    file_path=current_frame.file_path,
                    global_imports=context["global_imports"],
                    sliding_window=context["sliding_window"],
                    start_line=context["start_line"],
                    error_line=current_frame.line_number,
                    traceback=current_error_str,
                )

                mode = patch_data["mode"]

                if mode == "DIAGNOSABLE":
                    diag = patch_data["diagnosis"]
                    print(f"\n[Issue]        {diag['issue']}")
                    print(f"[Reason]       {diag['reason']}")
                    print(f"[Suggested Fix] {diag['suggested_fix']}")
                    self.trace_parser.restore_from_backup(target_file)
                    repaired = False
                    return False

                if mode == "UNPATCHABLE":
                    print(f"\n[Surgeon] Cannot safely repair.")
                    print(f"[Reason]  {patch_data['reason']}")
                    self.trace_parser.restore_from_backup(target_file)
                    repaired = False
                    return False

                # PATCHABLE — attempt the patch
                print(f"[Surgeon] Applying patch...")
                success_apply = self.patch_engine.apply_patch(
                    file_path=current_frame.file_path,
                    patch_code=patch_data["patch_code"],
                    start_line=patch_data["start_line"],
                    end_line=patch_data["end_line"],
                )

                if not success_apply:
                    print("[Surgeon] Patch failed syntax check. Retrying...")
                    continue

                print("[Surgeon] Re-running...")
                result = self.execution_engine.run_command(self.command)

                if result.exit_code == 0:
                    print(f"\n[Surgeon] Success.")
                    self._show_diff(target_file, backup_path)
                    repaired = True
                    break

                current_error_str = result.stdout + "\n" + result.stderr
                new_frame = self.trace_parser.parse_traceback(current_error_str)
                if not new_frame:
                    print("[Surgeon] Could not parse traceback after patch. Stopping.")
                    break
                current_frame = new_frame

        except RuntimeError:
            # Already printed by PatchEngine (e.g. no API key)
            pass
        except Exception as e:
            print(f"\n[Surgeon] Unexpected error: {e}")

        finally:
            if repaired:
                if os.path.exists(backup_path):
                    os.remove(backup_path)
            else:
                print(f"\n[Surgeon] Restoring original file...")
                restored = self.trace_parser.restore_from_backup(target_file)
                if restored:
                    print("[Surgeon] Rollback completed.")
                if os.path.exists(backup_path):
                    os.remove(backup_path)

        return repaired

    def _run_diagnosis(self, file_path: str, frame: TraceFrame, error_str: str):
        """Calls the patch engine in diagnosis-only mode and prints the result."""
        try:
            context = self.trace_parser.get_context_map(file_path, frame.line_number)
            result = self.patch_engine.get_diagnosis(
                file_path=file_path,
                global_imports=context["global_imports"],
                sliding_window=context["sliding_window"],
                start_line=context["start_line"],
                error_line=frame.line_number,
                traceback=error_str,
            )
            diag = result["diagnosis"]
            print(f"\n[Issue]        {diag['issue']}")
            print(f"[Reason]       {diag['reason']}")
            print(f"[Suggested Fix] {diag['suggested_fix']}")
        except Exception as e:
            print(f"[Surgeon] Diagnosis failed: {e}")

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
            tofile=f"b/{os.path.basename(original_path)}",
        )

        diff_str = "".join(diff)
        if diff_str:
            print(f"\n--- Patch Applied ({os.path.basename(original_path)}) ---")
            print(diff_str)
            print("---------------------------------------------------")
