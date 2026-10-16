import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


class RootDocsTests(unittest.TestCase):
    def test_root_docs_do_not_embed_the_registered_catalog(self):
        registry = json.loads((ROOT / "registry.json").read_text())
        for relative in ("README.md", "USAGE.md", "AGENTS.md"):
            text = (ROOT / relative).read_text().casefold()
            for entry in registry.values():
                for reference in (entry["directory"], entry["image"]):
                    with self.subTest(path=relative, reference=reference):
                        self.assertNotRegex(
                            text, rf"(?<![\w-]){re.escape(reference.casefold())}(?![\w-])"
                        )

    def test_readme_shell_examples_use_a_selected_type_and_preserve_credentials(self):
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
                    self.assertNotIn("--password", command)
        self.assertIn("New boxes receive a random password.", text)
        self.assertIn("preserves saved credentials", text)

    def test_operational_docs_do_not_supply_a_fixed_password(self):
        registry = json.loads((ROOT / "registry.json").read_text())
        paths = [ROOT / "USAGE.md"]
        for directory in (ROOT, *(ROOT / entry["directory"] for entry in registry.values())):
            paths.extend(directory / filename for filename in ("README.md", "SKILL.md"))
        for path in paths:
            with self.subTest(path=path):
                text = path.read_text()
                self.assertNotIn("boxbox", text)
                self.assertNotRegex(text, r"--password\s+(?!`|to\b|retains\b|preserves\b|or\b)\S+")

    def test_root_document_links_and_heading_anchors_resolve(self):
        for relative in ("README.md", "USAGE.md"):
            path = ROOT / relative
            links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text())
            self.assertTrue(links)
            for link in links:
                target = urlsplit(link)
                if target.scheme or target.netloc:
                    continue
                destination = path.parent / unquote(target.path) if target.path else path
                with self.subTest(path=relative, link=link):
                    self.assertTrue(destination.exists())
                    if target.fragment:
                        headings = re.findall(r"^#{1,6} (.+)$", destination.read_text(), re.M)
                        anchors = {
                            re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
                            for heading in headings
                        }
                        self.assertIn(unquote(target.fragment), anchors)


if __name__ == "__main__":
    unittest.main()
