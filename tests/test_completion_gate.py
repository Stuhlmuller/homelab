from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class CompletionGateScriptTests(unittest.TestCase):
    def test_script_enforces_author_checklist_items(self) -> None:
        content = (ROOT / "scripts/ci/enforce_completion_gate.py").read_text()
        self.assertIn("REQUIRED_AUTHOR_ITEMS", content)
        self.assertIn("I ran repository validation (`make validate`) after my final code edits.", content)
        self.assertIn("I committed and pushed the final implementation changes for this issue.", content)
        self.assertIn("I understand this work is only complete after this PR is merged into `main`.", content)


if __name__ == "__main__":
    unittest.main()
