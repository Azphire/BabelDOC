from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import minimal_pipeline
from babeldoc.magazine import vlm_client as vlm_client_module
from babeldoc.magazine.article_ir import ArticleDocumentIR

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_TEMP = ROOT / ".runtime" / "temp"
SAMPLE = ROOT / "examples" / "input" / "Courier-en.pdf"
REPORTS = (
    "page_classify.report.json",
    "chain_report.json",
    "article_map.json",
    "article_ir.json",
)


class StubConfig:
    def __init__(self, working_dir: Path):
        self.working_dir = working_dir
        self.input_file = str(SAMPLE)
        self.split_strategy = None

    def get_working_file_path(self, name: str) -> str:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        return str(self.working_dir / name)


class CredentialEnvironmentTrap(dict[str, str]):
    def get(self, key: str, default=None):
        raise AssertionError(f"credential environment was queried: {key}")


@pytest.fixture
def runtime_work_dir():
    with tempfile.TemporaryDirectory(
        prefix="m1-real-pdf-",
        dir=RUNTIME_TEMP,
    ) as temp_dir:
        yield Path(temp_dir)


def _trap_model_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("VLM/model path was entered")

    monkeypatch.setattr(
        vlm_client_module,
        "os",
        SimpleNamespace(environ=CredentialEnvironmentTrap()),
    )
    monkeypatch.setattr(vlm_client_module, "read_api_key", forbidden)
    monkeypatch.setattr(vlm_client_module, "build_openai_client", forbidden)
    monkeypatch.setattr(
        vlm_client_module.OpenAICompatibleTransport,
        "complete",
        forbidden,
    )


def _page_from_pdf(source_page, source_index: int) -> il_version_1.Page:
    width = float(source_page.rect.width)
    height = float(source_page.rect.height)
    paragraphs = []
    for block_index, block in enumerate(source_page.get_text("blocks", sort=True)):
        x, y, x2, y2, text, *_rest = block
        if len(block) > 6 and block[6] != 0:
            continue
        normalized = " ".join(str(text).split())
        if not normalized:
            continue
        paragraphs.append(
            il_version_1.PdfParagraph(
                box=il_version_1.Box(
                    x=float(x),
                    y=height - float(y2),
                    x2=float(x2),
                    y2=height - float(y),
                ),
                pdf_style=il_version_1.PdfStyle(
                    font_id="courier-real-page",
                    font_size=10.0,
                ),
                unicode=normalized,
                debug_id=f"source-page-{source_index + 1}-block-{block_index}",
                layout_label="plain text",
            )
        )
    frame = il_version_1.Box(x=0.0, y=0.0, x2=width, y2=height)
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=frame),
        cropbox=il_version_1.Cropbox(box=frame),
        pdf_font=[
            il_version_1.PdfFont(
                font_id="courier-real-page",
                name="Courier-Real-Sample",
            )
        ],
        pdf_paragraph=paragraphs,
        base_operations=il_version_1.BaseOperations(value=""),
        page_number=source_index,
        unit="point",
    )


def _sample_pages_seven_and_eight() -> il_version_1.Document:
    assert SAMPLE.is_file()
    with pymupdf.open(SAMPLE) as source:
        assert source.page_count >= 8
        pages = [_page_from_pdf(source[index], index) for index in (6, 7)]
        total_pages = source.page_count
    assert all(page.pdf_paragraph for page in pages)
    return il_version_1.Document(page=pages, total_pages=total_pages)


def _assert_ir_invariants(document_ir: ArticleDocumentIR) -> None:
    source_refs = [
        element.source_ref
        for article in document_ir.articles
        for element in article.elements
    ]
    assert len(source_refs) == len(set(source_refs))
    assert set(source_refs) == set(document_ir.by_element)
    assert set(document_ir.by_page.values()) <= {
        article.article_id for article in document_ir.articles
    }
    assert set(document_ir.by_chain.values()) <= {
        article.article_id for article in document_ir.articles
    }
    for source_ref, chain_id in document_ir.by_chain_member.items():
        assert source_ref in document_ir.by_element
        assert chain_id in document_ir.by_chain


def test_courier_pages_seven_and_eight_build_offline_structure(
    monkeypatch: pytest.MonkeyPatch,
    runtime_work_dir: Path,
) -> None:
    _trap_model_paths(monkeypatch)
    docs = _sample_pages_seven_and_eight()
    config = StubConfig(runtime_work_dir)
    minimal_pipeline.configure(config)

    document_ir = minimal_pipeline.after_styles(config, docs)

    assert isinstance(document_ir, ArticleDocumentIR)
    assert minimal_pipeline.get_article_document_ir(config) is document_ir
    assert config.magazine_state.article_document_ir is document_ir
    assert [page.page_number for page in docs.page] == [6, 7]
    assert all(page.page_kind is not None for page in docs.page)
    _assert_ir_invariants(document_ir)

    for report_name in REPORTS:
        assert (config.working_dir / report_name).is_file()
    classifier_report = json.loads(
        (config.working_dir / REPORTS[0]).read_text(encoding="utf-8")
    )
    assert classifier_report["vlm_enabled"] is False
    assert len(classifier_report["pages"]) == 2
    assert all(record["vlm"] is None for record in classifier_report["pages"])
