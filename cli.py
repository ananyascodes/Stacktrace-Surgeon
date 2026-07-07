import argparse
import os
import sys
from execution_engine import ExecutionEngine
from trace_parser import TraceParser
from patch_engine import PatchEngine
from orchestrator import Orchestrator


def cmd_run(args):
    """Run the full autonomous repair loop."""
    orchestrator = Orchestrator(
        command=args.cmd,
        max_retries=args.max_retries,
        project_root=args.project_root,
    )
    success = orchestrator.run_repair_loop()
    sys.exit(0 if success else 1)


def cmd_analyze(args):
    """
    Run a command, parse the traceback, and print a structured summary.
    No patching is performed.
    """
    engine = ExecutionEngine()
    parser = TraceParser(project_root=args.project_root)

    print(f"\n[Surgeon] Running...")
    result = engine.run_command(args.cmd)

    if result.exit_code == 0:
        print("\n[Surgeon] Command exited cleanly. Nothing to analyze.")
        sys.exit(0)

    error_output = result.stdout + "\n" + result.stderr
    frame = parser.parse_traceback(error_output)

    if not frame:
        print("\n[Surgeon] Could not parse a project traceback frame.")
        sys.exit(1)

    print(f"\n[File]  {os.path.relpath(frame.file_path)}")
    print(f"[Line]  {frame.line_number}")
    print(f"[Error] {frame.exception_type}")
    print(f"[Cause] {frame.exception_message or '(no message)'}")
    sys.exit(1)


def cmd_diagnose(args):
    """
    Run a command, then use the patch engine in diagnosis-only mode.
    No patching is performed.
    """
    engine = ExecutionEngine()
    parser = TraceParser(project_root=args.project_root)

    print(f"\n[Surgeon] Running...")
    result = engine.run_command(args.cmd)

    if result.exit_code == 0:
        print("\n[Surgeon] Command exited cleanly. Nothing to diagnose.")
        sys.exit(0)

    error_output = result.stdout + "\n" + result.stderr
    frame = parser.parse_traceback(error_output)

    if not frame:
        print("\n[Surgeon] Could not parse a project traceback frame.")
        sys.exit(1)

    try:
        patch_engine = PatchEngine()
        context = parser.get_context_map(frame.file_path, frame.line_number)
        diag_result = patch_engine.get_diagnosis(
            file_path=frame.file_path,
            global_imports=context["global_imports"],
            sliding_window=context["sliding_window"],
            start_line=context["start_line"],
            error_line=frame.line_number,
            traceback=error_output,
        )
        diag = diag_result["diagnosis"]
        print(f"\n[Issue]        {diag['issue']}")
        print(f"[Reason]       {diag['reason']}")
        print(f"[Suggested Fix] {diag['suggested_fix']}")
    except RuntimeError:
        pass  # API key error already printed by PatchEngine
    sys.exit(1)


def cmd_rollback(args):
    """Restore a file from its .surgeon.bak backup."""
    file_path = os.path.abspath(args.file)
    if not os.path.isfile(file_path):
        print(f"[Surgeon] File not found: {file_path}")
        sys.exit(1)

    restored = TraceParser.restore_from_backup(file_path)
    if restored:
        print("[Surgeon] Restored original file.")
        sys.exit(0)
    else:
        bak = file_path + ".surgeon.bak"
        print(f"[Surgeon] No backup found at: {bak}")
        sys.exit(1)


def main():
    """
    Main CLI entrypoint for StackTrace Surgeon.
    """
    parser = argparse.ArgumentParser(
        description="StackTrace Surgeon: Autonomous test-repair loop for local Python developers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  surgeon run \"pytest tests/\"\n"
            "  surgeon analyze \"python app.py\"\n"
            "  surgeon diagnose \"python app.py\"\n"
            "  surgeon rollback app.py"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available subcommands")

    # -- run --
    run_parser = subparsers.add_parser("run", help="Run command under the autonomous repair loop")
    run_parser.add_argument("cmd", help="Command to execute (e.g. 'pytest tests/')")
    run_parser.add_argument("--max-retries", type=int, default=3, help="Max repair attempts (default: 3)")
    run_parser.add_argument("--project-root", default=".", help="Project root directory (default: .)")

    # -- analyze --
    analyze_parser = subparsers.add_parser("analyze", help="Parse and display traceback without patching")
    analyze_parser.add_argument("cmd", help="Command to execute and analyze")
    analyze_parser.add_argument("--project-root", default=".", help="Project root directory (default: .)")

    # -- diagnose --
    diagnose_parser = subparsers.add_parser("diagnose", help="Diagnose error cause without patching")
    diagnose_parser.add_argument("cmd", help="Command to execute and diagnose")
    diagnose_parser.add_argument("--project-root", default=".", help="Project root directory (default: .)")

    # -- rollback --
    rollback_parser = subparsers.add_parser("rollback", help="Restore a file from its .surgeon.bak backup")
    rollback_parser.add_argument("file", help="Path to the file to restore")

    args = parser.parse_args()

    dispatch = {
        "run": cmd_run,
        "analyze": cmd_analyze,
        "diagnose": cmd_diagnose,
        "rollback": cmd_rollback,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
