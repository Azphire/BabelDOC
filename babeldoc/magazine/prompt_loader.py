"""Prompt template loading with a per-run provenance record.

Every prompt this project sends to a language or vision model lives in
``prompts/`` as its own file. Nothing composes prompt text in code, so a change
to what a model is asked is reviewable as a diff and identifiable afterwards by
hash: loading a template appends its SHA-256 to ``prompts.manifest.json`` in the
working directory, next to the configuration manifest the classifier writes.

A template variable is ``{name}`` with a lower case identifier between the
braces. A brace that opens anything else -- the JSON object a template shows to
fix the answer shape, for instance -- is left alone, so a template can state the
exact output it demands without escaping.

Rendering is strict in both directions. A variable the template declares and the
caller does not supply is an error, and so is a value the caller supplies for a
variable the template does not declare: the second is how a renamed variable
would otherwise drop a whole section of a prompt in silence. The rendered text
is scanned once more afterwards, so a substituted value that itself looks like a
template variable is refused rather than sent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"

PROMPT_SUFFIX = ".md"

MANIFEST_NAME = "prompts.manifest.json"

# A template variable: a lower case identifier, alone between braces.
_VARIABLE = re.compile(r"\{([a-z][a-z0-9_]*)\}")

# A prompt is named by its stem, never by a path: a name that could climb out of
# the prompt directory is rejected before it reaches the filesystem.
_PROMPT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class PromptError(ValueError):
    """Raised when a prompt template is missing, malformed or under-supplied."""


@dataclass(frozen=True)
class Prompt:
    """One rendered prompt, carrying the identity of the file behind it."""

    name: str
    path: Path
    digest: str
    text: str
    variables: tuple[str, ...]


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_path(name: str, directory: Path | None = None) -> Path:
    if not _PROMPT_NAME.match(name):
        raise PromptError(
            f"illegal prompt name {name!r}; a name is a lower case identifier "
            f"and never a path"
        )
    return (PROMPT_DIR if directory is None else Path(directory)) / (
        name + PROMPT_SUFFIX
    )


def template_variables(template: str) -> tuple[str, ...]:
    """Variable names the template declares, in first appearance order."""
    seen: list[str] = []
    for match in _VARIABLE.finditer(template):
        if match.group(1) not in seen:
            seen.append(match.group(1))
    return tuple(seen)


def render(template: str, variables: dict[str, str], source: str) -> str:
    """Substitute every declared variable, refusing any mismatch."""
    declared = set(template_variables(template))
    supplied = set(variables)
    missing = sorted(declared - supplied)
    if missing:
        raise PromptError(f"{source}: no value supplied for {missing}")
    unknown = sorted(supplied - declared)
    if unknown:
        raise PromptError(f"{source}: template declares no variable {unknown}")

    text = template
    for name, value in variables.items():
        if not isinstance(value, str):
            raise PromptError(f"{source}: value for {name!r} is not a string")
        text = text.replace("{" + name + "}", value)

    left = template_variables(text)
    if left:
        raise PromptError(
            f"{source}: unreplaced variables remain after rendering: {list(left)}"
        )
    return text


def record_prompt_manifest(working_dir: Path | str, prompts: list[Prompt]) -> Path:
    """Append the SHA-256 of each prompt to the working directory manifest.

    Keyed by repository relative path, so a second load of the same template
    updates its entry rather than adding one.
    """
    manifest_path = Path(working_dir) / MANIFEST_NAME
    entries: dict[str, str] = {}
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as f:
            entries = json.load(f)
    for prompt in prompts:
        entries[manifest_key(prompt.path)] = prompt.digest
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, sort_keys=True)
    return manifest_path


def manifest_key(path: Path) -> str:
    """Repository relative posix path, the key a manifest entry is filed under."""
    root = PROMPT_DIR.parent
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


def load_prompt(
    name: str,
    variables: dict[str, str],
    working_dir: Path | str | None = None,
    directory: Path | None = None,
) -> Prompt:
    """Load ``prompts/<name>.md``, render it and record where it came from."""
    path = prompt_path(name, directory)
    if not path.is_file():
        raise PromptError(f"prompt template not found: {path}")
    template = path.read_text(encoding="utf-8")
    prompt = Prompt(
        name=name,
        path=path,
        digest=file_digest(path),
        text=render(template, variables, path.name),
        variables=template_variables(template),
    )
    if working_dir is not None:
        record_prompt_manifest(working_dir, [prompt])
    logger.debug("loaded prompt %s (%s)", name, prompt.digest[:12])
    return prompt
