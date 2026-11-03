# Credentials and private state

Keep provider credentials in approved secret storage or ignored local environment
files. Never commit OAuth token files, private roster/draft snapshots, local MCP
client configuration, or real league identifiers in fixtures. Use clearly named
synthetic placeholders and example identifiers.

GitHub Actions scans commits with a pinned Gitleaks release. Findings are suppressed
from CI logs; inspect locally with full redaction. The scanner does not prove that
arbitrary private information is absent, so review fixtures and documentation too.

If a credential is committed, its owner must revoke or rotate it with the provider.
Removing a file or rewriting Git history does not revoke a credential. Coordinate
any history cleanup with collaborators and GitHub Support where cached commits,
pull-request refs, forks, or other copies remain. Do not publish suspected secrets
in issues, PRs, logs or scanner reports.
