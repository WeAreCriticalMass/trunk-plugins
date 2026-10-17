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


def definition(name: str) -> str:
    """One `lint.definitions` entry of plugin.yaml, up to the next entry.

    The next entry starts at its own comment block, if it has one, so that
    comment is not counted as part of this entry.
    """
    section = PLUGIN.split(f"\n    - name: {name}\n", 1)[1]
    next_entry = r"\n\n    #|\n    - name: |\ntools:"
    return re.split(next_entry, section, maxsplit=1)[0]


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
    section = definition("pinact")
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
        upgrade = definition("pinact").split("        - name: upgrade\n", 1)[1]
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


class OxlintFormatterTests(unittest.TestCase):
    """Prettier is the fleet JavaScript formatter; oxlint only lints."""

    def section(self) -> str:
        return definition("oxlint")

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

    def test_oxfmt_is_no_longer_a_required_tool(self) -> None:
        # Upstream declares `tools: [oxfmt]`; with the formatter off nothing
        # runs it. The restated sequence names oxlint's own tool and is not
        # empty: Trunk treats `tools: []` as absent and keeps upstream's oxfmt.
        self.assertRegex(self.section(), r"(?m)^      tools: \[oxlint\]$")
        self.assertNotIn("tools: [oxfmt]", self.section())


class RuffFormatterTests(unittest.TestCase):
    """Ruff formats Python in place of black; its formatter does not sort imports."""

    def section(self) -> str:
        return definition("ruff")

    def test_the_format_command_is_enabled(self) -> None:
        commands = self.section().split("      commands:\n", 1)[1]
        self.assertEqual(
            [line.strip() for line in commands.strip().splitlines()],
            ["- name: format", "enabled: true"],
        )

    def test_the_lint_commands_are_left_to_upstream(self) -> None:
        # Trunk merges commands on [name, version, platforms]. Restating the
        # lint commands would also restate their `${cwd}/ruff_to_sarif.py`
        # parser, which could then resolve against this repository, where the
        # script does not exist.
        self.assertNotIn("name: lint", self.section())
        configuration = [
            line for line in PLUGIN.splitlines() if not line.lstrip().startswith("#")
        ]
        self.assertFalse([line for line in configuration if "ruff_to_sarif" in line])


class TrufflehogResultsTests(unittest.TestCase):
    """trufflehog reports unverified secrets too, through upstream's parser."""

    def test_trufflehog_git_is_left_to_upstream(self) -> None:
        self.assertNotIn("- name: trufflehog-git", PLUGIN)


    def section(self) -> str:
        return definition("trufflehog")

    def configuration(self) -> list[str]:
        return [
            line
            for line in self.section().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def run_line(self) -> str:
        # The folded (`>-`) scalar, joined as YAML joins it: with spaces.
        lines = self.section().split("          run: >-\n", 1)[1].splitlines()
        folded = [line.strip() for line in lines if line.startswith(" " * 12)]
        return " ".join(folded)

    def test_unverified_and_unknown_results_are_reported(self) -> None:
        argv = self.run_line().split()
        self.assertEqual(argv[:2], ["trufflehog", "filesystem"])
        self.assertIn("--results=verified,unverified,unknown", argv)
        self.assertNotIn("--only-verified", argv)

    def test_upstream_output_and_failure_flags_are_kept(self) -> None:
        # The parser reads JSON lines; --fail exits 183 on a finding, which
        # upstream lists among its success codes.
        argv = self.run_line().split()
        for flag in ("--json", "--fail", "--no-update"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[-1], "${target}")

    def test_only_run_is_named_on_upstream_lint_command(self) -> None:
        # Trunk merges commands on [name, version, platforms]: no version or
        # platforms, so the override lands on upstream's command.
        self.assertEqual(
            [line.strip() for line in self.configuration()],
            [
                "commands:",
                "- name: lint",
                "run: >-",
                "trufflehog filesystem --json --fail",
                "--results=verified,unverified,unknown --no-update ${target}",
            ],
        )

    def test_upstream_parser_is_not_restated(self) -> None:
        # Upstream's parser runs a script beside upstream's plugin.yaml.
        # A copy here could resolve against this repository instead.
        for line in self.configuration():
            for word in ("parser", "_to_sarif", "${plugin}", "${cwd}"):
                self.assertNotIn(word, line)

    def test_the_override_and_its_comment_fit_in_80_columns(self) -> None:
        start = PLUGIN.index("    # trufflehog reports every secret")
        text = PLUGIN[start:].split("\n    - name: trufflehog\n", 1)[0]
        for line in [*text.splitlines(), *self.section().splitlines()]:
            self.assertLessEqual(len(line), 80, line)


if __name__ == "__main__":
    unittest.main()
