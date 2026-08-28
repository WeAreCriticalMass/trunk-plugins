# Security Policy

## Scope

This repository is public, and it is shared configuration rather than an
application: `plugin.yaml` and the linter definitions beside it are merged into
every Critical Mass repository that lists this source. Trunk merges plugin
sources serially, and a later source may override almost anything an earlier one
sets, so a change here can silently alter what is checked — or stop being
checked — across the fleet.

Security issues are therefore treated seriously where they affect:

- the integrity of the merged configuration a consuming repository receives
- linter or tool definitions that could execute unexpected code during a check
- pinned tool versions and the sources they are fetched from
- any configuration that would weaken or disable a control in a consuming
  repository without that being visible in its own tree

## Reporting

Do not open a public issue for a security concern. Use GitHub's private
vulnerability reporting for this repository. If that facility is unavailable,
contact an authorised Critical Mass representative through an already
established private channel.

Include only the minimum needed to reproduce and assess the issue:

- the affected commit or released version
- which consuming repository or check is affected, if known
- clear reproduction steps
- expected behaviour against actual behaviour

## Handling expectations

- Do not publish details before the issue is understood and triaged.
- Do not access data or systems beyond what is needed to demonstrate the
  finding.
- Because this configuration is consumed by other repositories, a fix may need
  to land here and be taken up downstream before details are made public.
