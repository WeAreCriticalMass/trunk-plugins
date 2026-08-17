# trunk-plugins

Trunk configuration shared across the Critical Mass fleet.

Trunk merges plugin sources serially in the order a repository lists them, and a
later source may override almost any configuration an earlier one sets. So this
repository is listed *after* `trunk-io/plugins`, and holds only the places where
the fleet deliberately differs from upstream defaults.

## Adopting it

Add a second entry to `plugins.sources` in a repository's `.trunk/trunk.yaml`,
after the upstream one:

```yaml
plugins:
  sources:
    - id: trunk
      ref: v1.11.0
      uri: https://github.com/trunk-io/plugins
    - id: critical-mass
      ref: v1
      uri: https://github.com/WeAreCriticalMass/trunk-plugins
```

Order is load-bearing. Listed first, upstream would win and this repository would
have no effect while appearing to be adopted.

Verify with `trunk print-config`, which prints the merged result — that is the
cheap way to confirm an override landed, rather than inferring it from behaviour.

## What is here, and why

**grype uses one shared vulnerability database.** See the comment in
`plugin.yaml`. Upstream scopes its cache per repository, which duplicated a
1.9 GB database 61 times on the shared runner.

## What does not belong here

Anything a single repository needs. This file is read by every repository that
adopts it, so a rule that suits one of them is a rule the rest have to work
around.
