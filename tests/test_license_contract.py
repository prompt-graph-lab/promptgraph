import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LICENSE = ROOT / "LICENSE"
REQUIREMENTS_IN = ROOT / "requirements.in"
REQUIREMENTS_LOCK = ROOT / "requirements.txt"
SETUP = ROOT / "setup.bat"
RELEASE_PROCESS = ROOT / "docs" / "release-process.md"
PUBLIC_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "user-guide.md",
    ROOT / "docs" / "releases" / "1.0.0.md",
    RELEASE_PROCESS,
)
PIN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[^\s;]+$")


def _exact_pins(path: Path) -> tuple[str, ...]:
    pins = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and PIN_PATTERN.fullmatch(line):
            pins.append(line)
    return tuple(pins)


class LicenseContractTests(unittest.TestCase):
    def test_license_is_standard_mit_with_project_attribution(self):
        text = LICENSE.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("MIT License\n"))
        self.assertIn("Copyright (c) 2026 PromptGraph Lab.", text)
        self.assertIn("Permission is hereby granted", text)
        self.assertIn("The above copyright notice and this permission notice", text)
        self.assertIn("THE SOFTWARE IS PROVIDED \"AS IS\"", text)
        self.assertNotIn("Apache License", text)
        self.assertNotIn("GNU GENERAL PUBLIC LICENSE", text)

    def test_direct_intent_and_exact_lock_are_reconciled_in_audit(self):
        direct = _exact_pins(REQUIREMENTS_IN)
        locked = _exact_pins(REQUIREMENTS_LOCK)
        audit = RELEASE_PROCESS.read_text(encoding="utf-8")
        table_start = audit.index("| License evidence | Exact lock entries")
        table_end = audit.index("\n\nThis repository only", table_start)
        audit_table = audit[table_start:table_end]

        self.assertEqual(6, len(direct))
        self.assertEqual(54, len(locked))
        self.assertTrue(set(direct).issubset(set(locked)))
        table_pins = re.findall(r"`([A-Za-z0-9][A-Za-z0-9._-]*==[0-9][^`]*)`", audit_table)
        self.assertEqual(set(locked), set(table_pins))
        self.assertEqual(len(locked), len(table_pins))
        for pin in locked:
            with self.subTest(pin=pin):
                self.assertEqual(1, audit_table.count(f"`{pin}`"))

    def test_public_documents_agree_on_final_mit_and_holder(self):
        for path in PUBLIC_DOCUMENTS:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn("MIT License", text)
                self.assertIn("PromptGraph Lab.", text)
                self.assertNotIn("remain unresolved", text)
                self.assertNotIn("reconfirmed before the public repository", text)

    def test_notice_file_decision_matches_source_only_install_model(self):
        audit = RELEASE_PROCESS.read_text(encoding="utf-8")
        setup = SETUP.read_text(encoding="utf-8")
        self.assertIn("pip install --no-cache-dir --only-binary=:all: -r requirements.txt", setup)
        self.assertIn(
            "No `NOTICE` or `THIRD_PARTY_NOTICES.md` is required",
            audit,
        )
        self.assertFalse((ROOT / "NOTICE").exists())
        self.assertFalse((ROOT / "THIRD_PARTY_NOTICES.md").exists())

    def test_content_policy_and_downstream_boundaries_are_explicit(self):
        audit = RELEASE_PROCESS.read_text(encoding="utf-8")
        normalized_audit = " ".join(audit.split())
        tracked_workflows = subprocess.run(
            ["git", "ls-files", "workflows"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertEqual(["workflows/README.md"], tracked_workflows)
        for anchor in (
            "dummy_data/dummy_*.txt",
            "tests/fixtures/release/*.json",
            "No `workflows/*.json` files are tracked",
            "public-tree exposure gate",
            "clean-repository bootstrap gate",
            "archive gate",
            "release-candidate QA gate",
            "Third-party content keeps its own license",
            "User-provided or externally derived content",
            "Future workflow sample inclusion belongs to the public-tree provenance review",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, normalized_audit)

    def test_user_guide_does_not_assign_workflow_rights(self):
        guide = (ROOT / "docs" / "user-guide.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "workflows, and Global Libraries remain user-owned data",
            guide,
        )
        self.assertIn(
            "future workflow sample inclusion requires a separate provenance review",
            " ".join(guide.split()),
        )


if __name__ == "__main__":
    unittest.main()
