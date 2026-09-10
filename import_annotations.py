#!/usr/bin/env python3

import json
import sys
import pymupdf  # PyMuPDF


def make_quads(vertices):
    """
    Convert exported vertices into PyMuPDF Quad objects.

    Our exporter stores vertices as:
        [
            [x1, y1, x2, y2, x3, y3, x4, y4],
            ...
        ]

    Some PyMuPDF versions may return vertices as individual points:
        [
            [x1, y1],
            [x2, y2],
            ...
        ]
    """

    if not vertices:
        return []

    # Case 1:
    # [[x1,y1,x2,y2,x3,y3,x4,y4], ...]
    if all(isinstance(v, (list, tuple)) and len(v) == 8
           for v in vertices):

        return [
            pymupdf.Quad(
                pymupdf.Point(v[0], v[1]),
                pymupdf.Point(v[2], v[3]),
                pymupdf.Point(v[4], v[5]),
                pymupdf.Point(v[6], v[7]),
            )
            for v in vertices
        ]

    # Case 2:
    # [[x1,y1], [x2,y2], ...]
    if all(isinstance(v, (list, tuple)) and len(v) == 2
           for v in vertices):

        points = [
            pymupdf.Point(v[0], v[1])
            for v in vertices
        ]

        # Four points make one quad
        if len(points) % 4 != 0:
            raise ValueError(
                f"Number of vertices ({len(points)}) "
                "is not a multiple of 4"
            )

        return [
            pymupdf.Quad(
                points[i],
                points[i + 1],
                points[i + 2],
                points[i + 3],
            )
            for i in range(0, len(points), 4)
        ]

    raise ValueError(
        f"Unknown vertex format: {vertices!r}"
    )


def restore_info(annot, info):
    """Restore annotation metadata."""

    if not info:
        return

    kwargs = {}

    for key in (
        "content",
        "title",
        "subject",
    ):
        if key in info and info[key]:
            kwargs[key] = info[key]

    if kwargs:
        try:
            annot.set_info(**kwargs)
        except Exception as e:
            print(f"  Warning: could not restore metadata: {e}")


def restore_colors(annot, colors):
    """Restore annotation colors."""

    if not colors:
        return

    stroke = colors.get("stroke")
    fill = colors.get("fill")

    try:
        kwargs = {}

        if stroke:
            kwargs["stroke"] = stroke

        if fill:
            kwargs["fill"] = fill

        if kwargs:
            annot.set_colors(**kwargs)

    except Exception as e:
        print(f"  Warning: could not restore colors: {e}")


def import_annotations(input_pdf, annotations_json, output_pdf):

    print(f"Opening: {input_pdf}")

    doc = pymupdf.open(input_pdf)

    print(f"Pages: {len(doc)}")

    with open(annotations_json, "r", encoding="utf-8") as f:
        annotations = json.load(f)

    print(f"Annotations to import: {len(annotations)}")
    print()

    imported = 0
    skipped = 0

    for number, data in enumerate(annotations, start=1):

        page_number = data.get("page")
        annotation_type = data.get("type")

        print(
            f"[{number}/{len(annotations)}] "
            f"{annotation_type} on page {page_number}"
        )

        if not page_number:
            print("  ERROR: annotation has no page")
            skipped += 1
            continue

        page_index = page_number - 1

        if page_index < 0 or page_index >= len(doc):
            print(
                f"  ERROR: page {page_number} "
                f"does not exist in destination PDF"
            )
            skipped += 1
            continue

        page = doc[page_index]

        rect = pymupdf.Rect(data["rect"])
        info = data.get("info", {})
        colors = data.get("colors", {})
        vertices = data.get("vertices")

        try:

            # ---------------------------------------------------------
            # Highlight
            # ---------------------------------------------------------

            if annotation_type == "Highlight":

                if vertices:
                    quads = make_quads(vertices)

                    if not quads:
                        raise ValueError(
                            "No valid quadrilaterals"
                        )

                    annot = page.add_highlight_annot(quads)

                else:
                    annot = page.add_highlight_annot(rect)

            # ---------------------------------------------------------
            # Underline
            # ---------------------------------------------------------

            elif annotation_type == "Underline":

                if vertices:
                    quads = make_quads(vertices)

                    if not quads:
                        raise ValueError(
                            "No valid quadrilaterals"
                        )

                    annot = page.add_underline_annot(quads)

                else:
                    annot = page.add_underline_annot(rect)

            # ---------------------------------------------------------
            # Strikeout
            # ---------------------------------------------------------

            elif annotation_type == "StrikeOut":

                if vertices:
                    quads = make_quads(vertices)

                    if not quads:
                        raise ValueError(
                            "No valid quadrilaterals"
                        )

                    annot = page.add_strikeout_annot(quads)

                else:
                    annot = page.add_strikeout_annot(rect)

            # ---------------------------------------------------------
            # Squiggly
            # ---------------------------------------------------------

            elif annotation_type == "Squiggly":

                if vertices:
                    quads = make_quads(vertices)

                    if not quads:
                        raise ValueError(
                            "No valid quadrilaterals"
                        )

                    annot = page.add_squiggly_annot(quads)

                else:
                    annot = page.add_squiggly_annot(rect)

            # ---------------------------------------------------------
            # Sticky note
            # ---------------------------------------------------------

            elif annotation_type == "Text":

                content = info.get("content", "")

                annot = page.add_text_annot(
                    rect.tl,
                    content
                )

            # ---------------------------------------------------------
            # Free text
            # ---------------------------------------------------------

            elif annotation_type == "FreeText":

                content = info.get("content", "")

                annot = page.add_freetext_annot(
                    rect,
                    content
                )

            # ---------------------------------------------------------
            # Rectangle
            # ---------------------------------------------------------

            elif annotation_type == "Square":

                annot = page.add_rect_annot(rect)

            # ---------------------------------------------------------
            # Circle
            # ---------------------------------------------------------

            elif annotation_type == "Circle":

                annot = page.add_circle_annot(rect)

            # ---------------------------------------------------------
            # Unsupported annotation
            # ---------------------------------------------------------

            else:

                print(
                    f"  SKIP: unsupported annotation type "
                    f"'{annotation_type}'"
                )

                skipped += 1
                continue

            # ---------------------------------------------------------
            # Restore metadata and appearance
            # ---------------------------------------------------------

            if annot is None:
                print("  ERROR: PyMuPDF returned no annotation")
                skipped += 1
                continue

            restore_info(annot, info)
            restore_colors(annot, colors)

            annot.update()

            imported += 1

            print("  OK")

        except Exception as e:

            print(
                f"  ERROR: {type(e).__name__}: {e}"
            )

            skipped += 1

    print()
    print("Saving output...")

    doc.save(output_pdf)

    doc.close()

    print()
    print("=" * 50)
    print("Done")
    print("=" * 50)
    print(f"Imported : {imported}")
    print(f"Skipped  : {skipped}")
    print(f"Output   : {output_pdf}")


def main():

    if len(sys.argv) != 4:

        print(
            f"Usage:\n"
            f"  {sys.argv[0]} "
            f"destination.pdf annotations.json output.pdf"
        )

        print()
        print("Example:")
        print(
            f"  {sys.argv[0]} "
            f"new.pdf annotations.json new_annotated.pdf"
        )

        sys.exit(1)

    input_pdf = sys.argv[1]
    annotations_json = sys.argv[2]
    output_pdf = sys.argv[3]

    import_annotations(
        input_pdf,
        annotations_json,
        output_pdf,
    )


if __name__ == "__main__":
    main()

