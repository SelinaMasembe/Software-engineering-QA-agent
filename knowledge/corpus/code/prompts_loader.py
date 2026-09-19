"""
Prompt loader for the Software-Engineering QA Agent.

Loads a versioned prompt template from docs/prompts/ and returns the
rendered system prompt text for a given prompt id and version. Every
model call in the agent goes through load_prompt() rather than
embedding prompt text directly in code, so every trace can be tied
back to exactly which prompt version produced it (see the AI
Engineering Design Notes, "Context Bundle" section).

Expected file layout:
    docs/prompts/<prompt_id>/<version>.md

Example:
    docs/prompts/propose_action/v1.0.md
    docs/prompts/propose_action/v1.1.md
"""

from dataclasses import dataclass
from pathlib import Path

# repo_root/src/prompts/loader.py -> repo_root/docs/prompts
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "prompts"


class PromptNotFoundError(Exception):
    """Raised when a requested prompt id or version does not exist on disk."""


@dataclass(frozen=True)
class PromptVersion:
    prompt_id: str
    version: str
    text: str


def load_prompt(prompt_id: str, version: str) -> PromptVersion:
    """
    Load one specific version of a prompt.

    Example:
        prompt = load_prompt("propose_action", "v1.1")
        prompt.text  # -> the full system prompt string
    """
    path = PROMPTS_DIR / prompt_id / f"{version}.md"
    if not path.exists():
        raise PromptNotFoundError(
            f"No prompt found for id={prompt_id!r} version={version!r} "
            f"(expected {path})"
        )
    return PromptVersion(
        prompt_id=prompt_id,
        version=version,
        text=path.read_text(encoding="utf-8"),
    )


def latest_version(prompt_id: str) -> str:
    """
    Return the highest version string available for a prompt id.

    This currently just sorts the filenames present on disk (v1.0,
    v1.1, v1.10, ...). Once the version history table in the Prompt
    Specification grows past simple lexical ordering, replace this
    with an explicit CURRENT pointer instead of inferring it from
    the directory listing.
    """
    prompt_dir = PROMPTS_DIR / prompt_id
    if not prompt_dir.exists():
        raise PromptNotFoundError(
            f"No prompts directory for id={prompt_id!r} (expected {prompt_dir})"
        )
    versions = sorted(p.stem for p in prompt_dir.glob("*.md"))
    if not versions:
        raise PromptNotFoundError(
            f"No versioned prompt files found in {prompt_dir}"
        )
    return versions[-1]


def load_latest(prompt_id: str) -> PromptVersion:
    """Convenience wrapper: load the highest version currently on disk."""
    return load_prompt(prompt_id, latest_version(prompt_id))


if __name__ == "__main__":
    # Quick manual check: python src/prompts/loader.py
    prompt = load_latest("propose_action")
    print(f"Loaded {prompt.prompt_id} {prompt.version} "
          f"({len(prompt.text)} characters)")