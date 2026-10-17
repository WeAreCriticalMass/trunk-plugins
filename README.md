# trunk-plugins

Trunk configuration shared across the Critical Mass fleet.

Trunk merges plugin sources serially in the order a repository lists them, and a
later source may override almost any configuration an earlier one sets. So this
repository is listed _after_ `trunk-io/plugins`, and holds only the places where
the fleet deliberately differs from upstream defaults.

## Adopting it

Run Alidade's `fleet-tooling/scripts/adopt_trunk_plugins.py --write`. It adds
this repository as a second entry in `plugins.sources`, after the upstream one,
pinned to the release named in Alidade's `fleet-toolchain.v1.json`, and it
repins a checkout still on the moving `v1` tag. The result looks like this,
with each `ref` an immutable release tag that Renovate moves:

```yaml
plugins:
  sources:
    - id: trunk
      ref: vX.Y.Z
      uri: https://github.com/trunk-io/plugins
    - id: critical-mass
      ref: vX.Y.Z
      uri: https://github.com/WeAreCriticalMass/trunk-plugins
```

Do not write `ref: v1`. It is a moving tag that names different plugin code
on different days, and Renovate has no release to propose against it. Eighteen
checkouts copied it from an earlier version of this example.

Order is load-bearing. Listed first, upstream would win and this repository would
have no effect while appearing to be adopted.

Verify with `trunk print-config`, which prints the merged result — that is the
cheap way to confirm an override landed, rather than inferring it from behaviour.

## What is here, and why

**grype uses one shared vulnerability database.** See the comment in
`plugin.yaml`. Upstream scopes its cache per repository, which duplicated a
1.9 GB database 61 times on the shared runner.

**pinact runs with double-dash flags.** Upstream's wrapper still builds
`pinact run -format sarif`, which pinact v5 rejects, so every pull request that
touched a workflow failed changed-file linting in repositories on pinact@5. The
override runs upstream's own wrapper with only its flags adjusted (pinact v4
accepts them too), so the fleet can stay on current pinact. Remove it once an
upstream release contains trunk-io/plugins#1180.

**oxipng fetches the build for the runner's CPU.** Upstream's single macOS
download is the x86_64 binary, which cannot start on an Apple Silicon runner
without Rosetta ("Bad CPU type in executable"), so any pull request that
changed a PNG failed changed-file linting. The override maps macOS and Linux
by CPU. Remove it once upstream selects the macOS asset by CPU.

**oxlint lints and Prettier formats, without oxfmt.** Upstream v1.11.0 gave
oxlint a format command running oxfmt at a different width from Prettier, and
the two rewrote each other's output. The override disables the oxfmt command
and, from v1.4.0 (unreleased), replaces upstream's `tools: [oxfmt]` with
`[oxlint]`, so a repository that enables oxlint no longer downloads a
formatter nothing runs. (`tools: []` does not work: Trunk keeps upstream's.)

**Ruff formats Python (v1.4.0, unreleased).** The fleet uses one formatter per
language, and for Python that is Ruff, in place of black. Upstream ships Ruff's
format command disabled; the override switches it on. Trunk merges commands on
their `[name, version, platforms]` tuple rather than replacing the list, so only
the format command is named, and upstream's lint commands, with their parser,
are left untouched. A repository adopting this release can drop black from
`lint.enabled`. Ruff's formatter does not sort imports, so keep isort unless the
repository's Ruff configuration selects the import rules (`I`); with them,
import order is reported as a Ruff lint finding, which Ruff's own fix
(`ruff check --select I --fix`) resolves.

**trufflehog reports unverified secrets (v1.5.0, unreleased).** Upstream runs
trufflehog with `--only-verified`, which reports a secret only when trufflehog
can log in with it, so a private key, a revoked or test credential, or a token
for an internal service passed silently. The fleet keeps one secret scanner,
trufflehog in place of gitleaks, so the override runs it with
`--results=verified,unverified,unknown` instead and reports those too. Only
the command's `run` is restated: Trunk merges it into upstream's command, whose
parser, a script in upstream's own directory, stays as it is. Each trufflehog
release checked, from 3.90.13 to the fleet's 3.99.0, accepts the flag.
trufflehog-git, the opt-in history scan, keeps upstream's verified-only
command. Once this release is out, Alidade's Trunk profiles set
`trufflehogReportsUnverified`, and the fleet render then retires gitleaks
wherever trufflehog is rendered.

## Releases

Repositories pin an immutable tag (`v1.1.0`, …), not the original `v1`, so
Renovate's Trunk manager can propose each release like any other dependency.
Tags are never moved.

## What does not belong here

Anything a single repository needs. This file is read by every repository that
adopts it, so a rule that suits one of them is a rule the rest have to work
around.
