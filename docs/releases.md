# Release Versioning

`vplay` changes version whenever a public installable artifact changes.

Use a new version for:

- New user-facing features.
- Bug fixes in a shipped binary.
- Packaging fixes that affect Homebrew or portable downloads.
- Changes to default behavior, settings, module loading, or update handling.

Do not reuse a public release tag for a different binary. If a beta needs a fix, publish the next beta build, such as `1.1 beta 2`, instead of replacing `1.1 beta`.

Homebrew `revision` is reserved for formula-only fixes where the app binary and displayed app version do not change. If `vplay --version` should read differently, bump the app version instead.
