import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RootDocsTests(unittest.TestCase):
    def test_root_docs_do_not_embed_the_registered_catalog(self):
        registry = json.loads((ROOT / "registry.json").read_text())
        for relative in ("README.md", "AGENTS.md"):
            text = (ROOT / relative).read_text().casefold()
            for entry in registry.values():
                for reference in (entry["directory"], entry["image"]):
                    with self.subTest(path=relative, reference=reference):
                        self.assertNotRegex(
                            text, rf"(?<![\w-]){re.escape(reference.casefold())}(?![\w-])"
                        )

    def test_readme_shell_examples_use_a_selected_type_and_explicit_password(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("TYPE='<registered-type>'", text)
        self.assertIn("NAME=research", text)
        commands = re.findall(r'"\$BOXES_ROOT/box" ([^\n`]+)', text)
        self.assertTrue(commands)
        for command in commands:
            operation = command.split()[0]
            with self.subTest(command=command):
                if operation != "list" and command != "status --json":
                    self.assertTrue(command.startswith(f'{operation} "$TYPE"'))
                if operation == "up":
                    self.assertIn("--password boxbox", command)


if __name__ == "__main__":
    unittest.main()
