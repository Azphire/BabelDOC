"""Gate script for batch B6 session one (article grouping and the map sidecar).

Run from the repository root:

    python spec_checks/spec_check_b6.py

Exit code 0 when every assertion T6.1 answers for passes, 1 otherwise. Needs no
API key and makes no network request: grouping reads the page type vocabulary
and the chains already in the document, and the pipeline runs it with
skip_translation.

The batch exists because two questions were being answered by one policy flag.
``starts_article`` is the chain detector's prior -- running text does not
continue into this page -- and grouping needs a different one: an article begins
on this page. They agree on the flowing page types and disagree on every piece
of furniture, so a contents page declared as somewhere text begins was also read
as somewhere an article begins, and absorbed the feature page after it.
Assertion 02 is what pins the separation down: four synthetic types crossing the
two flags, the chain prior asked to depend on one of them and the grouping role
on the other, neither on both.

01 is the declaration itself: the new flag is optional and defaults to false, so
a vocabulary written before it still loads; exactly the types that declare it
read true; a non-boolean is refused; and no ``starts_article`` declaration moved,
which is what keeps the B4 detector's inputs identical.

03 is the grouping walk on documents built for it -- an article continuing
across a bought page, two openers in a row, a document declaring no opener at
all, a page belonging to no article absorbing nothing, a chain drawn across a
boundary the walk had drawn, and a page whose kind the vocabulary does not know.

04 is the same walk over the corpus, stated structurally rather than by count:
every page is in exactly one article or in none, no chain crosses an article,
and nothing belonging to no article appears inside one. No assertion here names
how many articles a sample has; that is a measurement and it belongs in the
report.

05 is the one instance assertion, on the sample the absorbed page was found on.

06 is the switch, 07 determinism, 08 the change scope and what the stage may not
do, and 09 the full sweep, suppressed when the runner is already performing one.

Tiers: 04, 05, 06b, 06c, 06d and 07b need pipeline artefacts and belong to the
pipeline tier; everything else is static or synthetic.
"""

from __future__ import annotations

import ast
import copy
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf.document_il import il_version_1  # noqa: E402
from babeldoc.format.pdf.document_il.xml_converter import XMLConverter  # noqa: E402
from babeldoc.magazine import article_builder  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import taxonomy as taxonomy_module  # noqa: E402
from babeldoc.magazine.article_builder import REPORT_NAME  # noqa: E402
from babeldoc.magazine.chain_signals import opener_prior  # noqa: E402
from spec_checks import artifacts  # noqa: E402
from spec_checks import harness  # noqa: E402

# The commit this session starts from, and the tag that freezes it.
BASE_TAG = "batch-b6.0"
BATCH_TAG = "batch-b6.1"

PYTHON = sys.executable

MODULE = "babeldoc/magazine/article_builder.py"
CONFIG = "configs/article_grouping.json"
TAXONOMY = "configs/page_types.json"
HIGH_LEVEL = "babeldoc/format/pdf/high_level.py"
SCHEMA = "babeldoc/format/pdf/document_il/il_version_1.xsd"
OUTPUT_DIR = ROOT / "examples" / "output" / "b6"

# Set by spec_checks/run_all.py.
NESTED_SUPPRESSED = os.environ.get("SPEC_NO_NESTED") == "1"

PIPELINE_TIER = (
    "check_04_corpus_structure",
    "check_05_instance",
    "check_06b_sidecar",
    "check_06c_zero_difference",
    "check_06d_conservation",
    "check_07b_corpus_determinism",
)

# The page types that declare the new flag. Named here because the assertion is
# about the declaration itself: these three and nothing else.
OPENING_TYPES = frozenset({"article_opener", "editorial", "interview"})

# The publication the absorbed page was found on, and what the rule says about
# the first four pages of its sample: cover, colophon and contents belong to no
# article, and the first page carrying chainable text opens the first one. The
# publication is named rather than the file, so a corpus refresh that replaces
# the excerpt with a longer one keeps the instance instead of silently skipping
# it; the front matter the assertion is about is the same either way.
INSTANCE_PUBLICATION = "aramcoworld"
INSTANCE_UNASSIGNED = (1, 2, 3)
INSTANCE_FIRST_START = 4

# Paths this session may change. The delivery report is committed alongside the
# code, as batch-b5.3's smoke report was, so one document under the output tree
# is inside the scope -- named file by file rather than by prefix, because
# everything else that lands under examples/output/ is a produced artefact and a
# prefix would let one be committed without anyone noticing.
ALLOWED_PREFIXES = (
    "babeldoc/magazine/",
    "configs/",
    "tools/",
    "spec_checks/",
    "plans/",
)
ALLOWED_FILES = {
    "CLAUDE.md",
    "UPSTREAM_DIFF.md",
    "examples/output/b6/article_grouping.report.md",
}

# The upstream files PLAN_B6 names. This session hooks into two of them and
# leaves the third alone, so the assertion is a subset rather than an equality.
ALLOWED_UPSTREAM = {
    "babeldoc/format/pdf/high_level.py",
    "babeldoc/format/pdf/translation_config.py",
    "babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py",
}

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

CJK_SCAN_FILES = (MODULE, CONFIG, TAXONOMY, "spec_checks/spec_check_b6.py")
CJK_RANGES = ((0x3000, 0x303F), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))

# Every attribute B1 added. The grouping stage may read the chain pair and may
# write none of them: the map is a sidecar and the schema is frozen.
IL_FIELD_NAMES = (
    "page_kind",
    "page_kind_conf",
    "page_kind_source",
    "chain_id",
    "chain_index",
    "drop_cap_candidate",
    "drop_cap_decision",
    "segment_sentence_start",
    "segment_sentence_end",
)

# The flag the grouping stage must not read. It is named in that module's prose,
# where the separation is explained, so the scan reads code strings only.
CHAIN_PRIOR_FLAG = "starts_article"

# Layout label of a synthetic body paragraph. Headings are labelled from the
# declaration under test rather than from a name written here.
BODY_LABEL = "plain text"

# Synthetic page kinds, and the policy each of them stands for. The names are
# not vocabulary names: the point is to drive the walk from a policy this file
# controls, so that assertion 03 states the rule rather than the corpus.
KIND_OPENS = "synthetic_opens"
KIND_MEMBER = "synthetic_member"
KIND_FURNITURE = "synthetic_furniture"
KIND_UNKNOWN = "synthetic_undeclared"

SYNTHETIC_POLICY = {
    KIND_OPENS: {"opens_article": True, "chain_eligible": True, "translate": True},
    KIND_MEMBER: {"opens_article": False, "chain_eligible": True, "translate": True},
    KIND_FURNITURE: {
        "opens_article": False,
        "chain_eligible": False,
        "translate": True,
    },
}

_results: list[tuple[str, bool, str]] = []
_tmp_root = Path(tempfile.mkdtemp(prefix="spec_b6_"))
_timer = harness.Timer("spec_check_b6")


def record(name: str, ok: bool, detail: str = "") -> bool:
    _timer.mark(name)
    detail = detail.encode("ascii", "backslashreplace").decode("ascii")
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return ok


def skip(name: str, detail: str) -> None:
    print(f"SKIPPED: {detail} :: {name}")


def has_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in CJK_RANGES) for char in text
    )


def git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603, S607 - git is expected on PATH for this gate
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def tag_exists(tag: str) -> bool:
    code, _ = git_output(["rev-parse", "-q", "--verify", f"{tag}^{{commit}}"])
    return code == 0


def changed_files() -> set[str]:
    """Every path this session changed, anchored on its tag once it exists."""
    if tag_exists(BATCH_TAG):
        _, listing = git_output(["diff", "--name-only", BASE_TAG, BATCH_TAG])
        return {line.strip() for line in listing.splitlines() if line.strip()}

    _, listing = git_output(["diff", "--name-only", BASE_TAG])
    paths = {line.strip() for line in listing.splitlines() if line.strip()}
    _, untracked = git_output(["status", "--porcelain", "--untracked-files=all"])
    for line in untracked.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path)
    return paths


def read_checkpoint(path: Path) -> il_version_1.Document:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return XMLConverter().read_xml(str(path))


def sample_pdfs() -> list[Path]:
    manifest = corpus.load_manifest()
    return [ROOT / "examples" / "input" / e["file"] for e in manifest["samples"]]


def instance_stem() -> str | None:
    """The stem of the registered sample of the instance publication."""
    for sample in corpus.load_manifest().get("samples", []):
        if sample.get("publication") == INSTANCE_PUBLICATION:
            return Path(sample["file"]).stem
    return None


def code_strings(path: Path) -> set[str]:
    """Every string constant a module uses in code, docstrings excluded.

    A module explaining in prose which flag it deliberately does not read would
    otherwise fail the assertion that it does not read it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


def assigned_attributes(path: Path) -> set[str]:
    """Attribute names a module assigns to, however the assignment is written."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


class WorkingDir:
    """The whole of what the stage asks a translation config for."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def get_working_file_path(self, name: str) -> str:
        return str(self.directory / name)


# --- synthetic documents -----------------------------------------------------


def synthetic_paragraph(
    debug_id: str, label: str = BODY_LABEL, text: str = "body text"
) -> il_version_1.PdfParagraph:
    return il_version_1.PdfParagraph(
        debug_id=debug_id, layout_label=label, unicode=text
    )


def synthetic_page(index: int, kind: str, paragraphs=None) -> il_version_1.Page:
    return il_version_1.Page(
        page_number=index,
        page_kind=kind,
        page_kind_conf=1.0,
        pdf_paragraph=list(paragraphs)
        if paragraphs
        else [synthetic_paragraph(f"p{index}")],
    )


def synthetic_document(kinds: list[str]) -> il_version_1.Document:
    return il_version_1.Document(
        page=[synthetic_page(index, kind) for index, kind in enumerate(kinds)]
    )


def synthetic_policy_of(kind: str | None) -> dict | None:
    return SYNTHETIC_POLICY.get(kind)


def heading_labels() -> tuple[str, ...]:
    return article_builder.title_labels(article_builder.load_grouping_config())


def group(kinds: list[str], chains: dict[str, list[int]] | None = None):
    """Group a synthetic document, optionally with chains laid across it."""
    docs = synthetic_document(kinds)
    for chain_id, pages in (chains or {}).items():
        for order, page_index in enumerate(pages):
            paragraph = docs.page[page_index].pdf_paragraph[0]
            paragraph.chain_id = chain_id
            paragraph.chain_index = order
    return docs, article_builder.build_articles(
        docs, synthetic_policy_of, heading_labels()
    )


def page_sets(grouping) -> list[list[int]]:
    """Article membership as 1-based page numbers, in page order."""
    return [[index + 1 for index in article.pages] for article in grouping.articles]


def unassigned_pages(grouping) -> list[int]:
    return [role.index + 1 for role in grouping.unassigned]


# --- 01 the declaration ------------------------------------------------------


def write_taxonomy(name: str, mutate) -> str:
    raw = json.loads((ROOT / TAXONOMY).read_text(encoding="utf-8"))
    mutate(raw)
    path = _tmp_root / f"{name}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return str(path)


def check_01_declaration() -> None:
    """Positive 1: the flag is declared, optional, and the old one is untouched."""
    taxonomy = taxonomy_module.load_taxonomy()
    declared = {
        page_type.name: page_type.policy.get(article_builder.OPENER_POLICY_FLAG)
        for page_type in taxonomy.page_types
    }
    opening = {name for name, value in declared.items() if value}
    record(
        "01a exactly the declared types open an article",
        opening == OPENING_TYPES
        and all(isinstance(value, bool) for value in declared.values()),
        f"opening={sorted(opening)} expected={sorted(OPENING_TYPES)}",
    )

    def strip_flag(raw: dict) -> None:
        for entry in raw["page_types"]:
            entry["policy"].pop(article_builder.OPENER_POLICY_FLAG, None)

    stripped = taxonomy_module.load_taxonomy(write_taxonomy("stripped", strip_flag))
    defaults = {
        page_type.name: page_type.policy[article_builder.OPENER_POLICY_FLAG]
        for page_type in stripped.page_types
    }
    record(
        "01b a vocabulary written before the flag still loads and reads false",
        len(defaults) == len(taxonomy.page_types) and not any(defaults.values()),
        f"types={len(defaults)} any_true={any(defaults.values())}",
    )

    def bad_flag(raw: dict) -> None:
        raw["page_types"][0]["policy"][article_builder.OPENER_POLICY_FLAG] = "yes"

    refused = False
    try:
        taxonomy_module.load_taxonomy(write_taxonomy("bad_flag", bad_flag))
    except taxonomy_module.TaxonomyError:
        refused = True
    record("01c a non-boolean declaration is refused at load", refused, "")

    # The chain detector's prior is an input this session may not disturb, so
    # every declaration it reads has to be what batch-b6.0 shipped.
    code, before = git_output(["show", f"{BASE_TAG}:{TAXONOMY}"])
    moved: list[str] = []
    if code == 0:
        previous = {
            entry["name"]: entry["policy"].get(CHAIN_PRIOR_FLAG)
            for entry in json.loads(before)["page_types"]
        }
        current = {
            page_type.name: page_type.policy.get(CHAIN_PRIOR_FLAG)
            for page_type in taxonomy.page_types
        }
        moved = sorted(
            name
            for name in set(previous) | set(current)
            if previous.get(name) != current.get(name)
        )
    record(
        "01d no starts_article declaration moved",
        code == 0 and not moved,
        f"moved={moved}",
    )


# --- 02 the two flags are independent ----------------------------------------


def combination_taxonomy() -> tuple[str, dict[tuple[bool, bool], str]]:
    """A vocabulary of four types, one per combination of the two flags.

    Built from a shipped type so its rules are real ones; only the name and the
    two flags differ between the four, which is what makes the comparison a
    comparison of the flags alone.
    """
    raw = json.loads((ROOT / TAXONOMY).read_text(encoding="utf-8"))
    template = copy.deepcopy(raw["page_types"][0])
    entries = []
    names: dict[tuple[bool, bool], str] = {}
    for starts in (False, True):
        for opens in (False, True):
            entry = copy.deepcopy(template)
            name = f"combo_{int(starts)}{int(opens)}"
            entry["name"] = name
            entry["description"] = "one combination of the two flags"
            entry["policy"] = {
                "chain_eligible": True,
                "translate": True,
                "repair_profile": "flow",
                CHAIN_PRIOR_FLAG: starts,
                article_builder.OPENER_POLICY_FLAG: opens,
            }
            entries.append(entry)
            names[(starts, opens)] = name
    raw["page_types"] = entries
    raw["default_type"] = names[(False, False)]
    path = _tmp_root / "combinations.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return str(path), names


def check_02_flag_independence() -> None:
    """Positive 2: each consumer reads its own flag and is blind to the other."""
    path, names = combination_taxonomy()
    taxonomy = taxonomy_module.load_taxonomy(path)

    priors: dict[tuple[bool, bool], float] = {}
    roles: dict[tuple[bool, bool], str] = {}
    for combination, name in names.items():
        page = synthetic_page(0, name)
        priors[combination] = opener_prior(page, taxonomy.policy_of(name))
        roles[combination] = article_builder.page_role(
            page, 0, taxonomy.policy_of
        ).role

    prior_blind = all(
        priors[(starts, False)] == priors[(starts, True)] for starts in (False, True)
    )
    prior_moves = priors[(True, False)] > priors[(False, False)]
    record(
        "02a the chain prior reads starts_article and is blind to opens_article",
        prior_blind and prior_moves,
        f"priors={{{', '.join(f'{s}{o}={v}' for (s, o), v in priors.items())}}}",
    )

    role_blind = all(
        roles[(False, opens)] == roles[(True, opens)] for opens in (False, True)
    )
    role_moves = (
        roles[(False, True)] == article_builder.ROLE_OPENS
        and roles[(False, False)] == article_builder.ROLE_MEMBER
    )
    record(
        "02b the grouping role reads opens_article and is blind to starts_article",
        role_blind and role_moves,
        f"roles={{{', '.join(f'{s}{o}={v}' for (s, o), v in roles.items())}}}",
    )

    # Reload the shipped vocabulary: load_taxonomy caches one entry, and every
    # assertion after this one asks about the real one.
    taxonomy_module.load_taxonomy()


# --- 03 the grouping walk ----------------------------------------------------


def check_03_synthetic_walk() -> None:
    """Positive 3: the walk on documents built to exercise each of its rules."""
    _, across = group([KIND_OPENS, KIND_MEMBER, KIND_FURNITURE, KIND_MEMBER])
    record(
        "03a an article continues across a page belonging to no article",
        page_sets(across) == [[1, 2, 4]] and unassigned_pages(across) == [3],
        f"articles={page_sets(across)} unassigned={unassigned_pages(across)}",
    )

    _, twice = group([KIND_OPENS, KIND_OPENS, KIND_MEMBER])
    record(
        "03b two openers in a row are two articles",
        page_sets(twice) == [[1], [2, 3]],
        f"articles={page_sets(twice)}",
    )

    _, headless = group([KIND_MEMBER, KIND_MEMBER, KIND_MEMBER])
    record(
        "03c a document declaring no opener is one article",
        page_sets(headless) == [[1, 2, 3]] and not unassigned_pages(headless),
        f"articles={page_sets(headless)}",
    )

    _, leading = group([KIND_FURNITURE, KIND_FURNITURE, KIND_MEMBER, KIND_OPENS])
    _, trailing = group([KIND_OPENS, KIND_FURNITURE])
    record(
        "03d a page belonging to no article absorbs nothing",
        page_sets(leading) == [[3], [4]]
        and unassigned_pages(leading) == [1, 2]
        and page_sets(trailing) == [[1]]
        and unassigned_pages(trailing) == [2],
        f"leading={page_sets(leading)}/{unassigned_pages(leading)} "
        f"trailing={page_sets(trailing)}/{unassigned_pages(trailing)}",
    )

    _, joined = group([KIND_OPENS, KIND_OPENS, KIND_OPENS], chains={"c1": [0, 1]})
    merged = [article.merged_by_chain for article in joined.articles]
    record(
        "03e a chain across a drawn boundary joins the two articles",
        page_sets(joined) == [[1, 2], [3]] and merged == [True, False],
        f"articles={page_sets(joined)} merged={merged}",
    )

    _, unknown = group([KIND_UNKNOWN, KIND_MEMBER])
    reasons = [role.reason for role in unknown.unassigned]
    record(
        "03f a page whose kind the vocabulary does not declare stands apart",
        page_sets(unknown) == [[2]]
        and unassigned_pages(unknown) == [1]
        and reasons == [article_builder.REASON_NO_PAGE_KIND],
        f"articles={page_sets(unknown)} reasons={reasons}",
    )

    # The title reference is the first heading on the opening page, recognised
    # by the labels the declaration names rather than by a label written here.
    label = heading_labels()[0]
    docs = synthetic_document([KIND_OPENS])
    docs.page[0].pdf_paragraph = [
        synthetic_paragraph("body", BODY_LABEL, "a body paragraph first"),
        synthetic_paragraph("head", label, "The Heading"),
        synthetic_paragraph("later", label, "A Second Heading"),
    ]
    grouping = article_builder.build_articles(
        docs, synthetic_policy_of, heading_labels()
    )
    found = article_builder.title_paragraph(docs.page[0], heading_labels())
    record(
        "03g the title reference is the first heading on the opening page",
        len(grouping.articles) == 1
        and found is not None
        and found.debug_id == "head",
        f"title={None if found is None else found.debug_id}",
    )


# --- pipeline artefacts ------------------------------------------------------


_runs: dict[str, dict] = {}


def runs() -> dict[str, dict]:
    """The grouping run and the switch-down run of every corpus sample."""
    if _runs:
        return _runs
    for pdf in sample_pdfs():
        grouped = artifacts.get_artifacts(pdf, "grouped")
        chained = artifacts.get_artifacts(pdf, "chained")
        map_path = grouped.working_dir / REPORT_NAME
        _runs[pdf.stem] = {
            "grouped": grouped,
            "chained": chained,
            "map": json.loads(map_path.read_text(encoding="utf-8"))
            if map_path.exists()
            else None,
        }
    return _runs


def checkpoint_of(working_dir: Path, stage: str) -> Path | None:
    from babeldoc.magazine.checkpoint import checkpoint_stem

    path = working_dir / f"{checkpoint_stem(stage)}.xml"
    return path if path.exists() else None


# --- 04 the corpus, structurally ---------------------------------------------


def check_04_corpus_structure() -> None:
    """Positive 4: the partition holds on every sample, without naming a count."""
    partition: list[str] = []
    crossing: list[str] = []
    absorbed: list[str] = []
    identity: list[str] = []
    titles: list[str] = []
    table: list[dict] = []

    for stem, run in runs().items():
        article_map = run["map"]
        if article_map is None:
            partition.append(f"{stem}: no map written")
            continue
        pages = {entry["page"] for entry in article_map["pages"]}
        held: dict[int, list[str]] = {}
        for article in article_map["articles"]:
            for page in article["pages"]:
                held.setdefault(page, []).append(article["article_id"])
        unassigned = {entry["page"] for entry in article_map["unassigned"]}

        twice = sorted(page for page, owners in held.items() if len(owners) > 1)
        both = sorted(set(held) & unassigned)
        neither = sorted(pages - set(held) - unassigned)
        if twice or both or neither:
            partition.append(
                f"{stem}: in two articles={twice} in both={both} in neither={neither}"
            )

        ids = [article["article_id"] for article in article_map["articles"]]
        if len(set(ids)) != len(ids) or any(not value for value in ids):
            identity.append(f"{stem}: article ids {ids}")
        for article in article_map["articles"]:
            if article["pages"] != sorted(set(article["pages"])):
                identity.append(f"{stem}: {article['article_id']} pages out of order")
            if article["start_page"] != min(article["pages"]):
                identity.append(f"{stem}: {article['article_id']} start page is not first")

        roles = {entry["page"]: entry["role"] for entry in article_map["pages"]}
        for page, owners in held.items():
            if roles.get(page) == article_builder.ROLE_UNASSIGNED:
                absorbed.append(f"{stem}: page {page} is in {owners} and unassigned")

        checkpoint = checkpoint_of(run["grouped"].working_dir, "chain_builder")
        if checkpoint is not None:
            document = read_checkpoint(checkpoint)
            owner_of = {
                page: article["article_id"]
                for article in article_map["articles"]
                for page in article["pages"]
            }
            chains: dict[str, set[str | None]] = {}
            for index, page in enumerate(document.page):
                for paragraph in page.pdf_paragraph:
                    if paragraph.chain_id:
                        chains.setdefault(paragraph.chain_id, set()).add(
                            owner_of.get(index + 1)
                        )
            for chain_id, owners in chains.items():
                if len(owners) > 1:
                    crossing.append(
                        f"{stem}/{chain_id}: spans {sorted(map(str, owners))}"
                    )
            declared = set(heading_labels())
            for article in article_map["articles"]:
                title = article["title"]
                if title is None:
                    continue
                if title["layout_label"] not in declared:
                    titles.append(f"{stem}: {title['layout_label']} is not a heading")
                start = document.page[article["start_page"] - 1]
                expected = article_builder.title_paragraph(start, heading_labels())
                if expected is None or expected.debug_id != title["debug_id"]:
                    titles.append(
                        f"{stem}: {article['article_id']} title is not the first "
                        f"heading on its opening page"
                    )

        table.append(
            {
                "sample": stem,
                "articles": [
                    {
                        "article_id": article["article_id"],
                        "pages": article["pages"],
                        "title": (article["title"] or {}).get("text"),
                        "merged_by_chain": article["merged_by_chain"],
                        "chains": article["chains"],
                    }
                    for article in article_map["articles"]
                ],
                "unassigned": article_map["unassigned"],
                "pages": article_map["pages"],
            }
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "article_map.corpus.json").write_text(
        json.dumps(table, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    record(
        "04a every page is in exactly one article or in none",
        not partition and bool(table),
        f"samples={len(table)} problems={partition[:3]}",
    )
    record("04b no chain crosses an article", not crossing, f"problems={crossing[:3]}")
    record(
        "04c nothing belonging to no article appears inside one",
        not absorbed,
        f"problems={absorbed[:3]}",
    )
    record(
        "04d article ids are unique and page lists are ordered",
        not identity,
        f"problems={identity[:3]}",
    )
    record(
        "04e every title reference is the first declared heading on its opening page",
        not titles,
        f"problems={titles[:3]}",
    )


# --- 05 the instance ---------------------------------------------------------


def check_05_instance() -> None:
    """Positive 5: on the sample the defect was found on, furniture stands apart.

    Pages 1 to 3 are the cover, the colophon and the contents page: none is
    declared an opener and none carries text a chain may run through, so each
    belongs to no article. Page 4 is the first page that does, and with no
    opener declared before it, it opens the first article rather than joining
    the contents page as it did while one flag answered both questions.
    """
    name = "05 the furniture pages stand apart and the first feature page opens"
    stem = instance_stem()
    run = runs().get(stem) if stem else None
    if run is None or run["map"] is None:
        skip(name, f"no {INSTANCE_PUBLICATION} sample is in the corpus")
        return
    article_map = run["map"]
    unassigned = [entry["page"] for entry in article_map["unassigned"]]
    starts = [article["start_page"] for article in article_map["articles"]]
    record(
        name,
        all(page in unassigned for page in INSTANCE_UNASSIGNED)
        and bool(starts)
        and min(starts) == INSTANCE_FIRST_START,
        f"unassigned={unassigned} start_pages={starts}",
    )


# --- 06 the switch -----------------------------------------------------------


def check_06a_switch() -> None:
    """Negative 6a: the switch exists, defaults to off, and is the only way in."""
    import inspect

    from babeldoc.format.pdf.translation_config import TranslationConfig

    parameter = inspect.signature(TranslationConfig.__init__).parameters.get(
        "magazine_article_group"
    )
    source = (ROOT / HIGH_LEVEL).read_text(encoding="utf-8")
    gated = re.search(
        r"if translation_config\.magazine_article_group:\s*\n\s*ArticleBuilder\(",
        source,
    )
    record(
        "06a the switch exists, defaults to False, and is the only way in",
        parameter is not None
        and parameter.default is False
        and gated is not None
        and source.count("ArticleBuilder(") == 1,
        f"default={parameter.default if parameter else 'absent'} gated={bool(gated)}",
    )


def check_06b_sidecar() -> None:
    """Negative 6b: no map with the switch down, one with it up."""
    leaked = [
        stem
        for stem, run in runs().items()
        if (run["chained"].working_dir / REPORT_NAME).exists()
    ]
    missing = [stem for stem, run in runs().items() if run["map"] is None]
    record(
        "06b the map appears only with the switch up",
        not leaked and not missing and bool(runs()),
        f"leaked={leaked} missing={missing}",
    )


def check_06c_zero_difference() -> None:
    """Negative 6c: the stage hands back the document it was given.

    Stated inside one document rather than between two pipeline runs: paragraph
    debug ids are drawn at random, so two runs of one sample differ whatever any
    stage does. The document a real run produced is serialised, put through the
    stage, and serialised again.
    """
    from babeldoc.magazine.article_builder import ArticleBuilder

    converter = XMLConverter()
    problems: list[str] = []
    checked = 0
    for stem, run in runs().items():
        checkpoint = checkpoint_of(run["grouped"].working_dir, "chain_builder")
        if checkpoint is None:
            problems.append(f"{stem}: no checkpoint to run the stage over")
            continue
        document = read_checkpoint(checkpoint)
        before = converter.to_xml(document)
        work = WorkingDir(_tmp_root / f"stage.{stem}")
        ArticleBuilder(work).process(document)
        if converter.to_xml(document) != before:
            problems.append(f"{stem}: the stage changed the document")
        if not (work.directory / REPORT_NAME).exists():
            problems.append(f"{stem}: the stage wrote no map")
        checked += 1
    record(
        "06c the stage writes a map and leaves the document untouched",
        not problems and checked > 0,
        f"samples={checked} problems={problems[:3]}",
    )


def check_06d_conservation() -> None:
    """Negative 6d: the run with the switch up carries what the run without does."""
    problems: list[str] = []
    compared = 0
    for stem, run in runs().items():
        left = checkpoint_of(run["chained"].working_dir, "typesetting")
        right = checkpoint_of(run["grouped"].working_dir, "typesetting")
        if left is None or right is None:
            problems.append(f"{stem}: no typesetting checkpoint either side")
            continue
        before, after = read_checkpoint(left), read_checkpoint(right)
        compared += 1
        if len(before.page) != len(after.page):
            problems.append(f"{stem}: {len(before.page)} pages became {len(after.page)}")
            continue
        for index, (page_a, page_b) in enumerate(
            zip(before.page, after.page, strict=True)
        ):
            if len(page_a.pdf_paragraph) != len(page_b.pdf_paragraph):
                problems.append(f"{stem}: paragraph count moved on page {index + 1}")
            texts_a = [p.unicode for p in page_a.pdf_paragraph]
            texts_b = [p.unicode for p in page_b.pdf_paragraph]
            if texts_a != texts_b:
                problems.append(f"{stem}: paragraph text moved on page {index + 1}")
    record(
        "06d the switch changes no page, paragraph or text the pipeline produces",
        not problems and compared > 0,
        f"samples={compared} problems={problems[:3]}",
    )


# --- 07 determinism ----------------------------------------------------------


def check_07a_synthetic_determinism() -> None:
    """Positive 7a: the same document groups the same way twice."""
    kinds = [KIND_OPENS, KIND_MEMBER, KIND_FURNITURE, KIND_MEMBER, KIND_OPENS]
    _, first = group(kinds)
    _, second = group(kinds)
    ids = {article.article_id for article in first.articles} | {
        article.article_id for article in second.articles
    }
    record(
        "07a the grouping is the same twice over, the ids being fresh each time",
        page_sets(first) == page_sets(second)
        and unassigned_pages(first) == unassigned_pages(second)
        and len(ids) == len(first.articles) + len(second.articles),
        f"first={page_sets(first)} second={page_sets(second)}",
    )


def check_07b_corpus_determinism() -> None:
    """Positive 7b: regrouping a produced document reproduces its map."""
    problems: list[str] = []
    checked = 0
    labels = heading_labels()
    taxonomy = taxonomy_module.load_taxonomy()
    for stem, run in runs().items():
        checkpoint = checkpoint_of(run["grouped"].working_dir, "chain_builder")
        if checkpoint is None or run["map"] is None:
            continue
        checked += 1
        regrouped = article_builder.build_articles(
            read_checkpoint(checkpoint), taxonomy.policy_of, labels
        )
        expected = [article["pages"] for article in run["map"]["articles"]]
        if page_sets(regrouped) != expected:
            problems.append(f"{stem}: {page_sets(regrouped)} != {expected}")
        if unassigned_pages(regrouped) != [
            entry["page"] for entry in run["map"]["unassigned"]
        ]:
            problems.append(f"{stem}: the unassigned set moved")
    record(
        "07b regrouping the produced document reproduces the map",
        not problems and checked > 0,
        f"samples={checked} problems={problems[:3]}",
    )


# --- 08 the change scope -----------------------------------------------------


def check_08_scope() -> None:
    """Negative 8: the session stays inside its scope and the stage stays pure."""
    changed = changed_files()
    outside = sorted(
        path
        for path in changed
        if path not in ALLOWED_FILES
        and path not in ALLOWED_UPSTREAM
        and not path.startswith(ALLOWED_PREFIXES)
    )
    record(
        "08a this session changes only the paths PLAN_B6 allows",
        not outside and bool(changed),
        f"changed={len(changed)} outside={outside}",
    )

    upstream = sorted(
        path
        for path in changed
        if path not in PROJECT_OWNED_FILES
        and not path.startswith(PROJECT_OWNED_PREFIXES)
    )
    registry = (ROOT / "UPSTREAM_DIFF.md").read_text(encoding="utf-8")
    unregistered = [path for path in upstream if path not in registry]
    record(
        "08b the upstream files touched are a subset of the three PLAN_B6 names",
        set(upstream) <= ALLOWED_UPSTREAM and not unregistered,
        f"upstream={upstream} unregistered={unregistered}",
    )

    module = ROOT / MODULE
    text = module.read_text(encoding="utf-8")
    named = [
        name
        for name in taxonomy_module.load_taxonomy().names()
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text)
    ]
    record("08c the grouping module names no page type", not named, f"named={named}")

    record(
        "08d the grouping module never reads the chain detector's prior",
        CHAIN_PRIOR_FLAG not in code_strings(module),
        f"flag={CHAIN_PRIOR_FLAG}",
    )

    written = sorted(set(assigned_attributes(module)) & set(IL_FIELD_NAMES))
    record(
        "08e the grouping module writes nothing into the intermediate language",
        not written,
        f"written={written}",
    )

    cjk: list[str] = []
    for relative in CJK_SCAN_FILES:
        path = ROOT / relative
        if not path.is_file():
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if has_cjk(line):
                cjk.append(f"{relative}:{number}")
    _, diff = git_output(["diff", "-U0", BASE_TAG, "--", *sorted(ALLOWED_UPSTREAM)])
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++") and has_cjk(line):
            cjk.append(f"added upstream line: {line.strip()}")
    record(
        "08f no CJK characters in the code this session adds",
        not cjk,
        f"offenders={cjk[:5]}",
    )

    # The map is a sidecar. Declaring an article on a paragraph or a page would
    # need a schema change, which the freeze forbids until W-B1-01 lifts.
    schema = (ROOT / SCHEMA).read_text(encoding="utf-8")
    record(
        "08g the article map stays out of the intermediate language schema",
        "article" not in schema.lower(),
        "",
    )


# --- 09 sweep ----------------------------------------------------------------


def check_09_sweep() -> None:
    name = "09 the full run_all sweep is green"
    if NESTED_SUPPRESSED:
        print(f"SKIPPED: nested run suppressed :: {name}")
        return
    proc = subprocess.run(  # noqa: S603 - fixed argv built from repository paths
        [PYTHON, str(ROOT / "spec_checks" / "run_all.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "run_all.full.log").write_text(proc.stdout, encoding="utf-8")
    failures = [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip().startswith("[FAIL]")
    ]
    record(
        name,
        proc.returncode == 0 and not failures,
        f"exit={proc.returncode} failures={failures[:5]}",
    )


def main() -> int:
    logging.basicConfig(level=logging.ERROR)

    check_01_declaration()
    check_02_flag_independence()
    check_03_synthetic_walk()
    check_06a_switch()
    check_07a_synthetic_determinism()

    if harness.FAST_TIER:
        for name in PIPELINE_TIER:
            harness.fast_skip(name)
    else:
        with _timer.phase("pipeline runs"):
            runs()
        check_04_corpus_structure()
        check_05_instance()
        check_06b_sidecar()
        check_06c_zero_difference()
        check_06d_conservation()
        check_07b_corpus_determinism()

    check_08_scope()
    check_09_sweep()

    failed = [name for name, ok, _ in _results if not ok]
    print()
    artifacts.write_stats("spec_check_b6")
    artifacts.print_stats("spec_check_b6")
    _timer.write()
    _timer.print_summary()
    print(f"spec_check_b6: {len(_results) - len(failed)}/{len(_results)} passed")
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
