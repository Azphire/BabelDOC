"""Atomic touched-page snapshots shared by flow and repair passes."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import fields
from dataclasses import is_dataclass

from babeldoc.format.pdf.document_il.il_version_1 import Box
from babeldoc.magazine import fixed_assets
from babeldoc.magazine.run_trace import hash_record


class TransactionRestoreError(RuntimeError):
    """Raised when restored state does not match the transaction baseline."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _page_xml_digests(docs, positions: tuple[int, ...]) -> str:
    try:
        from lxml import etree

        from babeldoc.magazine.checkpoint import to_checkpoint_xml
    except ModuleNotFoundError:
        return hash_record(
            [
                (position, fixed_assets.content_digest(docs.page[position]))
                for position in positions
            ]
        )
    root = etree.fromstring(to_checkpoint_xml(docs).encode("utf-8"))
    pages = root.findall("page")
    return hash_record(
        [
            (position, _sha256(etree.tostring(pages[position])))
            for position in positions
        ]
    )


def _geometry(node, path: str, seen: set[int], output: list) -> None:
    if node is None or isinstance(node, str | bytes | int | float | bool):
        return
    identity = id(node)
    if identity in seen:
        return
    seen.add(identity)
    if isinstance(node, Box):
        output.append(
            (
                path,
                getattr(node, "x", None),
                getattr(node, "y", None),
                getattr(node, "x2", None),
                getattr(node, "y2", None),
            )
        )
        return
    if is_dataclass(node):
        for item in fields(node):
            _geometry(getattr(node, item.name), f"{path}.{item.name}", seen, output)
        return
    if isinstance(node, dict):
        for key in sorted(node, key=str):
            _geometry(node[key], f"{path}[{key!r}]", seen, output)
        return
    if isinstance(node, list | tuple):
        for index, item in enumerate(node):
            _geometry(item, f"{path}[{index}]", seen, output)


def _geometry_digest(docs, positions: tuple[int, ...]) -> str:
    output = []
    seen: set[int] = set()
    for position in positions:
        _geometry(docs.page[position], f"page[{position}]", seen, output)
    return hash_record(output)


def _drop_cap_digest(docs, positions: tuple[int, ...]) -> str:
    rows = []
    for position in positions:
        for index, paragraph in enumerate(docs.page[position].pdf_paragraph or ()):
            rows.append(
                (
                    position,
                    index,
                    getattr(paragraph, "drop_cap_candidate", None),
                    getattr(paragraph, "drop_cap_decision", None),
                )
            )
    return hash_record(rows)


def _allocator_digest(value) -> str | None:
    return None if value is None else fixed_assets.content_digest(value)


@dataclass(frozen=True, slots=True)
class TransactionDigests:
    xml: str
    geometry: str
    drop_cap_intent: str
    run_trace: str | None
    fixed_assets: str | None
    allocator: str | None

    def as_record(self) -> dict:
        return {
            "xml": self.xml,
            "geometry": self.geometry,
            "drop_cap_intent": self.drop_cap_intent,
            "run_trace": self.run_trace,
            "fixed_assets": self.fixed_assets,
            "allocator": self.allocator,
        }


def state_digests(
    docs,
    positions: Iterable[int],
    *,
    run_trace=None,
    fixed_inventory=None,
    allocator=None,
) -> TransactionDigests:
    selected = tuple(sorted({int(position) for position in positions}))
    return TransactionDigests(
        xml=_page_xml_digests(docs, selected),
        geometry=_geometry_digest(docs, selected),
        drop_cap_intent=_drop_cap_digest(docs, selected),
        run_trace=(None if run_trace is None else run_trace.transaction_digest()),
        fixed_assets=(
            None
            if fixed_inventory is None
            else hash_record(fixed_inventory.to_record())
        ),
        allocator=(
            run_trace.transaction_allocator_digest()
            if allocator is None and run_trace is not None
            else _allocator_digest(allocator)
        ),
    )


def _restore_allocator(target, snapshot) -> None:
    if target is None:
        return
    restored = copy.deepcopy(snapshot)
    if isinstance(target, dict):
        target.clear()
        target.update(restored)
        return
    if isinstance(target, list):
        target[:] = restored
        return
    if hasattr(target, "__dict__") and hasattr(restored, "__dict__"):
        target.__dict__.clear()
        target.__dict__.update(restored.__dict__)
        return
    raise TransactionRestoreError(
        f"allocator state of type {type(target).__name__} is not restorable"
    )


@dataclass
class TransactionSnapshot:
    """The complete state a bounded mutation is permitted to touch."""

    docs: object
    page_positions: tuple[int, ...]
    page_sequence: list[object]
    pages: dict[int, object]
    total_pages: object
    run_trace: object | None
    trace_state: object | None
    fixed_inventory_builder: object | None
    allocator: object | None
    allocator_state: object | None
    before: TransactionDigests
    generation: int | None = None
    status: str = "attempted"
    rollback_verification: dict | None = None

    @classmethod
    def capture(
        cls,
        docs,
        page_positions: Iterable[int] | None = None,
        *,
        run_trace=None,
        fixed_inventory=None,
        fixed_inventory_builder=None,
        allocator=None,
    ) -> TransactionSnapshot:
        positions = tuple(
            range(len(docs.page))
            if page_positions is None
            else sorted({int(position) for position in page_positions})
        )
        if any(position < 0 or position >= len(docs.page) for position in positions):
            raise ValueError("transaction page position is outside the document")
        page_snapshots = {
            position: copy.deepcopy(docs.page[position]) for position in positions
        }
        trace_state = (
            None if run_trace is None else run_trace.transaction_snapshot()
        )
        allocator_state = copy.deepcopy(allocator)
        inventory = fixed_inventory
        if inventory is None and fixed_inventory_builder is not None:
            inventory = fixed_inventory_builder()
        return cls(
            docs=docs,
            page_positions=positions,
            page_sequence=list(docs.page),
            pages=page_snapshots,
            total_pages=copy.deepcopy(getattr(docs, "total_pages", None)),
            run_trace=run_trace,
            trace_state=trace_state,
            fixed_inventory_builder=fixed_inventory_builder,
            allocator=allocator,
            allocator_state=allocator_state,
            before=state_digests(
                docs,
                positions,
                run_trace=run_trace,
                fixed_inventory=inventory,
                allocator=allocator,
            ),
        )

    def begin_generation(self, reason: str) -> int | None:
        if self.run_trace is not None:
            self.generation = self.run_trace.begin_repair_generation(reason)
        return self.generation

    def current_digests(self) -> TransactionDigests:
        inventory = (
            None
            if self.fixed_inventory_builder is None
            else self.fixed_inventory_builder()
        )
        return state_digests(
            self.docs,
            self.page_positions,
            run_trace=self.run_trace,
            fixed_inventory=inventory,
            allocator=self.allocator,
        )

    def commit(self, touched_refs=(), *, capture_geometry: bool = True) -> dict:
        if self.run_trace is not None and self.generation is not None:
            if capture_geometry:
                self.run_trace.capture_repair_document(
                    self.docs, self.generation, touched_refs
                )
            self.run_trace.commit_generation(self.generation)
        self.status = "committed"
        return self.as_record()

    def not_executed(self) -> dict:
        self.rollback()
        self.status = "not_executed"
        return self.as_record()

    def rollback(self) -> dict:
        self.docs.page = list(self.page_sequence)
        for position, page in self.pages.items():
            self.docs.page[position] = copy.deepcopy(page)
        if hasattr(self.docs, "total_pages"):
            self.docs.total_pages = copy.deepcopy(self.total_pages)
        if self.run_trace is not None:
            self.run_trace.restore_transaction_snapshot(self.trace_state)
        _restore_allocator(self.allocator, self.allocator_state)
        restored = self.current_digests()
        self.rollback_verification = {
            "verified": restored == self.before,
            "expected": self.before.as_record(),
            "restored": restored.as_record(),
        }
        self.status = "rolled_back"
        if not self.rollback_verification["verified"]:
            raise TransactionRestoreError("transaction rollback digest mismatch")
        return self.as_record()

    def as_record(self) -> dict:
        return {
            "status": self.status,
            "pages": [position + 1 for position in self.page_positions],
            "generation": self.generation,
            "before": self.before.as_record(),
            "rollback_verification": self.rollback_verification,
        }
