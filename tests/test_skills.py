import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    "boxes": Path("SKILL.md"),
    "browser-box": Path("browser-box/SKILL.md"),
    "android-devbox": Path("android-devbox/SKILL.md"),
    "bambustudio-box": Path("bambustudio-box/SKILL.md"),
}


def discover(source):
    return [
        Path(directory) / "SKILL.md"
        for directory, _, files in os.walk(source, followlinks=True)
        if "SKILL.md" in files
    ]


class SkillPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="boxes-skills-")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.source = self.work / "global/skills"
        self.source.mkdir(parents=True)
        self.link = self.source / "boxes"
        self.link.symlink_to(ROOT, target_is_directory=True)
        self.cwd = self.work / "unrelated working directory"
        self.cwd.mkdir()
        self.env = os.environ.copy()
        for key in ("PYTHONPATH", "PYTHONHOME"):
            self.env.pop(key, None)
        self.env.update({
            "BOXES_STATE_DIR": str(self.work / "state"),
            "BOXES_DATA_DIR": str(self.work / "data"),
        })

    def run_command(self, arguments):
        result = subprocess.run(
            arguments, cwd=self.cwd, env=self.env, capture_output=True,
            text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_single_symlink_recursively_registers_four_unique_ids(self):
        paths = discover(self.source)
        ids = [path.parent.name for path in paths]
        self.assertEqual(sorted(ids), sorted(SKILLS))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            {path.resolve() for path in paths},
            {ROOT / relative for relative in SKILLS.values()},
        )
        for path in paths:
            with self.subTest(path=path):
                frontmatter = path.read_text().split("---", 2)[1]
                fields = dict(re.findall(r"^(name|description):\s*(.+)$", frontmatter, re.M))
                self.assertEqual(fields["name"], path.parent.name)
                self.assertTrue(fields["description"].strip())

    def test_old_skill_layout_is_gone_and_evals_remain_available(self):
        for relative in ("skills", "browser-box/skills", "android-devbox/skills", "bambustudio-box/skills"):
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())
        cases = json.loads((ROOT / "tests/skill-evals/evals.json").read_text())
        self.assertEqual(cases["skill_name"], "boxes")
        self.assertEqual([case["id"] for case in cases["evals"]], [1, 2, 3, 4])
        for case in cases["evals"]:
            self.assertIn("--password boxbox", case["expected_output"])
        for relative in SKILLS.values():
            self.assertIn("--password boxbox", (ROOT / relative).read_text())

    def test_local_markdown_links_resolve_from_each_source_base(self):
        for base in (ROOT, self.link):
            for relative in SKILLS.values():
                for path in (base / relative, base / relative.parent / "README.md"):
                    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text())
                    for link in links:
                        target = urlsplit(link)
                        if target.scheme or target.netloc or not target.path:
                            continue
                        with self.subTest(path=path, link=link):
                            self.assertTrue((path.parent / unquote(target.path)).resolve().exists())
                            self.assertNotIn("skills/SKILL.md", target.path)

    def test_skill_bootstraps_resolve_source_and_symlink_bases(self):
        for base in (ROOT, self.link):
            for relative in SKILLS.values():
                path = base / relative
                with self.subTest(base=path.parent):
                    bootstrap = re.search(r"```sh\n(.*?)```", path.read_text(), re.S).group(1)
                    self.assertIn("<skill-base>", bootstrap)
                    script = self.work / "resolve-root.sh"
                    script.write_text(
                        "set -eu\n" + bootstrap.replace("<skill-base>", str(path.parent))
                        + '\nprintf "%s\\n" "$BOXES_ROOT"\n'
                        + '"$BOXES_ROOT/box" list --json\n'
                    )
                    output = self.run_command(["sh", str(script)])
                    resolved, listed = output.split("\n", 1)
                    self.assertEqual(Path(resolved), ROOT)
                    self.assertEqual(json.loads(listed), [])

    def test_source_root_keeps_cli_registry_runtime_and_android_assets(self):
        for relative in ("box", "boxes/cli.py", "registry.json", "runtime.json", "android-devbox/Dockerfile", "android-devbox/box-android"):
            with self.subTest(path=relative):
                self.assertTrue((self.link / relative).is_file())
        registry = json.loads((self.link / "registry.json").read_text())
        self.assertEqual(set(registry), {"browser", "android", "bambu"})
        for entry in registry.values():
            self.assertTrue((self.link / entry["directory"] / "SKILL.md").is_file())
            if "build" in entry:
                self.assertTrue((self.link / entry["build"] / "Dockerfile").is_file())
        self.assertIn("environment", json.loads((self.link / "runtime.json").read_text()))

    def test_real_cli_from_unrelated_cwd_via_absolute_and_symlink_paths(self):
        launcher = self.work / "box-link"
        launcher.symlink_to(ROOT / "box")
        for executable in (ROOT / "box", self.link / "box", launcher):
            with self.subTest(executable=executable):
                help_text = self.run_command([str(executable), "--help"])
                self.assertIn("usage: box", help_text)
                self.assertIn("up", help_text)
                self.assertIn("agent", help_text)
                listed = self.run_command([str(executable), "list", "--json"])
                self.assertEqual(json.loads(listed), [])
