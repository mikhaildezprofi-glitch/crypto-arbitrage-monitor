import unittest
from pathlib import Path


class SberkassaProbeSyntaxTests(unittest.TestCase):
    def test_probe_script_compiles_without_importing_browser_dependencies(self):
        project_root = Path(__file__).resolve().parents[1]
        script_path = project_root / "scripts" / "sberkassa_chromium_probe.py"
        source = script_path.read_text(encoding="utf-8")
        compile(source, str(script_path), "exec")


if __name__ == "__main__":
    unittest.main()
