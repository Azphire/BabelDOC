"""Corpus registry and manifest handling.

``corpus/registry.user.json`` is the sole authority for the semantic metadata
of the sample corpus and is hand edited by the corpus owner. ``corpus/
manifest.json`` is a machine rebuilt view of it: the semantic fields are copied
verbatim, the mechanical fields are measured from the sample files, and the
baseline block is filled in by ``tools/build_baseline.py``.

``corpus/page_labels.json`` is the second hand written file: the page type
ground truth the classifier is measured against. ``corpus/chain_labels.user.json``
is the third: the ground truth for whether an article runs across a given page
boundary. Both are read here and never written.

Nothing here interprets a publication: the module validates structure and
copies values, so adding a sample is a registry edit followed by a rebuild.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Collection
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
INPUT_DIR = ROOT / "examples" / "input"
REGISTRY_PATH = ROOT / "corpus" / "registry.user.json"
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
PAGE_LABELS_PATH = ROOT / "corpus" / "page_labels.json"
CHAIN_LABELS_PATH = ROOT / "corpus" / "chain_labels.user.json"

# How a boundary key joins the two page numbers it names.
BOUNDARY_SEPARATOR = "->"

# Keys a boundary entry may carry: the adjudication itself and the note the
# adjudicator left behind explaining it.
CHAIN_LABEL_KEYS: frozenset[str] = frozenset({"link", "note"})

# Prefix marking a top level key of a hand written truth file as documentation
# rather than as a sample: the adjudicator states the rule the file was written
# under beside the judgements made under it, and no sample file is named this
# way. Machines skip these keys; they exist for whoever reads or revises the
# adjudications next.
DOCUMENTATION_KEY_PREFIX = "_"

# Fields the registry owns. The manifest carries a verbatim copy of each, and
# any difference between the two is an error rather than a rebuild trigger.
SEMANTIC_FIELDS: tuple[str, ...] = (
    "publication",
    "magazine",
    "toc_pages",
    "corpus_role",
    "notes",
)

# Fields measured from the sample file, which the registry never states.
MECHANICAL_FIELDS: tuple[str, ...] = ("sha256", "pages")

# Closed vocabulary for the corpus_role list.
CORPUS_ROLES: frozenset[str] = frozenset({"translation_eval", "layout_generalization"})

# The role whose samples the agreement rate assertions are binding on. Every
# sample is measured and reported the same way; a sample outside this role
# carries no gate, because a distribution the thresholds were never tuned
# against would otherwise decide whether the tuned ones still hold. Its numbers
# are the baseline a later calibration for that distribution is judged from.
CONSTRAINED_ROLE = "layout_generalization"

# Marker a registry entry carries while its metadata is still unverified; a
# corpus holding one is not fit to build baselines from.
UNVERIFIED_MARKER = "TO-VERIFY"

# Read size for incremental hashing; a pure I/O buffer, not a tuning knob.
_HASH_CHUNK_BYTES = 1 << 20


class CorpusError(ValueError):
    """Raised when the registry cannot be turned into a manifest."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def page_count(path: Path) -> int:
    with pymupdf.open(path) as doc:
        return doc.page_count


def load_registry(path: Path = REGISTRY_PATH) -> list[dict]:
    """Read the registry and return its entries, unmodified."""
    with path.open(encoding="utf-8") as f:
        registry = json.load(f)
    entries = registry.get("entries")
    if not isinstance(entries, list):
        raise CorpusError(f"{path.name}: entries must be a list")
    return entries


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def registered_pdfs(input_dir: Path = INPUT_DIR) -> list[str]:
    """Every PDF present under the sample directory, as a relative path."""
    if not input_dir.is_dir():
        return []
    return sorted(
        pdf.relative_to(input_dir).as_posix() for pdf in input_dir.rglob("*.pdf")
    )


def validate_registry(entries: list[dict], input_dir: Path = INPUT_DIR) -> list[str]:
    """Check the registry against its schema and against the sample directory."""
    errors: list[str] = []
    if not entries:
        errors.append("registry: no entries")

    seen: set[str] = set()
    for position, entry in enumerate(entries):
        where = f"entries[{position}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: entry must be an object")
            continue
        rel = entry.get("file")
        if not isinstance(rel, str) or not rel:
            errors.append(f"{where}: file must be a non-empty string")
            continue
        where = rel
        if rel in seen:
            errors.append(f"{where}: duplicate entry")
            continue
        seen.add(rel)

        if UNVERIFIED_MARKER in json.dumps(entry, ensure_ascii=False):
            errors.append(f"{where}: still carries {UNVERIFIED_MARKER}")

        path = input_dir / rel
        if not path.exists():
            errors.append(f"{where}: registered but missing from {input_dir}")
            pages = None
        else:
            pages = page_count(path)

        missing = [field for field in SEMANTIC_FIELDS if field not in entry]
        if missing:
            errors.append(f"{where}: missing semantic field(s) {missing}")

        publication = entry.get("publication")
        if not isinstance(publication, str) or not publication:
            errors.append(f"{where}: publication must be a non-empty string")

        if not isinstance(entry.get("magazine"), bool):
            errors.append(f"{where}: magazine must be a boolean")

        notes = entry.get("notes")
        if not isinstance(notes, str) or not notes:
            errors.append(f"{where}: notes must be a non-empty string")

        roles = entry.get("corpus_role")
        if not isinstance(roles, list) or not roles:
            errors.append(f"{where}: corpus_role must be a non-empty list")
        else:
            unknown = sorted(set(roles) - CORPUS_ROLES)
            if unknown:
                errors.append(
                    f"{where}: unknown corpus_role {unknown}; "
                    f"allowed are {sorted(CORPUS_ROLES)}"
                )

        toc_pages = entry.get("toc_pages")
        if not isinstance(toc_pages, list):
            errors.append(f"{where}: toc_pages must be a list")
        else:
            bad = [
                value
                for value in toc_pages
                if not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
                or (pages is not None and value > pages)
            ]
            if bad:
                errors.append(
                    f"{where}: toc_pages {bad} outside the 1..{pages} file page order"
                )

    for rel in registered_pdfs(input_dir):
        if rel not in seen:
            errors.append(f"{rel}: present in {input_dir} but not registered")

    return errors


def build_manifest(
    entries: list[dict],
    previous: dict | None = None,
    input_dir: Path = INPUT_DIR,
) -> dict:
    """Rebuild the manifest from the registry, measuring the mechanical fields.

    A baseline block from ``previous`` is carried over only while the sample
    content hash is unchanged, so a replaced sample never keeps a stale
    baseline.
    """
    carried: dict[str, tuple[str | None, dict]] = {}
    for entry in (previous or {}).get("samples", []):
        if "baseline" in entry:
            carried[entry["file"]] = (entry.get("sha256"), entry["baseline"])

    samples: list[dict] = []
    for entry in entries:
        rel = entry["file"]
        path = input_dir / rel
        if not path.exists():
            raise CorpusError(f"{rel}: missing from {input_dir}")
        digest = sha256_file(path)
        sample: dict = {"file": rel, "sha256": digest, "pages": page_count(path)}
        for field in SEMANTIC_FIELDS:
            if field in entry:
                sample[field] = copy.deepcopy(entry[field])
        baseline = carried.get(rel)
        if baseline is not None and baseline[0] == digest:
            sample["baseline"] = copy.deepcopy(baseline[1])
        samples.append(sample)

    return {"version": (previous or {}).get("version", 1), "samples": samples}


def write_manifest(manifest: dict, path: Path = MANIFEST_PATH) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def validate_manifest(
    manifest: dict,
    entries: list[dict],
    input_dir: Path = INPUT_DIR,
    root: Path = ROOT,
) -> tuple[list[str], list[str]]:
    """Check the manifest against the registry and against the sample files."""
    errors: list[str] = []
    warnings: list[str] = []

    samples = manifest.get("samples")
    if not isinstance(samples, list):
        return ["manifest: samples must be a list"], warnings

    by_file = {entry["file"]: entry for entry in entries if isinstance(entry, dict)}
    seen: set[str] = set()

    for sample in samples:
        rel = sample.get("file")
        if not isinstance(rel, str) or not rel:
            errors.append("manifest: a sample has no file")
            continue
        seen.add(rel)
        entry = by_file.get(rel)
        if entry is None:
            errors.append(f"{rel}: in the manifest but not in the registry")
            continue

        for field in SEMANTIC_FIELDS:
            if sample.get(field) != entry.get(field):
                errors.append(
                    f"{rel}: {field} differs from the registry, "
                    f"manifest={sample.get(field)!r} registry={entry.get(field)!r}"
                )

        path = input_dir / rel
        if not path.exists():
            errors.append(f"{rel}: missing from {input_dir}")
            continue
        actual_hash = sha256_file(path)
        if actual_hash != sample.get("sha256"):
            errors.append(
                f"{rel}: sha256 mismatch, manifest={sample.get('sha256')} "
                f"actual={actual_hash}"
            )
        actual_pages = page_count(path)
        if actual_pages != sample.get("pages"):
            errors.append(
                f"{rel}: page count mismatch, manifest={sample.get('pages')} "
                f"actual={actual_pages}"
            )

        baseline = sample.get("baseline")
        if not baseline:
            warnings.append(f"{rel}: no baseline registered")
            continue
        baseline_pdf = root / baseline["pdf"]
        if not baseline_pdf.exists():
            warnings.append(f"{rel}: baseline PDF not built at {baseline['pdf']}")
        elif sha256_file(baseline_pdf) != baseline["sha256"]:
            errors.append(
                f"{rel}: baseline sha256 mismatch, manifest={baseline['sha256']} "
                f"actual={sha256_file(baseline_pdf)}"
            )
        if not (root / baseline["checkpoints"]).is_dir():
            warnings.append(
                f"{rel}: baseline checkpoints not built at {baseline['checkpoints']}"
            )

    for rel in by_file:
        if rel not in seen:
            errors.append(f"{rel}: registered but absent from the manifest")

    return errors, warnings


def load_page_labels(path: Path = PAGE_LABELS_PATH) -> dict:
    """Read the page label ground truth exactly as it is written."""
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def normalize_page_labels(raw: dict) -> dict[str, dict[str, list[str]]]:
    """Canonical form: file -> 1-based page number -> acceptable type names.

    A bare string value is the earlier single label spelling and reads as a one
    element list, so a hand written file predating the array form still loads.
    Assumes ``validate_page_labels`` found nothing to complain about.
    """
    return {
        file_name: {
            page: [value] if isinstance(value, str) else list(value)
            for page, value in pages.items()
        }
        for file_name, pages in raw.items()
    }


def validate_page_labels(
    raw: object,
    known_types: Collection[str],
    source: str = PAGE_LABELS_PATH.name,
    pages_by_file: dict[str, int] | None = None,
) -> list[str]:
    """Check the ground truth against its shape and the declared vocabulary.

    Every message names the file, the page and, where one is at fault, the
    offending element, so a hand editing round trip does not need the code.

    When ``pages_by_file`` maps a sample to its page count, a page number past
    the end of that sample is an error. Without the bound such a label simply
    never matches any produced page, and a typo would be scored as a
    classifier miss rather than reported as the editing mistake it is.
    """
    errors: list[str] = []
    if not isinstance(raw, dict):
        return [f"{source}: root must be an object"]

    declared = sorted(known_types)
    for file_name, pages in raw.items():
        if not isinstance(pages, dict):
            errors.append(f"{source}: {file_name}: value must be an object")
            continue
        total = (pages_by_file or {}).get(file_name)
        for page, value in pages.items():
            where = f"{source}: {file_name} page {page}"
            if not (page.isdigit() and int(page) >= 1):
                errors.append(f"{where}: page must be a 1-based page number")
            elif total is not None and int(page) > total:
                errors.append(f"{where}: outside the 1..{total} pages of {file_name}")
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list):
                errors.append(f"{where}: value must be an array of type names")
                continue
            if not value:
                errors.append(f"{where}: array must hold at least one type name")
                continue
            seen: set[str] = set()
            for element in value:
                if not isinstance(element, str) or not element:
                    errors.append(
                        f"{where}: element {element!r} must be a non-empty string"
                    )
                    continue
                if element not in known_types:
                    errors.append(
                        f"{where}: element {element!r} is not a declared page type; "
                        f"declared types are {declared}"
                    )
                if element in seen:
                    errors.append(f"{where}: element {element!r} appears twice")
                seen.add(element)
    return errors


def load_chain_labels(path: Path = CHAIN_LABELS_PATH) -> dict:
    """Read the boundary ground truth exactly as it is written."""
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def chain_label_samples(raw: dict) -> dict[str, dict]:
    """The sample entries of the boundary ground truth, documentation aside."""
    return {
        name: value
        for name, value in raw.items()
        if not name.startswith(DOCUMENTATION_KEY_PREFIX)
    }


def parse_boundary_key(key: str) -> tuple[int, int] | None:
    """Split a ``"N->M"`` boundary key into its two 1-based page numbers.

    Returns None for anything not of that shape, which is what the validator
    turns into a message naming the offending key.
    """
    left, separator, right = key.partition(BOUNDARY_SEPARATOR)
    if not separator or not left.isdigit() or not right.isdigit():
        return None
    return int(left), int(right)


def validate_chain_labels(
    raw: object,
    source: str = CHAIN_LABELS_PATH.name,
    pages_by_file: dict[str, int] | None = None,
) -> list[str]:
    """Check the boundary ground truth against its shape and the page counts.

    A boundary is an adjacent page pair written ``"N->N+1"`` with a boolean
    ``link``. Absent boundaries are unlabelled rather than negative, so nothing
    here requires a file to be labelled at all; what is written down, though,
    has to name a pair that exists, or a typo would be scored as a detector miss
    rather than reported as the editing mistake it is.

    A top level key marked as documentation carries the adjudicator's own prose
    and is passed over: it states what the judgements below it were made under,
    which is worth keeping beside them and is not itself a judgement.
    """
    errors: list[str] = []
    if not isinstance(raw, dict):
        return [f"{source}: root must be an object"]

    for file_name, boundaries in chain_label_samples(raw).items():
        if not isinstance(boundaries, dict):
            errors.append(f"{source}: {file_name}: value must be an object")
            continue
        total = (pages_by_file or {}).get(file_name)
        for key, entry in boundaries.items():
            where = f"{source}: {file_name} boundary {key}"
            pair = parse_boundary_key(key)
            if pair is None:
                errors.append(
                    f"{where}: key must be two 1-based page numbers "
                    f"joined by {BOUNDARY_SEPARATOR!r}"
                )
            else:
                tail, head = pair
                if tail < 1:
                    errors.append(f"{where}: pages are 1-based")
                elif head != tail + 1:
                    errors.append(f"{where}: pages must be adjacent")
                elif total is not None and head > total:
                    errors.append(
                        f"{where}: outside the 1..{total} pages of {file_name}"
                    )
            if not isinstance(entry, dict):
                errors.append(f"{where}: value must be an object")
                continue
            if "link" not in entry:
                errors.append(f"{where}: value must declare 'link'")
            elif not isinstance(entry["link"], bool):
                errors.append(f"{where}: 'link' must be a boolean")
            unknown = sorted(set(entry) - CHAIN_LABEL_KEYS)
            if unknown:
                errors.append(f"{where}: unknown keys {unknown}")
    return errors


def group_by_publication(manifest: dict) -> dict[str, list[dict]]:
    """Samples grouped by publication, the unit a leave-one-out split uses."""
    groups: dict[str, list[dict]] = {}
    for sample in manifest.get("samples", []):
        groups.setdefault(sample.get("publication", ""), []).append(sample)
    return {key: groups[key] for key in sorted(groups)}


def group_by_role(manifest: dict) -> dict[str, list[dict]]:
    """Samples grouped by corpus role, the unit the agreement domain is cut on.

    A sample carrying several roles appears under each of them, so the groups
    overlap: they answer what a role covers rather than how the corpus divides.
    """
    groups: dict[str, list[dict]] = {}
    for sample in manifest.get("samples", []):
        for role in sample.get("corpus_role", []):
            groups.setdefault(role, []).append(sample)
    return {key: groups[key] for key in sorted(groups)}


def constrained_samples(manifest: dict, role: str = CONSTRAINED_ROLE) -> list[str]:
    """File names of the samples an agreement rate assertion is binding on."""
    return [
        sample["file"]
        for sample in manifest.get("samples", [])
        if "file" in sample and role in sample.get("corpus_role", [])
    ]
