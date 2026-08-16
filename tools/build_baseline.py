"""Produce the baseline artefacts for every sample in corpus/manifest.json.

Each sample is dry-run through the pipeline with ``only_parse_generate_pdf``
(no translation stage, no API key) and ``magazine_checkpoint`` enabled. The
resulting mono PDF is frozen at ``examples/output/baseline/<name><suffix>`` and
its IL checkpoints in the archive
``examples/output/baseline/<name>.checkpoints.zip``. The manifest names the
directory the archive stands for, and every reader resolves one to the other. The
manifest is updated in place with the baseline paths and hashes. The suffix
carries the batch that froze the corpus, so a corpus swap is visible in the
artefact names; gates read the path from the manifest and never spell it out.

Usage:
    python tools/build_baseline.py [--sample Courier-en.pdf ...] [--suffix .b2_2.pdf]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from babeldoc.format.pdf import high_level  # noqa: E402
from babeldoc.format.pdf.parse_shared import _ParseOnlyDocLayoutModel  # noqa: E402
from babeldoc.format.pdf.translation_config import TranslationConfig  # noqa: E402
from babeldoc.format.pdf.translation_config import WatermarkOutputMode  # noqa: E402
from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import CHECKPOINT_ARCHIVE_SUFFIX  # noqa: E402
from babeldoc.magazine.checkpoint import CHECKPOINT_PREFIX  # noqa: E402
from babeldoc.magazine.checkpoint import write_checkpoint_archive  # noqa: E402

logger = logging.getLogger(__name__)

INPUT_DIR = ROOT / "examples" / "input"
BASELINE_DIR = ROOT / "examples" / "output" / "baseline"
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
BASELINE_SUFFIX = ".b2_2.pdf"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_one(pdf: Path, name: str, suffix: str = BASELINE_SUFFIX) -> tuple[Path, Path]:
    stage_dir = BASELINE_DIR / "_staging" / name
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    source_lang, target_lang = corpus.direction_of(name)
    config = TranslationConfig(
        translator=None,
        input_file=pdf,
        lang_in=source_lang,
        lang_out=target_lang,
        doc_layout_model=_ParseOnlyDocLayoutModel(),
        output_dir=stage_dir / "out",
        working_dir=stage_dir / "work",
        watermark_output_mode=WatermarkOutputMode.NoWatermark,
        no_dual=True,
        auto_extract_glossary=False,
        only_parse_generate_pdf=True,
        magazine_checkpoint=True,
    )
    result = high_level.translate(config)
    if result is None or result.mono_pdf_path is None:
        raise RuntimeError(f"{name}: dry run produced no mono PDF")

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    baseline_pdf = BASELINE_DIR / f"{name}{suffix}"
    shutil.copyfile(result.mono_pdf_path, baseline_pdf)

    checkpoint_dir = BASELINE_DIR / f"{name}.checkpoints"
    archive = checkpoint_dir.with_name(
        checkpoint_dir.name + CHECKPOINT_ARCHIVE_SUFFIX
    )
    if checkpoint_dir.exists():
        shutil.rmtree(checkpoint_dir)
    if archive.exists():
        archive.unlink()
    work_dir = Path(config.working_dir)
    staged = sorted(work_dir.glob(f"{CHECKPOINT_PREFIX}*"))
    if not staged:
        raise RuntimeError(f"{name}: no checkpoint files produced in {work_dir}")
    # Kept as one archive: a baseline is read whole and never edited, and the
    # XML of one run compresses by about an order of magnitude.
    write_checkpoint_archive(staged, archive)

    shutil.rmtree(stage_dir.parent, ignore_errors=True)
    return baseline_pdf, checkpoint_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="append", default=None)
    parser.add_argument("--suffix", default=BASELINE_SUFFIX)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    use_project_cache(ROOT)

    with MANIFEST_PATH.open(encoding="utf-8") as f:
        manifest = json.load(f)

    for entry in manifest["samples"]:
        rel = entry["file"]
        if args.sample and rel not in args.sample:
            continue
        pdf = INPUT_DIR / rel
        name = Path(rel).stem
        baseline_pdf, checkpoint_dir = build_one(pdf, name, args.suffix)
        entry["baseline"] = {
            "pdf": baseline_pdf.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(baseline_pdf),
            "checkpoints": checkpoint_dir.relative_to(ROOT).as_posix(),
        }
        print(f"{rel}: baseline -> {entry['baseline']['pdf']}")

    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
