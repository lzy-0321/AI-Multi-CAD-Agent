import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ("README.zh-CN.md", "README.md", "README.md", "README.zh-CN.md"),
    ("docs/zh/installation-quickstart.md", "docs/installation-quickstart.md",
     "../installation-quickstart.md", "zh/installation-quickstart.md"),
    ("docs/zh/agent-workflow.md", "docs/agent-workflow.md",
     "../agent-workflow.md", "zh/agent-workflow.md"),
    ("docs/zh/validation-v0.2.md", "docs/validation-v0.2.md",
     "../validation-v0.2.md", "zh/validation-v0.2.md"),
    ("docs/zh/requirements-v2.md", "docs/requirements-v2.md",
     "../requirements-v2.md", "zh/requirements-v2.md"),
)


def commands(text):
    blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
    return [line for block in blocks for line in block.splitlines() if not line.strip().startswith("#")]


class DocsSiteTests(unittest.TestCase):
    def test_github_language_switch_links_resolve(self):
        for chinese_path, english_path, to_english, to_chinese in PAIRS:
            chinese = (ROOT / chinese_path).read_text(encoding="utf-8")
            english = (ROOT / english_path).read_text(encoding="utf-8")
            self.assertTrue(chinese.startswith(f"[English]({to_english}) | **中文**\n"))
            self.assertTrue(english.startswith(f"**English** | [中文]({to_chinese})\n"))
            self.assertNotIn("index.html", chinese)
            self.assertNotIn("index.html", english)
            self.assertEqual(commands(chinese), commands(english))
            for path, text in ((ROOT / chinese_path, chinese), (ROOT / english_path, english)):
                for href in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                    if href.startswith(("http://", "https://", "mailto:")):
                        continue
                    target = (path.parent / href.split("#", 1)[0]).resolve()
                    self.assertTrue(target.is_file(), f"{path} -> {href}")
