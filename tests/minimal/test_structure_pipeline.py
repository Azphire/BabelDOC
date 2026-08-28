from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.magazine import minimal_pipeline
from babeldoc.magazine import vlm_client as vlm_client_module
from babeldoc.magazine.article_builder import UNSUPPORTED_SAME_PAGE_MULTI_ARTICLE
from babeldoc.magazine.article_ir import ArticleDocumentIR

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_TEMP = ROOT / ".runtime" / "temp"
TAIL_TEXT = "the sentence continues past the foot of this page and"
HEAD_TEXT = "resumes here at the head of the next one without a break"
PAGE_WIDTH = 600.0
PAGE_HEIGHT = 800.0
CHAR_WIDTH = 5.0


class StubConfig:
    def __init__(self, working_dir: Path):
        self.working_dir = working_dir
        self.input_file = str(ROOT / "examples" / "input" / "Courier-en.pdf")
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
        prefix="m1-structure-",
        dir=RUNTIME_TEMP,
    ) as temp_dir:
        yield Path(temp_dir)


def _empty_ir() -> ArticleDocumentIR:
    return ArticleDocumentIR(
        articles=(),
        by_page={},
        by_element={},
        by_chain={},
    )


def _paragraph(
    text: str,
    debug_id: str,
    *,
    left: float,
    bottom: float,
    rows: int = 2,
    label: str = "plain text",
) -> il_version_1.PdfParagraph:
    characters = []
    for row in range(rows):
        y = bottom + (rows - 1 - row) * 20.0
        for column, character in enumerate(text):
            characters.append(
                il_version_1.PdfCharacter(
                    char_unicode=character if row == rows - 1 else "x",
                    box=il_version_1.Box(
                        x=left + column * CHAR_WIDTH,
                        y=y,
                        x2=left + (column + 1) * CHAR_WIDTH,
                        y2=y + 10.0,
                    ),
                )
            )
    return il_version_1.PdfParagraph(
        box=il_version_1.Box(
            x=left,
            y=bottom,
            x2=left + len(text) * CHAR_WIDTH,
            y2=bottom + (rows - 1) * 20.0 + 10.0,
        ),
        pdf_style=il_version_1.PdfStyle(font_id="F0", font_size=10.0),
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_characters=il_version_1.PdfSameStyleCharacters(
                    pdf_character=characters
                )
            )
        ],
        unicode=text,
        debug_id=debug_id,
        layout_label=label,
    )


def _page(
    number: int,
    paragraphs: list[il_version_1.PdfParagraph],
    *,
    page_kind: str | None = None,
) -> il_version_1.Page:
    box = il_version_1.Box(x=0.0, y=0.0, x2=PAGE_WIDTH, y2=PAGE_HEIGHT)
    return il_version_1.Page(
        mediabox=il_version_1.Mediabox(box=box),
        cropbox=il_version_1.Cropbox(box=box),
        pdf_font=[il_version_1.PdfFont(font_id="F0", name="ABCDEF+Test-Regular")],
        pdf_paragraph=paragraphs,
        base_operations=il_version_1.BaseOperations(value=""),
        page_number=number,
        unit="point",
        page_kind=page_kind,
        page_kind_conf=1.0 if page_kind else None,
    )


def _chain_document() -> il_version_1.Document:
    return il_version_1.Document(
        page=[
            _page(
                0,
                [_paragraph(TAIL_TEXT, "tail", left=50.0, bottom=100.0)],
            ),
            _page(
                1,
                [_paragraph(HEAD_TEXT, "head", left=50.0, bottom=680.0)],
            ),
        ],
        total_pages=2,
    )


def _force_article_body(_classifier, docs) -> il_version_1.Document:
    for page in docs.page:
        page.page_kind = "article_body"
        page.page_kind_conf = 1.0
        page.page_kind_source = "test-deterministic"
    return docs


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


def _assert_chain_and_owner_invariants(
    docs: il_version_1.Document,
    document_ir: ArticleDocumentIR,
) -> None:
    raw_chains: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for page_index, page in enumerate(docs.page):
        for paragraph_index, paragraph in enumerate(page.pdf_paragraph):
            if paragraph.chain_id is None:
                continue
            assert paragraph.chain_index is not None
            source_ref = f"p{page_index + 1}#{paragraph_index}"
            raw_chains[paragraph.chain_id].append((paragraph.chain_index, source_ref))

    assert raw_chains
    all_members = []
    for members in raw_chains.values():
        members.sort()
        assert [index for index, _source_ref in members] == list(range(len(members)))
        all_members.extend(source_ref for _index, source_ref in members)

    assert len(all_members) == len(set(all_members))
    for source_ref in all_members:
        canonical_chain = document_ir.by_chain_member[source_ref]
        assert document_ir.by_element[source_ref] == document_ir.by_chain[canonical_chain]


def test_fixed_stage_order_and_single_canonical_identity(
    monkeypatch: pytest.MonkeyPatch,
    runtime_work_dir: Path,
) -> None:
    events = []
    expected_ir = _empty_ir()

    class FakePageClassifier:
        vlm_enabled = False

        def __init__(self, _config):
            events.append("PageClassifier:init")

        def process(self, docs):
            events.append("PageClassifier:process")
            return docs

    class FakeChainBuilder:
        def __init__(self, _config):
            events.append("ChainBuilder:init")

        def process(self, docs):
            events.append("ChainBuilder:process")
            return docs

    class FakeArticleBuilder:
        def __init__(self, _config):
            events.append("ArticleBuilder:init")

        def process(self, _docs):
            events.append("ArticleBuilder:process")
            return expected_ir

    monkeypatch.setattr(minimal_pipeline, "PageClassifier", FakePageClassifier)
    monkeypatch.setattr(minimal_pipeline, "ChainBuilder", FakeChainBuilder)
    monkeypatch.setattr(minimal_pipeline, "ArticleBuilder", FakeArticleBuilder)

    config = StubConfig(runtime_work_dir)
    docs = il_version_1.Document(page=[], total_pages=0)
    minimal_pipeline.configure(config)
    result = minimal_pipeline.after_styles(config, docs)

    assert events == [
        "PageClassifier:init",
        "PageClassifier:process",
        "ChainBuilder:init",
        "ChainBuilder:process",
        "ArticleBuilder:init",
        "ArticleBuilder:process",
    ]
    assert result is expected_ir
    assert minimal_pipeline.get_article_document_ir(config) is expected_ir
    assert config.magazine_state.article_document_ir is expected_ir
    assert config.magazine_state.structure_document_identity == id(docs)

    with pytest.raises(
        minimal_pipeline.MinimalPipelineStateError,
        match="already attempted",
    ):
        minimal_pipeline.after_styles(config, docs)
    assert minimal_pipeline.get_article_document_ir(config) is expected_ir
    assert events[-1] == "ArticleBuilder:process"


def test_real_chain_members_have_stable_refs_and_one_owner(
    monkeypatch: pytest.MonkeyPatch,
    runtime_work_dir: Path,
) -> None:
    monkeypatch.setattr(
        minimal_pipeline.PageClassifier,
        "process",
        _force_article_body,
    )

    observed_refs = []
    observed_article_ids = []
    for run in range(2):
        config = StubConfig(runtime_work_dir / f"run-{run}")
        docs = _chain_document()
        minimal_pipeline.configure(config)
        document_ir = minimal_pipeline.after_styles(config, docs)

        _assert_chain_and_owner_invariants(docs, document_ir)
        assert minimal_pipeline.get_article_document_ir(config) is document_ir
        assert len(document_ir.articles) == 1
        assert set(document_ir.by_element) == {"p1#0", "p2#0"}
        observed_refs.append(tuple(document_ir.by_element))
        observed_article_ids.append(document_ir.articles[0].article_id)
        assert (config.working_dir / "chain_report.json").is_file()
        assert (config.working_dir / "article_map.json").is_file()
        assert (config.working_dir / "article_ir.json").is_file()

    assert observed_refs[0] == observed_refs[1]
    assert observed_article_ids[0] == observed_article_ids[1]


def test_unsupported_multi_article_and_unknown_kind_are_protected(
    monkeypatch: pytest.MonkeyPatch,
    runtime_work_dir: Path,
) -> None:
    def preserve_kinds(_classifier, docs):
        return docs

    monkeypatch.setattr(
        minimal_pipeline.PageClassifier,
        "process",
        preserve_kinds,
    )
    multi_article_page = _page(
        0,
        [
            _paragraph(
                "Left feature.",
                "left-title",
                left=50.0,
                bottom=680.0,
                rows=1,
                label="title",
            ),
            _paragraph(
                "Right feature.",
                "right-title",
                left=350.0,
                bottom=680.0,
                rows=1,
                label="title",
            ),
        ],
        page_kind="article_opener",
    )
    unknown_page = _page(
        1,
        [_paragraph("Unknown page.", "unknown", left=50.0, bottom=680.0)],
        page_kind="not-in-taxonomy",
    )
    docs = il_version_1.Document(
        page=[multi_article_page, unknown_page],
        total_pages=2,
    )
    config = StubConfig(runtime_work_dir)
    minimal_pipeline.configure(config)

    document_ir = minimal_pipeline.after_styles(config, docs)

    unsupported = {item.page: item for item in document_ir.unsupported_pages}
    assert unsupported[1].reason == UNSUPPORTED_SAME_PAGE_MULTI_ARTICLE
    assert unsupported[1].evidence_refs == ("p1#0", "p1#1")
    assert document_ir.article_for_page(2) is None
    assert 2 not in document_ir.by_page
    assert all(slot.page != 1 for article in document_ir.articles for slot in article.slots)


def test_vlm_disabled_path_never_enters_client_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
    runtime_work_dir: Path,
) -> None:
    _trap_model_paths(monkeypatch)
    config_file = ROOT / "configs" / "vlm.json"
    assert json.loads(config_file.read_text(encoding="utf-8"))["enabled"] is False

    config = StubConfig(runtime_work_dir)
    docs = il_version_1.Document(
        page=[_page(0, [], page_kind=None)],
        total_pages=1,
    )
    minimal_pipeline.configure(config)
    document_ir = minimal_pipeline.after_styles(config, docs)

    report = json.loads(
        (config.working_dir / "page_classify.report.json").read_text(encoding="utf-8")
    )
    assert report["vlm_enabled"] is False
    assert all(page["vlm"] is None for page in report["pages"])
    assert minimal_pipeline.get_article_document_ir(config) is document_ir


def test_enabled_vlm_is_rejected_before_classifier_process(
    monkeypatch: pytest.MonkeyPatch,
    runtime_work_dir: Path,
) -> None:
    process_called = False

    class EnabledClassifier:
        vlm_enabled = True

        def __init__(self, _config):
            pass

        def process(self, docs):
            nonlocal process_called
            process_called = True
            return docs

    monkeypatch.setattr(minimal_pipeline, "PageClassifier", EnabledClassifier)
    config = StubConfig(runtime_work_dir)
    minimal_pipeline.configure(config)

    with pytest.raises(
        minimal_pipeline.MinimalPipelineStateError,
        match="VLM page classification must remain disabled",
    ):
        minimal_pipeline.after_styles(
            config,
            il_version_1.Document(page=[], total_pages=0),
        )

    assert process_called is False
    assert config.magazine_state.article_document_ir is None
