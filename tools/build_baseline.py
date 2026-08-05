"""Produce the B0 baseline artefacts for every sample in corpus/manifest.json.

Each sample is dry-run through the pipeline with ``only_parse_generate_pdf``
(no translation stage, no API key) and ``magazine_checkpoint`` enabled. The
resulting mono PDF is frozen at ``examples/output/baseline/<name>.b0.pdf`` and
its IL checkpoints at ``examples/output/baseline/<name>.checkpoints/``. The
manifest is updated in place with the baseline paths and hashes.

Usage:
    python tools/build_baseline.py [--sample basic-en.pdf ...]
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
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.checkpoint import CHECKPOINT_PREFIX  # noqa: E402

logger = logging.getLogger(__name__)

INPUT_DIR = ROOT / "examples" / "input"
BASELINE_DIR = ROOT / "examples" / "output" / "baseline"
MANIFEST_PATH = ROOT / "corpus" / "manifest.json"
BASELINE_SUFFIX = ".b0.pdf"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_one(pdf: Path, name: str) -> tuple[Path, Path]:
    stage_dir = BASELINE_DIR / "_staging" / name
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    config = TranslationConfig(
        translator=None,
        input_file=pdf,
        lang_in="en",
        lang_out="zh",
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
    baseline_pdf = BASELINE_DIR / f"{name}{BASELINE_SUFFIX}"
    shutil.copyfile(result.mono_pdf_path, baseline_pdf)

    checkpoint_dir = BASELINE_DIR / f"{name}.checkpoints"
    if checkpoint_dir.exists():
        shutil.rmtree(checkpoint_dir)
    checkpoint_dir.mkdir(parents=True)
    work_dir = Path(config.working_dir)
    copied = 0
    for item in sorted(work_dir.glob(f"{CHECKPOINT_PREFIX}*")):
        shutil.copyfile(item, checkpoint_dir / item.name)
        copied += 1
    if copied == 0:
        raise RuntimeError(f"{name}: no checkpoint files produced in {work_dir}")

    shutil.rmtree(stage_dir.parent, ignore_errors=True)
    return baseline_pdf, checkpoint_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="append", default=None)
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
        baseline_pdf, checkpoint_dir = build_one(pdf, name)
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
