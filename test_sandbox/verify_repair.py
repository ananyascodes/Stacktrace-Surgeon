import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from orchestrator import Orchestrator

class TestRepairLoop(unittest.TestCase):
    def setUp(self):
        self.test_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "temp_broken_test.py"))
        # Create a simple failing script
        with open(self.test_file, "w", encoding="utf-8") as f:
            f.write("def test_broken_function():\n    assert 1 == 2\n")

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)
        backup = self.test_file + ".surgeon.bak"
        if os.path.exists(backup):
            os.remove(backup)

    @patch("litellm.completion")
    def test_successful_repair_on_second_attempt(self, mock_completion):
        # First completion: return a patch that still fails (assert 1 == 3)
        # Second completion: return a patch that passes (assert 1 == 1)
        response_fail = MagicMock()
        response_fail.choices = [MagicMock()]
        response_fail.choices[0].message.content = "def test_broken_function():\n    assert 1 == 3"

        response_pass = MagicMock()
        response_pass.choices = [MagicMock()]
        response_pass.choices[0].message.content = "def test_broken_function():\n    assert 1 == 1"

        mock_completion.side_effect = [response_fail, response_pass]

        # Quote the command path to handle directory spaces safely
        orchestrator = Orchestrator(
            command=f'pytest "{self.test_file}"',
            max_retries=2,
            project_root=os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        )

        success = orchestrator.run_repair_loop()
        
        # Verify success is reported
        self.assertTrue(success)
        
        # Verify backup is cleaned up
        self.assertFalse(os.path.exists(self.test_file + ".surgeon.bak"))
        
        # Verify the file is fixed
        with open(self.test_file, "r") as f:
            content = f.read()
        self.assertIn("assert 1 == 1", content)
        print("\n[TEST PASS] test_successful_repair_on_second_attempt passed!")

    @patch("litellm.completion")
    def test_exhausted_retries_and_rollback(self, mock_completion):
        # Mock LLM constantly returning patches that fail the test
        response_fail = MagicMock()
        response_fail.choices = [MagicMock()]
        response_fail.choices[0].message.content = "def test_broken_function():\n    assert 1 == 4"
        mock_completion.return_value = response_fail

        # Quote the command path to handle directory spaces safely
        orchestrator = Orchestrator(
            command=f'pytest "{self.test_file}"',
            max_retries=2,
            project_root=os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        )

        success = orchestrator.run_repair_loop()
        
        # Verify failure is reported
        self.assertFalse(success)
        
        # Verify backup is cleaned up after rollback
        self.assertFalse(os.path.exists(self.test_file + ".surgeon.bak"))
        
        # Verify the original file content was rolled back cleanly
        with open(self.test_file, "r") as f:
            content = f.read()
        self.assertIn("assert 1 == 2", content)
        print("[TEST PASS] test_exhausted_retries_and_rollback passed!")

if __name__ == "__main__":
    unittest.main()
