import argparse
import sys
from orchestrator import Orchestrator

def main():
    """
    Main CLI entrypoint for StackTrace Surgeon.
    """
    parser = argparse.ArgumentParser(
        description="StackTrace Surgeon: Autonomous test-repair loop for local Python developers."
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available subcommands")

    # Command: surgeon run "<command>"
    run_parser = subparsers.add_parser("run", help="Run a test command under the repair loop")
    run_parser.add_argument("cmd", help="The test command string to wrap and execute (e.g. 'pytest tests/test_auth.py')")
    run_parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum patch-and-verify retry attempts (default: 3)"
    )
    run_parser.add_argument(
        "--project-root",
        default=".",
        help="Root directory of the project codebase (default: current directory)"
    )

    args = parser.parse_args()

    if args.command == "run":
        orchestrator = Orchestrator(
            command=args.cmd,
            max_retries=args.max_retries,
            project_root=args.project_root
        )
        success = orchestrator.run_repair_loop()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
