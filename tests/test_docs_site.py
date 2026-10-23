import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ("README.md", "docs/en/readme.md", "docs/en/readme.md", "../../README.md"),
    ("docs/installation-quickstart.md", "docs/en/installation-quickstart.md",
     "en/installation-quickstart.md", "../installation-quickstart.md"),
    ("docs/agent-workflow.md", "docs/en/agent-workflow.md",
     "en/agent-workflow.md", "../agent-workflow.md"),
    ("docs/validation-v0.2.md", "docs/en/validation-v0.2.md",
     "en/validation-v0.2.md", "../validation-v0.2.md"),
    ("docs/requirements-v2.md", "docs/en/requirements-v2.md",
     "en/requirements-v2.md", "../requirements-v2.md"),
)


def commands(text):
    blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
    return [line for block in blocks for line in block.splitlines() if not line.strip().startswith("#")]


class DocsSiteTests(unittest.TestCase):
    def test_github_language_switch_links_resolve(self):
        for chinese_path, english_path, to_english, to_chinese in PAIRS:
            chinese = (ROOT / chinese_path).read_text(encoding="utf-8")
            english = (ROOT / english_path).read_text(encoding="utf-8")
            self.assertTrue(chinese.startswith(f"**中文** | [English]({to_english})\n"))
            self.assertTrue(english.startswith(f"[中文]({to_chinese}) | **English**\n"))
            self.assertNotIn("index.html", chinese)
            self.assertNotIn("index.html", english)
            self.assertEqual(commands(chinese), commands(english))
            for path, text in ((ROOT / chinese_path, chinese), (ROOT / english_path, english)):
                for href in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                    if href.startswith(("http://", "https://", "mailto:")):
                        continue
                    target = (path.parent / href.split("#", 1)[0]).resolve()
                    self.assertTrue(target.is_file(), f"{path} -> {href}")
