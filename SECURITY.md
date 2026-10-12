# Security

Found a vulnerability? Please don't open a public issue. Use GitHub's
"Report a vulnerability" button on the Security tab of this repository.

Never commit `.env`, `*.pem`, API keys or databases. A pre-commit hook blocks
the common cases; enable it after cloning:

```bash
git config core.hooksPath .githooks
```
