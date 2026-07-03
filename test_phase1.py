from execution_engine import ExecutionEngine
from trace_parser import TraceParser

# create objects

engine = ExecutionEngine()
parser = TraceParser(project_root=".")

# run the failing script

result = engine.run_command("python test_fail.py")

# print execution results

print("Exit code:", result.exit_code)
print("Error output:", result.stderr)

# parse traceback

parsed = parser.parse_traceback(result.stderr)
print("Parsed error:", parsed)

# extract code context

context = parser.get_context_map(parsed.file_path, parsed.line_number)
print("Context:", context)

# create backup

backup_path = parser.create_backup(parsed.file_path)
print("Backup created at:", backup_path)
