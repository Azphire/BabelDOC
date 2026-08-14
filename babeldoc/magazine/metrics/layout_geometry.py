"""M4, M5, M7, M8 and M9: what a page's geometry says about how it was set.

Two of these are borrowed and three are new. The borrowed pair are the layout
generation measures of li2020layoutgan as normalised per element by
kikuchi2021layoutganpp, cited as ``eq:overlap`` and ``eq:alignment`` of
``docs/dissertation/background_chapter.tex`` and reproduced here only so a reader
of the code sees what is being computed:

.. math::

    \\mathrm{Overlap} = \\frac{1}{N}\\sum_{i=1}^{N}\\sum_{j \\ne i}
        \\frac{A(b_i \\cap b_j)}{A(b_i)}
    \\qquad\\text{(eq:overlap)}

.. math::

    \\mathrm{Alignment} = \\frac{1}{N}\\sum_{i=1}^{N}
        \\min\\big(g(\\Delta x_i^{L}), g(\\Delta x_i^{C}), g(\\Delta x_i^{R}),
                   g(\\Delta y_i^{T}), g(\\Delta y_i^{C}), g(\\Delta y_i^{B})\\big),
    \\quad g(x) = -\\log(1 - x)
    \\qquad\\text{(eq:alignment)}

with :math:`\\Delta x_i^{*} = \\min_{j \\ne i} |x_i^{*} - x_j^{*}|` and
:math:`\\Delta y_i^{*}` the same over the other axis. The three new ones are the
graphics-side measures this project adds, defined here:

.. math::

    \\Delta_{\\mathrm{image}} =
        \\frac{\\sum_{k} A(f_k^{\\text{produced}}) - \\sum_{k} A(f_k^{\\text{source}})}
             {\\sum_{k} A(f_k^{\\text{source}})}
    \\qquad\\text{(M7, image-area delta)}

.. math::

    \\Delta_{\\mathrm{pages}} = P^{\\text{produced}} - P^{\\text{source}}
    \\qquad\\text{(M8, page-count delta)}

.. math::

    \\mathrm{IoU}_{\\mathrm{image}} = \\frac{1}{|S|}\\sum_{(u,v) \\in \\Pi}
        \\frac{A(u \\cap v)}{A(u \\cup v)},
    \\quad |S| = \\max(|F^{\\text{source}}|, |F^{\\text{produced}}|)
    \\qquad\\text{(M9, image placement IoU)}

where :math:`\\Pi` is the pairing described below. Dividing by the larger of the
two image counts rather than by :math:`|\\Pi|` is what makes an image that lost
its partner cost the score instead of vanishing from it.

**Decisions this module makes, which the metric contract records.**

*The element set is paragraphs and images, and not xobjects.* ``eq:overlap``
is about page elements rather than about text blocks, so images are in, taken
from ``pdf_figure`` and from the layout regions carrying a declared image class,
which is where this pipeline actually leaves them. A ``pdf_xobject`` is a
container whose contents are already counted as the paragraphs and images inside
it, and admitting it would have every one of its children overlap it completely
-- a page's Overlap would then measure how the producer nested its form objects.
The layout regions standing for text are left out for the same reason: they are
the regions the paragraphs were derived from, and counting both counts the page
twice.

*Coordinates are normalised by the page frame.* Kikuchi's measures are defined
on a unit page and ``g`` has a pole at 1, so a metric on raw points would be
neither comparable across page sizes nor total. The frame is the crop box where
there is one and the media box otherwise.

*Degenerate elements are dropped, not given a contribution.* ``eq:overlap``
divides by :math:`A(b_i)`, which a zero-area box has none of. An element under
``min_element_area_ratio`` leaves both roles, so it neither takes a share nor
gives one, and the count of what was dropped is reported.

*A page with fewer than two elements has no Alignment.* :math:`\\Delta` is a
minimum over the other elements and there are none, so the value is ``None``
rather than 0.0: a single-element page is not perfectly aligned, it is
unmeasurable, and the two must not add up in a corpus mean.

*Images pair by page position, then by nearest area.* Source and produced images
are taken in page order; each source image takes the unpaired produced image
whose area is closest to its own in ratio, refusing any pair whose areas differ
by more than ``image_pair_max_area_ratio``. Ties break on the produced image's
own page position, so the pairing is a function of the geometry and not of the
order a dictionary happened to iterate in. Whatever is left unpaired on either
side is counted in the denominator with an IoU of zero and named in the report.

The measures are absolute numbers whose scale is a property of the publication,
so a report gives **the source side and the produced side of one document and
their difference**, never one side alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from babeldoc.magazine.metrics import MetricsConfig
from babeldoc.magazine.metrics import load_metrics_config
from babeldoc.magazine.metrics import rounded

# The six coordinates eq:alignment is defined over, in its own order: the two
# left/top edges, the two centres, the two right/bottom edges.
ALIGNMENT_COORDINATES = ("left", "centre_x", "right", "top", "centre_y", "bottom")


@dataclass(frozen=True)
class Element:
    """One page element as the geometry measures see it, on the unit page."""

    kind: str
    left: float
    bottom: float
    right: float
    top: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.top - self.bottom

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def coordinate(self, name: str) -> float:
        if name == "left":
            return self.left
        if name == "right":
            return self.right
        if name == "centre_x":
            return (self.left + self.right) / 2
        if name == "bottom":
            return self.bottom
        if name == "top":
            return self.top
        return (self.bottom + self.top) / 2


def page_frame(page):
    """The box a page's coordinates are normalised by: crop box, else media box."""
    for holder in (page.cropbox, page.mediabox):
        if holder is not None and holder.box is not None:
            return holder.box
    return None


def _element_from(box, kind: str, frame) -> Element | None:
    if box is None or frame is None:
        return None
    values = (box.x, box.y, box.x2, box.y2)
    if any(value is None for value in values):
        return None
    width = float(frame.x2) - float(frame.x)
    height = float(frame.y2) - float(frame.y)
    if width <= 0 or height <= 0:
        return None
    left, bottom, right, top = (float(value) for value in values)
    return Element(
        kind=kind,
        left=(min(left, right) - float(frame.x)) / width,
        right=(max(left, right) - float(frame.x)) / width,
        bottom=(min(bottom, top) - float(frame.y)) / height,
        top=(max(bottom, top) - float(frame.y)) / height,
    )


def figures_of(page, config: MetricsConfig) -> list[Element]:
    """The image elements of one page, which M7 and M9 are about.

    Read from two places because this pipeline uses both. ``pdf_figure`` is
    where the intermediate language has somewhere for an image; the layout
    parser puts the images it finds in ``page_layout`` instead, as regions
    carrying one of the declared image classes, and on the corpus that is where
    all of them are. A measurement reading only the first would report every
    magazine as carrying no images at all.
    """
    frame = page_frame(page)
    found = []
    for figure in page.pdf_figure or ():
        element = _element_from(figure.box, "figure", frame)
        if element is not None:
            found.append(element)
    for layout in page.page_layout or ():
        if (layout.class_name or "") not in config.image_layout_classes:
            continue
        element = _element_from(layout.box, "figure", frame)
        if element is not None:
            found.append(element)
    return found


def elements_of(page, config: MetricsConfig) -> list[Element]:
    """Every measurable element of one page, on the unit page, in stored order."""
    frame = page_frame(page)
    found = []
    for paragraph in page.pdf_paragraph or ():
        element = _element_from(paragraph.box, "paragraph", frame)
        if element is not None:
            found.append(element)
    found.extend(figures_of(page, config))
    return found


def _intersection_area(left: Element, right: Element) -> float:
    width = min(left.right, right.right) - max(left.left, right.left)
    height = min(left.top, right.top) - max(left.bottom, right.bottom)
    if width <= 0 or height <= 0:
        return 0.0
    return width * height


def intersection_over_union(left: Element, right: Element) -> float:
    shared = _intersection_area(left, right)
    union = left.area + right.area - shared
    return shared / union if union > 0 else 0.0


def overlap(elements: list[Element], config: MetricsConfig) -> dict:
    """eq:overlap over one page's elements, with what it had to drop.

    No threshold: the detector in ``babeldoc/magazine/detectors/overlap.py``
    carries one because it is looking for a defect worth raising, and this is a
    measurement of how much elements intrude on one another at all.
    """
    kept = [item for item in elements if item.area >= config.min_element_area_ratio]
    dropped = len(elements) - len(kept)
    if not kept:
        return {"value": None, "elements": 0, "dropped": dropped}
    total = 0.0
    for index, element in enumerate(kept):
        for other_index, other in enumerate(kept):
            if index == other_index:
                continue
            total += _intersection_area(element, other) / element.area
    return {
        "value": total / len(kept),
        "elements": len(kept),
        "dropped": dropped,
    }


def _g(value: float, config: MetricsConfig) -> float:
    """``g(x) = -log(1-x)``, clamped to the domain its pole leaves open.

    The clamp is a bound, not a rescaling: an argument at or beyond 1 is only
    reachable by two elements at opposite edges of a normalised page, which is
    not a page anybody set, and the alternative to clamping is a metric that
    returns an infinity for one such page and destroys every mean it enters.
    """
    bounded = min(max(value, 0.0), config.alignment_max_delta)
    return -math.log(1.0 - bounded)


def alignment(elements: list[Element], config: MetricsConfig) -> dict:
    """eq:alignment over one page's elements, per element rather than per page."""
    kept = [item for item in elements if item.area >= config.min_element_area_ratio]
    dropped = len(elements) - len(kept)
    if len(kept) < 2:
        return {"value": None, "elements": len(kept), "dropped": dropped}
    total = 0.0
    for index, element in enumerate(kept):
        deltas = []
        for name in ALIGNMENT_COORDINATES:
            own = element.coordinate(name)
            deltas.append(
                min(
                    abs(own - other.coordinate(name))
                    for other_index, other in enumerate(kept)
                    if other_index != index
                )
            )
        total += min(_g(delta, config) for delta in deltas)
    return {"value": total / len(kept), "elements": len(kept), "dropped": dropped}


def _pairs(source: list[Element], produced: list[Element], config: MetricsConfig):
    """Source images matched to produced ones by page position, then nearest area.

    Greedy in source page order, which is what makes the result a function of
    the two pages: a source image takes the closest unpaired produced image by
    area ratio, and a tie is broken by the produced image's own position.
    """
    available = list(range(len(produced)))
    matched: list[tuple[int, int]] = []
    for index, element in enumerate(source):
        best = None
        for position in available:
            other = produced[position]
            larger = max(element.area, other.area)
            smaller = min(element.area, other.area)
            if smaller <= 0:
                ratio = math.inf
            else:
                ratio = larger / smaller
            if ratio > config.image_pair_max_area_ratio:
                continue
            if best is None or (ratio, position) < best[0]:
                best = ((ratio, position), position)
        if best is None:
            continue
        available.remove(best[1])
        matched.append((index, best[1]))
    return matched, available


def image_placement_iou(
    source: list[Element], produced: list[Element], config: MetricsConfig
) -> dict:
    """M9: how far the produced page's images sit from where the source's were."""
    matched, unpaired_produced = _pairs(source, produced, config)
    denominator = max(len(source), len(produced))
    if denominator == 0:
        return {
            "value": None,
            "pairs": 0,
            "source_images": 0,
            "produced_images": 0,
            "unpaired_source": 0,
            "unpaired_produced": 0,
        }
    total = sum(
        intersection_over_union(source[left], produced[right])
        for left, right in matched
    )
    return {
        "value": total / denominator,
        "pairs": len(matched),
        "source_images": len(source),
        "produced_images": len(produced),
        "unpaired_source": len(source) - len(matched),
        "unpaired_produced": len(unpaired_produced),
    }


def image_area_delta(source: list[Element], produced: list[Element]) -> dict:
    """M7: how much image area the produced page carries against the source page."""
    before = sum(item.area for item in source)
    after = sum(item.area for item in produced)
    return {
        "source_area": before,
        "produced_area": after,
        "absolute": after - before,
        "value": (after - before) / before if before > 0 else None,
    }


def page_count_delta(source_pages: int, produced_pages: int) -> dict:
    """M8: the coarsest geometric statement there is, and the easiest to check."""
    return {
        "source_pages": source_pages,
        "produced_pages": produced_pages,
        "value": produced_pages - source_pages,
        "conserved": source_pages == produced_pages,
    }


def measure_page(page, config: MetricsConfig) -> dict:
    """Overlap and Alignment for one page, as one side of a comparison."""
    elements = elements_of(page, config)
    return {
        "elements": len(elements),
        "overlap": overlap(elements, config),
        "alignment": alignment(elements, config),
    }


def _mean(values: list[float]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def measure(
    source_pages: list,
    produced_pages: list,
    config: MetricsConfig | None = None,
) -> dict:
    """M4, M5, M7, M8 and M9 over one document, both sides and their difference.

    Pages are compared by position. A document whose two sides differ in page
    count is measured over the pages they share, and the page-count delta is
    what says the two sides were not the same length; folding an absent page
    into a mean as a zero would hide exactly that.
    """
    config = config or load_metrics_config()
    digits = config.report_float_digits
    shared = min(len(source_pages), len(produced_pages))
    pages = []
    for index in range(shared):
        before = measure_page(source_pages[index], config)
        after = measure_page(produced_pages[index], config)
        figures_before = figures_of(source_pages[index], config)
        figures_after = figures_of(produced_pages[index], config)
        pages.append(
            {
                "page_index": index,
                "source": before,
                "produced": after,
                "overlap_delta": None
                if before["overlap"]["value"] is None or after["overlap"]["value"] is None
                else after["overlap"]["value"] - before["overlap"]["value"],
                "alignment_delta": None
                if before["alignment"]["value"] is None
                or after["alignment"]["value"] is None
                else after["alignment"]["value"] - before["alignment"]["value"],
                "image_area_delta": image_area_delta(figures_before, figures_after),
                "image_placement_iou": image_placement_iou(
                    figures_before, figures_after, config
                ),
            }
        )

    def rounded_pages() -> list[dict]:
        return [
            {
                key: rounded(value, digits)
                if not isinstance(value, dict)
                else {
                    inner: rounded(item, digits) for inner, item in value.items()
                }
                for key, value in page.items()
            }
            for page in pages
        ]

    return {
        "metric": "layout_geometry",
        "pages_compared": shared,
        "page_count_delta": page_count_delta(len(source_pages), len(produced_pages)),
        "summary": {
            "overlap_source": rounded(
                _mean([page["source"]["overlap"]["value"] for page in pages]), digits
            ),
            "overlap_produced": rounded(
                _mean([page["produced"]["overlap"]["value"] for page in pages]), digits
            ),
            "overlap_delta": rounded(
                _mean([page["overlap_delta"] for page in pages]), digits
            ),
            "alignment_source": rounded(
                _mean([page["source"]["alignment"]["value"] for page in pages]), digits
            ),
            "alignment_produced": rounded(
                _mean([page["produced"]["alignment"]["value"] for page in pages]),
                digits,
            ),
            "alignment_delta": rounded(
                _mean([page["alignment_delta"] for page in pages]), digits
            ),
            "image_area_delta": rounded(
                _mean([page["image_area_delta"]["value"] for page in pages]), digits
            ),
            "image_placement_iou": rounded(
                _mean([page["image_placement_iou"]["value"] for page in pages]), digits
            ),
        },
        "pages": rounded_pages(),
    }
