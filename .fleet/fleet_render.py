#!/usr/bin/env python3
"""Render and check the files a repository receives from Alidade's templates.

This is the pull half of fleet roll-out. Central mutation (`apply-fleet-*.sh`)
is retired because overwriting repositories from one place produced drift
nobody owned. Instead each repository pins a template release and renders it
itself:

* `.fleet/lock.json` records the inputs a repository renders with, the
  template release it rendered, and a sha256 for every managed file.
* `.github/workflows/fleet-render.yml` carries the pin, as the SHA-pinned
  `uses:` line of Alidade's `fleet-render` action, because GitHub only accepts
  a literal ref there. Renovate bumps that line, one pull request per release;
  the workflow runs this script from the pinned release and commits the result
  to the same pull request.
* `check` runs in the repository's required gate. A managed file that differs
  from the hash recorded at render time was edited by hand, and the edit would
  be overwritten by the next release, so the gate fails now rather than later.

The repository carries a copy of this file as `.fleet/fleet_render.py` (itself
a managed file), so the check needs nothing but `python3`.

Standard library only, on purpose.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

LOCK = ".fleet/lock.json"
RENDER_WORKFLOW = ".github/workflows/fleet-render.yml"
PLACEHOLDER = re.compile(r"(?<!\$)\{\{([A-Z][A-Z0-9_]*)\}\}")
# `{{NAME?}}` alone on a line is an optional block: its value is inserted as
# lines, and when the value is empty the line and the blank line after it go.
OPTIONAL_BLOCK = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\?\}\}")
# The pin in the render workflow: `uses: WeAreCriticalMass/Alidade/...@<sha> # <tag>`.
PIN = re.compile(
    r"uses: WeAreCriticalMass/Alidade/fleet-tooling/actions/fleet-render@"
    r"(?P<sha>[0-9a-f]{40}) # (?P<tag>\S+)"
)


def substitute(text: str, inputs: dict[str, str], name: str = "template") -> str:
    """Fill `{{NAME}}` placeholders and `{{NAME?}}` optional blocks."""

    def need(key: str) -> str:
        if key not in inputs:
            raise KeyError(f"{name}: no input for {{{{{key}}}}}")
        return inputs[key]

    out: list[str] = []
    skip_blank = False
    for line in text.splitlines(keepends=True):
        if skip_blank:
            skip_blank = False
            if not line.strip():
                continue
        block = OPTIONAL_BLOCK.fullmatch(line.strip())
        if block:
            value = need(block[1])
            if value:
                out.append(value.rstrip("\n") + "\n")
            else:
                skip_blank = True
            continue
        out.append(PLACEHOLDER.sub(lambda match: need(match[1]), line))
    return "".join(out)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_lock(repo: Path) -> dict:
    return json.loads((repo / LOCK).read_text(encoding="utf-8"))


def write_lock(repo: Path, lock: dict) -> None:
    path = repo / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def read_pin(repo: Path) -> dict[str, str] | None:
    workflow = repo / RENDER_WORKFLOW
    if not workflow.is_file():
        return None
    match = PIN.search(workflow.read_text(encoding="utf-8"))
    return {"sha": match["sha"], "tag": match["tag"]} if match else None


def render(repo: Path, source: Path) -> list[str]:
    """Render every managed file from `source` (Alidade's fleet-tooling
    directory at the pinned release). Returns the paths that changed."""
    lock = read_lock(repo)
    pin = read_pin(repo)
    if pin is None:
        # First render: the workflow carrying the pin does not exist yet, so
        # the pin comes from the lock's inputs (written at adoption).
        seeded = PIN.search(
            "uses: WeAreCriticalMass/Alidade/fleet-tooling/actions/fleet-render@"
            + lock.get("inputs", {}).get("FLEET_RENDER_PIN", "")
        )
        if seeded:
            pin = {"sha": seeded["sha"], "tag": seeded["tag"]}
    if pin:
        # The render workflow's `uses:` line is the pin Renovate moves; the
        # lock follows it.
        lock["version"] = pin["tag"]
        lock["commit"] = pin["sha"]
        lock.setdefault("inputs", {})[
            "FLEET_RENDER_PIN"
        ] = f"{pin['sha']} # {pin['tag']}"
    inputs = dict(lock.get("inputs", {}))
    changed: list[str] = []
    for relative, entry in sorted(lock["files"].items()):
        template = source / entry["template"]
        raw = template.read_text(encoding="utf-8")
        text = (
            substitute(raw, inputs, entry["template"])
            if template.suffix == ".tpl"
            else raw
        )
        data = text.encode("utf-8")
        target = repo / relative
        if not target.is_file() or target.read_bytes() != data:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if template.stat().st_mode & 0o111:
                target.chmod(0o755)
            changed.append(relative)
        entry["sha256"] = digest(data)
    write_lock(repo, lock)
    return changed


def check(repo: Path) -> list[str]:
    """Problems with the managed files, as messages. Empty means clean."""
    lock_path = repo / LOCK
    if not lock_path.is_file():
        return [f"{LOCK} is missing"]
    lock = read_lock(repo)
    problems: list[str] = []
    pin = read_pin(repo)
    if pin and lock.get("commit") != pin["sha"]:
        problems.append(
            f"{RENDER_WORKFLOW} pins {pin['tag']} but {LOCK} was rendered from "
            f"{lock.get('version')}: the render step has not run for this pin"
        )
    for relative, entry in sorted(lock.get("files", {}).items()):
        target = repo / relative
        if not target.is_file():
            problems.append(f"{relative} is managed by {LOCK} but missing")
        elif digest(target.read_bytes()) != entry.get("sha256"):
            problems.append(
                f"{relative} differs from the fleet template it was rendered "
                f"from ({entry['template']} at {lock.get('version')}). Change "
                "the template in Alidade, or the inputs in .fleet/lock.json, "
                "not the rendered file"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    render_cmd = sub.add_parser("render", help="render managed files")
    render_cmd.add_argument("--repo", type=Path, default=Path.cwd())
    render_cmd.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Alidade's fleet-tooling directory at the pinned release",
    )
    check_cmd = sub.add_parser("check", help="verify managed files")
    check_cmd.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    if args.command == "render":
        changed = render(args.repo.resolve(), args.source.resolve())
        print("\n".join(changed) if changed else "managed files already current")
        return 0
    problems = check(args.repo.resolve())
    for problem in problems:
        print(f"fleet-managed: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("fleet-managed files match .fleet/lock.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
