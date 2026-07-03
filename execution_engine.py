import sys
import subprocess
import threading
from typing import NamedTuple, Optional

class ExecutionResult(NamedTuple):
    """
    Data structure containing the results of a command execution.
    """
    exit_code: int
    stdout: str
    stderr: str

class ExecutionEngine:
    """
    An execution engine that runs commands, streams stdout/stderr to the console
    in real-time, and captures output and exit status.
    """
    def __init__(self, cwd: Optional[str] = None):
        """
        Initializes the execution engine.
        
        Args:
            cwd: Optional current working directory in which to execute commands.
        """
        self.cwd = cwd

    def run_command(self, command: str) -> ExecutionResult:
        """
        Runs a shell command string using subprocess.Popen.
        Streams stdout and stderr to the console in real-time using separate reader threads
        to avoid deadlocks, and captures the complete execution results.
        
        Args:
            command: The command string to execute in a shell.
            
        Returns:
            An ExecutionResult namedtuple containing exit_code, stdout, and stderr.
        """
        # Start subprocess with stdout and stderr piped
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.cwd,
            encoding='utf-8',
            errors='replace'
        )

        stdout_accumulated = []
        stderr_accumulated = []

        def read_stream(pipe, write_stream, accumulator):
            try:
                # Read line-by-line in real-time
                for line in iter(pipe.readline, ''):
                    write_stream.write(line)
                    write_stream.flush()
                    accumulator.append(line)
            except Exception as e:
                # Handle unexpected stream read errors safely
                write_stream.write(f"\n[ExecutionEngine error reading stream: {e}]\n")
                write_stream.flush()
            finally:
                pipe.close()

        # Create two reader threads for concurrent streaming
        stdout_thread = threading.Thread(
            target=read_stream,
            args=(process.stdout, sys.stdout, stdout_accumulated),
            daemon=True
        )
        stderr_thread = threading.Thread(
            target=read_stream,
            args=(process.stderr, sys.stderr, stderr_accumulated),
            daemon=True
        )

        # Start the streaming threads
        stdout_thread.start()
        stderr_thread.start()

        # Wait for both threads to finish reading all output
        stdout_thread.join()
        stderr_thread.join()

        # Wait for the child process to complete and obtain exit code
        exit_code = process.wait()

        return ExecutionResult(
            exit_code=exit_code,
            stdout="".join(stdout_accumulated),
            stderr="".join(stderr_accumulated)
        )
