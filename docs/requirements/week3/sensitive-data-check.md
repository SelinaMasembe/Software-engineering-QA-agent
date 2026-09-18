# Sensitive Data Check

## Purpose

The repository includes an automated check that helps prevent secrets and sensitive data from being committed.

The check detects:

- API keys and access tokens
- Private key blocks
- Passwords in URLs
- Hardcoded passwords and secrets
- Uganda phone numbers and national IDs
- Payment card numbers
- Sensitive filenames such as `.env`, `.log`, `.pem`, `.key`, and database files

## Enable the Check

Each group member must run these commands once from the repository root:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/precommit
```

How It Works
When a member creates a normal commit, Git automatically runs:

```bash
.githooks/precommit
```

The hook runs:

```bash
check_sensitive.py
```

The scanner checks staged files only.

Manual Checks
Scan all tracked files:

```bash
python3 check_sensitive.py --all
```

Scan staged files:

```bash
python3 check_sensitive.py
```

Results
Exit code 0 means the scan passed.

Exit code 1 means possible sensitive data was found and the commit is blocked.

The scanner displays the file, line number, and finding while redacting the detected value.

Handling Findings
Remove the real secret or sensitive data.
Load credentials from environment variables instead.
Remove sensitive logs, keys, or environment files from the commit.
Run the scanner again.
Synthetic values such as test-key and test-key-never-log are treated as test placeholders.

False positives may be suppressed with:

```bash
pragma: allowlist secret
```

Use this only when the value is definitely safe and synthetic.

Important Note
A member can bypass the hook with:

```bash
git commit --no-verify
```

This should not be used during normal development because it disables the security check.