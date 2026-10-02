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
chmod +x .githooks/pre-commit
```

Git only runs a hook whose file name matches the hook exactly, so the file
must be called `pre-commit` (with the hyphen). Until 2 October 2026 it was
named `precommit`, which Git silently ignored.

Confirm the hook is active without committing anything:

```bash
git hook run pre-commit
```

## How It Works

When a member creates a normal commit, Git automatically runs
`.githooks/pre-commit`, which runs `scripts/check_sensitive.py` on the staged
files only.

## Manual Checks

Scan all tracked files:

```bash
python3 scripts/check_sensitive.py --all
```

Scan staged files:

```bash
python3 scripts/check_sensitive.py
```

## Results

- Exit code 0 means the scan passed.
- Exit code 1 means possible sensitive data was found and the commit is blocked.

The scanner displays the file, line number, and finding while redacting the detected value.

## Handling Findings

1. Remove the real secret or sensitive data.
2. Load credentials from environment variables instead.
3. Remove sensitive logs, keys, or environment files from the commit.
4. Run the scanner again.

Synthetic values such as `test-key` and `test-key-never-log` are treated as test placeholders.

A false positive on a definitely synthetic value may be suppressed by adding
this comment to the line:

```text
pragma: allowlist secret
```

A whole file can be exempted by adding a glob to `.sensitive-scan-ignore`.
The repository currently has no exemptions; add one only with a written
reason and team agreement.

## Fixture Decision: No Committed `.log` Files

The Week 3 retrieval corpus originally used
`tests/fixtures/member2/corpus/logs/test_run_2026_09_15.log`. The scanner
blocks `*.log` because real sandbox and model runs can capture keys and
prompts, so the file was replaced with a synthetic
`tests/fixtures/member2/corpus/logs/test_run_2026_09_15.txt`. The retrieval
loader classifies anything under a `logs/` folder as a log, whatever its
extension (`src/rag/retrieval.py`), so the evaluation lost nothing.

A parallel branch later restored the `.log` together with a
`.sensitive-scan-ignore` exemption, and the merge kept both files. That put
two copies of the same incident in the corpus and broke
`tests/integration/test_rag_pipeline.py::ContractTests::test_manifest_counts_documents_and_chunks`.
On 2 October 2026 the `.log` and the exemption were removed. No test or
evaluation case referenced the `.log`, and all fifteen RAG evaluation cases
still produce their expected results.

## Important Note

A member can bypass the hook with:

```bash
git commit --no-verify
```

This should not be used during normal development because it disables the security check.
