"""Tests for the fleet Trunk plugin's overrides.

The pinact override replaces upstream's command with a one-line Python shim
that loads upstream's own wrapper and rewrites only its single-dash long
flags. A shim nobody runs is a shim nobody knows is broken, so these execute
it against a stand-in for upstream's ``pinact_run.py``. Standard library only.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess  # nosec B404 -- runs the shim under test with a fixed argv.
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = (ROOT / "plugin.yaml").read_text(encoding="utf-8")

# A stand-in for upstream's linters/pinact/pinact_run.py: the same two names the
# shim relies on, build_pinact_args(mode) and main(), and main reports the
# arguments it would hand pinact so the test can see what the shim produced.
UPSTREAM_WRAPPER = """
import json, sys

def build_pinact_args(mode):
    return ["run", "-format", "sarif", "-u", "--check", mode]

def main():
    print(json.dumps({"args": build_pinact_args("lint"), "argv": sys.argv[1:]}))
    return 0
"""


def pinact_runs() -> list[str]:
    """The `run:` value of each pinact command, as Trunk would see it."""
    section = PLUGIN.split("    - name: pinact\n", 1)[1].split("\ntools:", 1)[0]
    return [match.strip() for match in re.findall(r"run: >-\n\s+(.+)\n", section)]


def run_shim(run: str, wrapper: Path, target: str) -> dict:
    argv = shlex.split(
        run.replace("${plugin}/linters/pinact/pinact_run.py", str(wrapper)).replace(
            "${target}", target
        )
    )
    argv[0] = sys.executable
    result = subprocess.run(  # nosec B603 -- argv built from plugin.yaml.
        argv, capture_output=True, text=True, check=True, timeout=30
    )
    return json.loads(result.stdout)


class PinactShimTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.wrapper = Path(directory.name) / "pinact_run.py"
        self.wrapper.write_text(UPSTREAM_WRAPPER, encoding="utf-8")

    def test_both_commands_share_one_shim(self) -> None:
        runs = pinact_runs()
        self.assertEqual(len(runs), 2)
        lint, upgrade = (run.split(" ${plugin}")[0] for run in runs)
        self.assertEqual(lint, upgrade)

    def test_single_dash_long_flags_become_double_dash(self) -> None:
        out = run_shim(pinact_runs()[0], self.wrapper, ".github/workflows/ci.yml")
        # `-format` is the flag pinact v5 rejects; `-u` is a real short flag
        # and `--check` is already long, so both pass through untouched.
        self.assertEqual(
            out["args"], ["run", "--format", "sarif", "-u", "--check", "lint"]
        )

    def test_upstream_arguments_reach_the_wrapper(self) -> None:
        out = run_shim(pinact_runs()[1], self.wrapper, "a.yml")
        self.assertEqual(out["argv"], ["--upgrade", "a.yml"])

    def test_upgrade_stays_opt_in(self) -> None:
        upgrade = PLUGIN.split("        - name: upgrade\n", 1)[1].split("\ntools:", 1)[
            0
        ]
        self.assertIn("enabled: false", upgrade)


class GrypeOverrideTests(unittest.TestCase):
    def test_one_database_per_machine_and_path_restated(self) -> None:
        grype = PLUGIN.split("    - name: grype\n", 1)[1].split(
            "    - name: pinact", 1
        )[0]
        self.assertIn("value: ${env.HOME}/.cache/grype-shared/db", grype)
        # Trunk replaces sequences, so dropping PATH would leave grype unrunnable.
        self.assertIn('list: ["${linter}", "${env.PATH}"]', grype)

    def test_the_cli_floor_covers_env_home_expansion(self) -> None:
        self.assertRegex(PLUGIN, r'required_trunk_version: ">=1\.22\.2"')


def oxipng_downloads() -> list[dict[str, str]]:
    """The oxipng download entries, each as a flat key/value mapping."""
    section = PLUGIN.split("  downloads:\n    - name: oxipng\n", 1)[1]
    section = section.split("\n\n", 1)[0]
    entries: list[dict[str, str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            entries.append({})
            stripped = stripped[2:]
        if ":" in stripped and entries:
            key, value = stripped.split(":", 1)
            entries[-1][key.strip()] = value.strip().strip('"')
    return entries


class OxipngDownloadTests(unittest.TestCase):
    """Each platform must fetch a binary built for its own CPU."""

    def url_for(self, os_name: str, cpu: str) -> str:
        matches = [
            entry["url"]
            for entry in oxipng_downloads()
            if entry.get("os") == os_name and entry.get("cpu", cpu) == cpu
        ]
        self.assertTrue(matches, f"no oxipng download for {os_name}/{cpu}")
        return matches[0]

    def test_apple_silicon_fetches_the_arm64_build(self) -> None:
        # The x86_64 build cannot start on an Apple Silicon runner without
        # Rosetta: "execve failed: Bad CPU type in executable".
        self.assertIn("aarch64-apple-darwin", self.url_for("macos", "arm_64"))

    def test_intel_macs_keep_the_x86_64_build(self) -> None:
        self.assertIn("x86_64-apple-darwin", self.url_for("macos", "x86_64"))

    def test_linux_is_mapped_per_cpu(self) -> None:
        self.assertIn("x86_64-unknown-linux-musl", self.url_for("linux", "x86_64"))
        self.assertIn("aarch64-unknown-linux-musl", self.url_for("linux", "arm_64"))

    def test_every_macos_entry_names_its_cpu(self) -> None:
        # An entry without `cpu` matches every CPU, which is how upstream's
        # single macOS entry handed Apple Silicon the Intel binary.
        for entry in oxipng_downloads():
            if entry.get("os") == "macos":
                self.assertIn("cpu", entry)


if __name__ == "__main__":
    unittest.main()


class OxlintFormatterTests(unittest.TestCase):
    """Prettier is the fleet JavaScript formatter; oxlint only lints."""

    def section(self) -> str:
        return PLUGIN.split("    - name: oxlint\n", 1)[1].split("\ntools:", 1)[0]

    def test_the_oxfmt_command_is_disabled(self) -> None:
        fmt = self.section().split("        - name: format\n", 1)[1]
        self.assertIn("run: oxfmt --write ${target}", fmt)
        self.assertIn("formatter: true", fmt)
        self.assertIn("enabled: false", fmt)

    def test_the_lint_command_is_restated_and_still_enabled(self) -> None:
        lint = (
            self.section()
            .split("        - name: lint\n", 1)[1]
            .split("        - name: format\n", 1)[0]
        )
        self.assertIn("run: oxlint --format sarif ${target}", lint)
        self.assertNotIn("enabled: false", lint)
