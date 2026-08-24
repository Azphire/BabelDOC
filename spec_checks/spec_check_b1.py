"""Gate script for batch B1 (IL schema extension: page kind, chains, drop caps).

Run from the repository root:

    python spec_checks/spec_check_b1.py

Exit code 0 when every assertion in plans/PLAN_B1.md passes, 1 otherwise.
Requires no API key: the pipeline is exercised with only_parse_generate_pdf and
skip_translation.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import warnings
import xml.etree.ElementTree as ET
from dataclasses import fields as dataclass_fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.assets.assets import warmup  # noqa: E402
from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import checkpoint as checkpoint_module  # noqa: E402
from babeldoc.magazine import ir_compat  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import CHECKPOINT_PREFIX  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402
from xsdata.exceptions import ConverterWarning  # noqa: E402

# Which set of the sweep this gate belongs to. It asks the artifact builder
# for documents, so a cold slot means re-running the pipeline over the
# corpus -- minutes per sample -- and it runs on the cycle's full sweep
# rather than on every batch.
GATE_SET = "sweep"

PYTHON = sys.executable
# Tag that freezes this batch; once it exists the scope assertions read the
# delta it introduced instead of the working tree.
BATCH_TAG = "batch-b1"
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
INPUT_DIR = ROOT / "examples" / "input"
OUTPUT_DIR = ROOT / "examples" / "output" / "b1"
SCHEMA_DIR = ROOT / "babeldoc" / "format" / "pdf" / "document_il"
UPSTREAM_DIFF = ROOT / "UPSTREAM_DIFF.md"

RNG_NS = "{http://relaxng.org/ns/structure/1.0}"
XSD_NS = "{http://www.w3.org/2001/XMLSchema}"

# XML attribute name -> (owning element, Python field name, Python type).
NEW_ATTRIBUTES = {
    "pageKind": ("page", "page_kind", str),
    "pageKindConf": ("page", "page_kind_conf", float),
    "pageKindSource": ("page", "page_kind_source", str),
    "chainId": ("pdfParagraph", "chain_id", str),
    "chainIndex": ("pdfParagraph", "chain_index", int),
    "dropCapCandidate": ("pdfParagraph", "drop_cap_candidate", bool),
    "dropCapDecision": ("pdfParagraph", "drop_cap_decision", str),
    "segmentSentenceStart": ("pdfParagraph", "segment_sentence_start", int),
    "segmentSentenceEnd": ("pdfParagraph", "segment_sentence_end", int),
}
NEW_FIELD_NAMES = {py for _, py, _ in NEW_ATTRIBUTES.values()}

# Where the new names are defined, rather than consumed: the generated schema
# and the gate that checks it.
NAME_DEFINITION_FILES = {
    "babeldoc/format/pdf/document_il/il_version_1.py",
    "spec_checks/spec_check_b1.py",
}

# Consumers must stay within the authorized writer list. Every file here reads
# or writes one of the nine fields on purpose and is answerable for it; any
# other file mentioning one, in either spelling, is an unauthorized consumer
# and fails the assertion. The paragraph level six stay unwritten until B9, so
# this list is what keeps that true.
NAME_REFERENCE_ALLOW_LIST = NAME_DEFINITION_FILES | {
    "babeldoc/magazine/ir_compat.py",
    "babeldoc/magazine/page_classifier.py",
    # B4 is the first writer of the paragraph level chain pair.
    "babeldoc/magazine/chain_builder.py",
    "babeldoc/magazine/chain_signals.py",
    # B5 is the first writer of the sentence range, and reads the chain pair to
    # decide what a chain is.
    "babeldoc/magazine/chain_translation.py",
    # B6 reads the page kind and the chain pair to group pages into articles,
    # and writes neither: the article map is a sidecar.
    "babeldoc/magazine/article_builder.py",
    "spec_checks/spec_check_b6.py",
    # Builds synthetic pages carrying a page kind, so that the grouping the
    # brief pass depends on is driven by a policy the gate controls.
    "spec_checks/spec_check_b6_2.py",
    # Reads the page kind to show why a boundary was scored or masked.
    "tools/chain_report.py",
    "spec_checks/spec_check_b2.py",
    "spec_checks/spec_check_b2_1.py",
    "spec_checks/spec_check_b2_3.py",
    "spec_checks/spec_check_b3.py",
    "spec_checks/spec_check_b4.py",
    # Reads the chain order out of the B4 report to rebuild a chain's members.
    "spec_checks/spec_check_b5.py",
    # B7 is the first writer of the page kind trio outside the classifier: a
    # human ruling replaces all three at once. It writes no paragraph level
    # field; the drop cap name it mentions is the configuration key naming the
    # vocabulary a later batch's verdicts come from, not the IL attribute.
    "babeldoc/magazine/hitl.py",
    "spec_checks/spec_check_b7.py",
    # B7.2 is the first writer of the drop cap pair: the marking pass sets the
    # candidate flag and the review layer's ruling sets the verdict, both from
    # this one module.
    "babeldoc/magazine/drop_cap.py",
    "spec_checks/spec_check_b7_2.py",
    # B7.3 reads both pairs out of the frozen evidence of the two-pass smoke to
    # assert what a ruling reached; it writes nothing and touches no document.
    "spec_checks/spec_check_b7_3.py",
    # B7.5 reads the page kind out of the classifier checkpoint to score the
    # refreshed corpus against the ground truth, and writes nothing.
    "spec_checks/spec_check_b7_5.py",
    # B8 detects defects in a finished document and writes none of them back.
    # The package reads the page kind to reach that page's policy, and the
    # chain pair to restate what the chain pass escalated; every write it makes
    # goes to a sidecar. Its gate builds pages carrying a kind, so the detector
    # selection it asserts is driven by a policy the gate controls.
    "babeldoc/magazine/detectors/__init__.py",
    "babeldoc/magazine/detectors/base.py",
    "babeldoc/magazine/detectors/escalation.py",
    "spec_checks/spec_check_b8.py",
    # B8.2 repairs what B8.1 detected. Its gate builds pages carrying a kind,
    # for the same reason, and renumbers the chain id when it compares two runs
    # of one pipeline; neither the loop nor the gate writes an IL field.
    "spec_checks/spec_check_b8_2.py",
    # E1 measures a finished document and writes nothing into one. The mid-unit
    # page-break rate reads the chain pair and the sentence range to tell a
    # display continuation from a cut sentence; the conservation invariant reads
    # the chain id out of a sidecar to name the chain that failed it. Its gate
    # builds paragraphs carrying all four, so the verdicts it asserts are driven
    # by geometry and fields the gate controls.
    "babeldoc/magazine/metrics/mid_break_rate.py",
    "babeldoc/magazine/metrics/conservation.py",
    "spec_checks/spec_check_e1.py",
    # E2 attributes the drift between three frozen runs. It reads the chain pair
    # off the pre-translation checkpoint to tell a merged member from its batch
    # neighbours, which is the one distinction the attribution turns on; it
    # opens no document for writing and writes only its own report.
    "tools/drift_attribution.py",
    # B9.2 sets a heading after the layout has run. The pass itself names none
    # of the nine; its gate builds one paragraph carrying a chain id, because
    # the ordering it asserts -- a chain member is scaled after its backfill,
    # never rewritten by the scaling -- is only about a paragraph that is one.
    "spec_checks/spec_check_b9_2.py",
    # B9.3 cuts a paragraph into its source lines. It reads the page kind to
    # reach that page's policy and writes no field at all: a line paragraph is
    # copied from the paragraph it came out of, so every one of the nine carries
    # without being named. Its gate builds a paragraph carrying the chain pair
    # and pages carrying a kind, because what it asserts is that the copy keeps
    # the first and that the policy of the second is what selects a page.
    "babeldoc/magazine/line_split.py",
    "spec_checks/spec_check_b9_3.py",
    # B9.4 is the first reader of the drop cap verdict. The pass that acts on it
    # lives in the module that writes it, which is why no file joins the writer
    # list here; its gate builds paragraphs carrying the candidate flag and the
    # verdict, because what it asserts is which of the two decides and that a
    # paragraph carrying neither is left alone.
    "spec_checks/spec_check_b9_4.py",
    # B10.3 exempts a page whose lines are records from the stitch, and B10.5
    # reaches a page's reflow profile the same way: both read the page kind to
    # reach that page's declared policy and neither writes a field. Their gates
    # set a kind on a page they build, because the property each asserts is that
    # the policy of the page decides, not the pass.
    "babeldoc/magazine/fragment_stitch.py",
    "babeldoc/magazine/column_reflow.py",
    "spec_checks/spec_check_b10_3.py",
    "spec_checks/spec_check_b10_5.py",
    # B10.4 applies a human ruling that retypes whole pages. The kind it names
    # travels in the ruling file and in the apply report, both of which are read
    # here by their own key names; the gate writes no IL field.
    "spec_checks/spec_check_b10_4.py",
    # F3 closes the cycle and reads the same two files to state what the ruling
    # recovered: the ruled kinds and the apply report's account of which of them
    # the classifier had agreed with. It opens no document.
    "spec_checks/spec_check_f3.py",
    # B11.6 gives the indent policy a page level gate. The pass reads the page
    # kind to reach that page's declared policy and writes no field: the flag it
    # sets is first_line_indent, which is not one of the nine. Its gate builds
    # pages carrying a kind, and so does b11.5's, because what both assert is
    # that the policy of the page decides and not the pass -- the same reason
    # b10.3 and b10.5 are on this list.
    "babeldoc/magazine/indent_policy.py",
    "spec_checks/spec_check_b11_5.py",
    "spec_checks/spec_check_b11_6.py",
}

# Upstream files carried over from B0, still uncommitted in the working tree.
ALLOWED_UPSTREAM_B0 = {
    "babeldoc/format/pdf/high_level.py",
    "babeldoc/format/pdf/translation_config.py",
    "babeldoc/translator/cache.py",
}
# Upstream files this batch is allowed to touch.
ALLOWED_UPSTREAM_B1 = {
    "babeldoc/format/pdf/document_il/il_version_1.py",
    "babeldoc/format/pdf/document_il/il_version_1.rnc",
    "babeldoc/format/pdf/document_il/il_version_1.rng",
    "babeldoc/format/pdf/document_il/il_version_1.xsd",
}
ALLOWED_UPSTREAM_OTHER = {".gitignore"}

# Trees and root documents owned by the magazine extension. The upstream scope
# assertions ignore them: the allow lists above describe upstream files only,
# and later batches keep these project paths dirty.
PROJECT_OWNED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "corpus/",
    "examples/",
    "plans/",
    "prompts/",
    "spec_checks/",
    "tools/",
)
PROJECT_OWNED_FILES = {"CLAUDE.md", "UPSTREAM_DIFF.md", "WAIVERS.md"}

# Project-owned trees whose files must be free of non-ASCII comments.
# Code and configuration whose prose has to be English. The corpus tree is not
# here: its files are adjudications of documents rather than prose about code,
# and a Chinese edition in the corpus is adjudicated by quoting the Chinese it
# splits. What governs those files is their validators and their ownership.
NEW_CODE_GLOBS = (
    "babeldoc/magazine/*.py",
    "tools/*.py",
    "spec_checks/*.py",
    "configs/*.json",
)

# CJK / fullwidth / CJK-punctuation ranges, kept as code points so that this
# gate script stays pure ASCII itself.
CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

# Checks that need an artefact built during this run. run_all --fast skips
# them; the rest read the schema quadruple, source, git or a B0 baseline that
# is already on disk.
PIPELINE_TIER = (
    "check_04b_json_stability",
    "check_07_no_values_written",
    "check_08_render",
)

# The only converter warning tolerated when reading pipeline output (W-B0-02).
KNOWN_CONVERTER_WARNING = "debug_info"

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b1_"))
_timer = harness.Timer("spec_check_b1")


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


# --- schema parsing helpers -------------------------------------------------


def rnc_attributes() -> dict[str, dict[str, bool]]:
    """element name -> {attribute name: optional} parsed from the RNC grammar."""
    text = (SCHEMA_DIR / "il_version_1.rnc").read_text(encoding="utf-8")
    out: dict[str, dict[str, bool]] = {}
    for match in re.finditer(r"element\s+(\w+)\s*\{", text):
        name = match.group(1)
        start = match.end()
        index, depth = start, 1
        while depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        body = text[start : index - 1]
        # Nested element bodies belong to their own element, not to this one.
        flat = re.sub(r"element\s+\w+\s*\{[^{}]*\}", "", body)
        attrs: dict[str, bool] = {}
        for attr in re.finditer(r"attribute\s+(\w+)\s*\{", flat):
            cursor, depth = attr.end(), 1
            while depth:
                if flat[cursor] == "{":
                    depth += 1
                elif flat[cursor] == "}":
                    depth -= 1
                cursor += 1
            attrs[attr.group(1)] = flat[cursor : cursor + 1] == "?"
        out.setdefault(name, {}).update(attrs)
    return out


def rng_attributes() -> dict[str, dict[str, bool]]:
    root = ET.parse(SCHEMA_DIR / "il_version_1.rng").getroot()  # noqa: S314
    out: dict[str, dict[str, bool]] = {}

    def walk(node, owner: str | None, optional: bool) -> None:
        for child in node:
            if child.tag == f"{RNG_NS}element":
                name = child.get("name")
                out.setdefault(name, {})
                walk(child, name, False)
            elif child.tag == f"{RNG_NS}attribute":
                if owner is not None:
                    out.setdefault(owner, {})[child.get("name")] = optional
            elif child.tag == f"{RNG_NS}optional":
                walk(child, owner, True)
            else:
                walk(child, owner, optional)

    for define in root.findall(f"{RNG_NS}define"):
        walk(define, None, False)
    walk(root, None, False)
    return out


def xsd_attributes() -> dict[str, dict[str, bool]]:
    root = ET.parse(SCHEMA_DIR / "il_version_1.xsd").getroot()  # noqa: S314
    out: dict[str, dict[str, bool]] = {}
    for element in root.findall(f"{XSD_NS}element"):
        attrs: dict[str, bool] = {}
        complex_type = element.find(f"{XSD_NS}complexType")
        if complex_type is not None:
            for attr in complex_type.findall(f"{XSD_NS}attribute"):
                attrs[attr.get("name")] = attr.get("use") != "required"
        out[element.get("name")] = attrs
    return out


# --- pipeline helpers -------------------------------------------------------


def freeze_checkpoints(working_dir: Path, target: Path) -> Path:
    """Copy the checkpoints of a run into ``target``, replacing what was there."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for item in sorted(working_dir.glob(f"{CHECKPOINT_PREFIX}*")):
        shutil.copyfile(item, target / item.name)
    return target


def run_parse_only(pdf: Path, name: str) -> tuple[Path, Path]:
    """Dry run a sample and freeze its mono PDF and checkpoints under b1/."""
    with _timer.phase(f"pipeline:parse_only:{name}"):
        built = artifacts.get_artifacts(pdf, "parse_only")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    produced_pdf = OUTPUT_DIR / f"{name}.b1.pdf"
    shutil.copyfile(built.mono_pdf, produced_pdf)
    checkpoint_dir = freeze_checkpoints(
        built.working_dir, OUTPUT_DIR / f"{name}.checkpoints"
    )
    return produced_pdf, checkpoint_dir


def run_all_stages(pdf: Path, name: str) -> Path:
    """Run every non-translation stage so paragraph-bearing checkpoints exist."""
    with _timer.phase(f"pipeline:stages:{name}"):
        built = artifacts.get_artifacts(pdf, "stages")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return freeze_checkpoints(built.working_dir, OUTPUT_DIR / f"{name}.stages")


def render_diff(pdf_a: Path, pdf_b: Path, out_dir: Path) -> int:
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [
            PYTHON,
            str(ROOT / "tools" / "render_diff.py"),
            str(pdf_a),
            str(pdf_b),
            "--out",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode


def json_delta(old, new, path: str = "") -> list[str]:
    """Report differences between two JSON trees, ignoring new null-valued keys."""
    problems: list[str] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in old:
            if key not in new:
                problems.append(f"{path}/{key}: key disappeared")
            else:
                problems.extend(json_delta(old[key], new[key], f"{path}/{key}"))
        for key in new:
            if key in old:
                continue
            if key not in NEW_FIELD_NAMES:
                problems.append(f"{path}/{key}: unexpected new key")
            elif new[key] is not None:
                problems.append(f"{path}/{key}: new key carries {new[key]!r}")
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            problems.append(f"{path}: length {len(old)} -> {len(new)}")
        else:
            for index, (a, b) in enumerate(zip(old, new, strict=True)):
                problems.extend(json_delta(a, b, f"{path}[{index}]"))
    elif old != new:
        problems.append(f"{path}: {old!r} -> {new!r}")
    return problems


# --- assertions -------------------------------------------------------------


def check_01_schema_attributes() -> None:
    rnc, rng, xsd = rnc_attributes(), rng_attributes(), xsd_attributes()
    missing: list[str] = []
    not_optional: list[str] = []
    for attribute, (element, _, _) in NEW_ATTRIBUTES.items():
        for label, table in (("rnc", rnc), ("rng", rng), ("xsd", xsd)):
            if attribute not in table.get(element, {}):
                missing.append(f"{label}:{element}/{attribute}")
            elif not table[element][attribute]:
                not_optional.append(f"{label}:{element}/{attribute}")
    record(
        "01a all nine new attributes present in rnc, rng and xsd",
        not missing,
        f"missing={missing}",
    )
    record(
        "01b every new attribute is optional in all three schemas",
        not not_optional,
        f"required={not_optional}",
    )

    elements = sorted(set(rnc) | set(rng) | set(xsd))
    mismatched = [
        name
        for name in elements
        if not (rnc.get(name) == rng.get(name) == xsd.get(name))
    ]
    record(
        "01c the three schema files stay attribute-wise identical",
        not mismatched,
        f"elements={len(elements)} mismatched={mismatched}",
    )


def check_02_dataclass_fields() -> None:
    problems: list[str] = []
    models = {"page": il_version_1.Page, "pdfParagraph": il_version_1.PdfParagraph}
    for attribute, (element, field_name, field_type) in NEW_ATTRIBUTES.items():
        by_name = {f.name: f for f in dataclass_fields(models[element])}
        if field_name not in by_name:
            problems.append(f"{element}.{field_name}: missing")
            continue
        field = by_name[field_name]
        if field.default is not None:
            problems.append(f"{element}.{field_name}: default={field.default!r}")
        if field.metadata.get("name") != attribute:
            problems.append(
                f"{element}.{field_name}: metadata name={field.metadata.get('name')!r}"
            )
        if field.metadata.get("type") != "Attribute":
            problems.append(f"{element}.{field_name}: not mapped as an attribute")
        if str(field.type) != f"{field_type.__name__} | None":
            problems.append(f"{element}.{field_name}: type={field.type}")
    record(
        "02 Page and PdfParagraph expose the new fields with camelCase metadata",
        not problems,
        f"problems={problems}",
    )


def check_03_roundtrip() -> None:
    try:
        ir_compat.assert_new_fields_roundtrip()
        record("03 assert_new_fields_roundtrip passes over the XML path", True)
    except AssertionError as exc:
        record(
            "03 assert_new_fields_roundtrip passes over the XML path", False, str(exc)
        )


def check_04a_json_keys() -> None:
    converter = XMLConverter()
    payload = json.loads(converter.to_json(ir_compat.build_probe_document()))
    page = payload["page"][0]
    paragraph = page["pdf_paragraph"][0]
    missing = [name for name in ir_compat.NEW_PAGE_FIELDS if name not in page]
    missing += [
        name for name in ir_compat.NEW_PARAGRAPH_FIELDS if name not in paragraph
    ]
    unset = [name for name in ir_compat.NEW_PAGE_FIELDS if page.get(name) is None]
    unset += [
        name for name in ir_compat.NEW_PARAGRAPH_FIELDS if paragraph.get(name) is None
    ]
    record(
        "04a to_json emits every new key once the field is set",
        not missing and not unset,
        f"missing={missing} unset={unset}",
    )


def check_04b_json_stability(produced: dict[str, Path], manifest: dict) -> None:
    problems: list[str] = []
    compared = 0
    for entry in manifest["samples"]:
        name = Path(entry["file"]).stem
        baseline_dir = ROOT / entry["baseline"]["checkpoints"]
        for baseline_json in checkpoint_module.checkpoint_paths(baseline_dir, "*.json"):
            new_json = produced[name] / baseline_json.name
            if not new_json.exists():
                problems.append(f"{name}: {baseline_json.name} not produced")
                continue
            compared += 1
            old = json.loads(checkpoint_module.read_checkpoint_text(baseline_json))
            new = json.loads(new_json.read_text(encoding="utf-8"))
            problems.extend(
                f"{name}/{baseline_json.name}{item}"
                for item in json_delta(old, new)[:5]
            )
    record(
        "04b unset new fields leave the existing JSON key set untouched",
        not problems and compared > 0,
        f"compared={compared} problems={problems[:5]}",
    )


def check_05_backward_compat(manifest: dict) -> None:
    problems: list[str] = []
    unexpected_warnings: list[str] = []
    checked = 0
    for entry in manifest["samples"]:
        baseline_dir = ROOT / entry["baseline"]["checkpoints"]
        for xml_path in checkpoint_module.checkpoint_paths(baseline_dir, "*.xml"):
            checked += 1
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    ir_compat.assert_backward_compat(xml_path)
                except AssertionError as exc:
                    problems.append(str(exc))
            for item in caught:
                message = str(item.message)
                if item.category is not ConverterWarning:
                    unexpected_warnings.append(f"{xml_path.name}: {message}")
                elif KNOWN_CONVERTER_WARNING not in message or any(
                    field in message for field in NEW_FIELD_NAMES
                ):
                    unexpected_warnings.append(f"{xml_path.name}: {message}")
    record(
        "05a every B0 baseline checkpoint parses with all new fields None",
        not problems and checked > 0,
        f"checked={checked} problems={problems[:3]}",
    )
    record(
        "05b reading old checkpoints raises no warning beyond the known one",
        not unexpected_warnings,
        f"unexpected={unexpected_warnings[:3]}",
    )


def check_06_no_consumers() -> None:
    # Both spellings: the XML attribute name and the Python field name. A file
    # touching either one is consuming the field.
    needles = sorted(set(NEW_ATTRIBUTES) | NEW_FIELD_NAMES)
    offenders: list[str] = []
    skip_parts = {".git", "__pycache__", ".venv", "examples", ".ruff_cache"}
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if set(path.relative_to(ROOT).parts) & skip_parts:
            continue
        if relative in NAME_REFERENCE_ALLOW_LIST:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in needles:
            if needle in text:
                offenders.append(f"{relative}: {needle}")
    unauthorized = sorted({entry.split(":")[0] for entry in offenders})
    record(
        "06 consumers must stay within the authorized writer list",
        not offenders,
        f"unauthorized_files={unauthorized} hits={len(offenders)} "
        f"examples={offenders[:5]}",
    )


def check_07_no_values_written(checkpoint_dirs: list[Path]) -> None:
    needles = sorted(NEW_ATTRIBUTES)
    hits: list[str] = []
    scanned = 0
    for directory in checkpoint_dirs:
        for xml_path in sorted(directory.glob("*.xml")):
            scanned += 1
            text = xml_path.read_text(encoding="utf-8")
            hits.extend(
                f"{directory.name}/{xml_path.name}: {needle}"
                for needle in needles
                if needle in text
            )
    record(
        "07 no stage writes a new attribute into any checkpoint",
        not hits and scanned > 0,
        f"scanned={scanned} hits={hits[:5]}",
    )


def check_08_render(manifest: dict, produced_pdfs: dict[str, Path]) -> None:
    for entry in manifest["samples"]:
        name = Path(entry["file"]).stem
        baseline = ROOT / entry["baseline"]["pdf"]
        code = render_diff(baseline, produced_pdfs[name], _tmp_root / f"rd_{name}")
        record(
            f"08 dry run still renders identically to the B0 baseline ({name})",
            code == 0,
            f"exit={code}",
        )


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout


def batch_revisions() -> list[str]:
    """Revision arguments selecting the delta this batch introduced.

    Once the batch is tagged that is the tag against its parent, so a later
    batch can re-run this gate without its own changes counting here. Before
    the tag exists it is the working tree against HEAD.
    """
    code, _ = git_output(["rev-parse", "-q", "--verify", f"{BATCH_TAG}^{{commit}}"])
    return [f"{BATCH_TAG}^", BATCH_TAG] if code == 0 else ["HEAD"]


def changed_upstream_files() -> set[str]:
    """Upstream paths this batch changed."""
    _, listing = git_output(["diff", "--name-only", *batch_revisions()])
    return {
        path
        for path in (line.strip() for line in listing.splitlines())
        if path
        and path not in PROJECT_OWNED_FILES
        and not path.startswith(PROJECT_OWNED_PREFIXES)
    }


def check_09_upstream_scope() -> None:
    changed = changed_upstream_files()
    allowed = ALLOWED_UPSTREAM_B0 | ALLOWED_UPSTREAM_B1 | ALLOWED_UPSTREAM_OTHER
    record(
        "09a modified upstream files stay inside the registered allow list",
        changed <= allowed,
        f"unexpected={sorted(changed - allowed)}",
    )
    batch_delta = changed - ALLOWED_UPSTREAM_B0 - ALLOWED_UPSTREAM_OTHER
    record(
        "09b this batch touches only the IL schema quadruple",
        batch_delta <= ALLOWED_UPSTREAM_B1,
        f"delta={sorted(batch_delta)}",
    )

    registry = UPSTREAM_DIFF.read_text(encoding="utf-8")
    unregistered = sorted(path for path in changed if path not in registry)
    record(
        "09c every modified upstream file is registered in UPSTREAM_DIFF.md",
        not unregistered,
        f"unregistered={unregistered}",
    )


def check_09d_ascii_comments() -> None:
    offenders: list[str] = []
    for pattern in NEW_CODE_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if has_cjk(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")

    tracked = sorted(ALLOWED_UPSTREAM_B0 | ALLOWED_UPSTREAM_B1)
    _, diff = git_output(["diff", "-U0", *batch_revisions(), "--", *tracked])
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++") and has_cjk(line):
            offenders.append(f"added upstream line: {line.strip()}")
    record(
        "09d no CJK characters in new or added code",
        not offenders,
        f"offenders={offenders[:5]}",
    )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    with _timer.phase("warmup"):
        use_project_cache(ROOT)
        warmup()

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)

    check_01_schema_attributes()
    check_02_dataclass_fields()
    check_03_roundtrip()
    check_04a_json_keys()
    check_05_backward_compat(manifest)
    check_06_no_consumers()

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        produced_pdfs: dict[str, Path] = {}
        checkpoint_dirs: dict[str, Path] = {}
        for entry in manifest["samples"]:
            name = Path(entry["file"]).stem
            pdf, checkpoints = run_parse_only(INPUT_DIR / entry["file"], name)
            produced_pdfs[name] = pdf
            checkpoint_dirs[name] = checkpoints

        # The dry run stops after IL creation, so one sample is also taken
        # through every non-translation stage to cover paragraph-bearing
        # checkpoints.
        smallest = min(manifest["samples"], key=lambda entry: entry["pages"])
        stage_dir = run_all_stages(
            INPUT_DIR / smallest["file"], Path(smallest["file"]).stem
        )

        check_04b_json_stability(checkpoint_dirs, manifest)
        check_07_no_values_written([*checkpoint_dirs.values(), stage_dir])
        check_08_render(manifest, produced_pdfs)

    check_09_upstream_scope()
    check_09d_ascii_comments()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b1")
    artifacts.print_stats("spec_check_b1")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b1: {len(_results) - len(failed)}/{len(_results)} passed")
    for name in failed:
        print(f"  FAILED: {name}")
    shutil.rmtree(_tmp_root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
