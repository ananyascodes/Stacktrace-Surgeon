import os
import sys

# Add root directory to sys.path so we can import execution_engine and trace_parser
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from execution_engine import ExecutionEngine
from trace_parser import TraceParser, TraceFrame

def test_execution_engine_success():
    print("\n--- Running Success Execution Test ---")
    engine = ExecutionEngine()
    result = engine.run_command('python -c "import sys; print(\'Hello from stdout\'); sys.stderr.write(\'Hello from stderr\\n\')"')
    
    print(f"Exit Code: {result.exit_code}")
    print(f"Stdout captured: {repr(result.stdout)}")
    print(f"Stderr captured: {repr(result.stderr)}")
    
    assert result.exit_code == 0
    assert "Hello from stdout" in result.stdout
    assert "Hello from stderr" in result.stderr
    print("[PASS] Success Execution Test Passed!")

def test_execution_engine_failure_and_parsing():
    print("\n--- Running Failure & Parsing Test ---")
    engine = ExecutionEngine()
    # Execute a failing pytest run on test_broken.py
    cmd = "pytest test_sandbox/test_broken.py"
    result = engine.run_command(cmd)
    
    print(f"Exit Code: {result.exit_code}")
    assert result.exit_code != 0
    
    # Ingest stdout/stderr (pytest outputs failures to stdout by default)
    combined_output = result.stdout + "\n" + result.stderr
    
    parser = TraceParser()
    frame = parser.parse_traceback(combined_output)
    
    assert frame is not None, "Failed to parse traceback frame!"
    print(f"Parsed Frame: {frame}")
    
    # Verify exact values
    assert os.path.basename(frame.file_path) == "test_broken.py"
    assert frame.line_number == 8
    assert frame.exception_type == "KeyError"
    assert "age" in frame.exception_message
    print("[PASS] Failure & Traceback Parsing Test Passed!")
    
    # Test Context Mapping
    print("\n--- Running Context Mapping Test ---")
    context = parser.get_context_map(frame.file_path, frame.line_number)
    print(f"File Path: {context['file_path']}")
    print(f"Global Imports: {context['global_imports']}")
    print(f"Sliding Window Start Line: {context['start_line']}")
    print(f"Sliding Window lines:")
    for idx, line in enumerate(context['sliding_window']):
        print(f"  {context['start_line'] + idx}: {line}")
        
    assert context["error_line"] == 8
    assert len(context["sliding_window"]) > 0
    print("[PASS] Context Mapping Test Passed!")

def test_backup_and_restore():
    print("\n--- Running Backup & Restore Test ---")
    parser = TraceParser()
    target_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_broken.py"))
    
    # Read original contents
    with open(target_file, "r") as f:
        original_content = f.read()
        
    # Create backup
    backup_path = parser.create_backup(target_file)
    print(f"Backup created at: {backup_path}")
    assert os.path.exists(backup_path)
    
    try:
        # Mutate the file
        with open(target_file, "w") as f:
            f.write("# MUTATED FILE CONTENTS\n")
            
        # Verify mutation occurred
        with open(target_file, "r") as f:
            mutated_content = f.read()
        assert mutated_content == "# MUTATED FILE CONTENTS\n"
        print("File mutated successfully.")
        
        # Restore file
        success = parser.restore_from_backup(target_file)
        assert success
        
        # Verify restored contents
        with open(target_file, "r") as f:
            restored_content = f.read()
        assert restored_content == original_content
        print("[PASS] File restored successfully from backup.")
        
    finally:
        # Clean up backup file
        if os.path.exists(backup_path):
            os.remove(backup_path)
            print("Backup file cleaned up.")
            
    print("[PASS] Backup & Restore Test Passed!")

if __name__ == "__main__":
    try:
        test_execution_engine_success()
        test_execution_engine_failure_and_parsing()
        test_backup_and_restore()
        print("\n=============================")
        print("ALL FOUNDATIONAL TESTS PASSED!")
        print("=============================")
    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILURE: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] UNEXPECTED ERROR: {e}")
        sys.exit(1)
