import json
import sys
import pymupdf  # PyMuPDF


def export_annotations(pdf_path, output_path):
    doc = pymupdf.open(pdf_path)
    annotations = []

    for page_number, page in enumerate(doc, start=1):
        annot = page.first_annot

        while annot:
            data = {
                "page": page_number,
                "type": annot.type[1],       # e.g. "Highlight", "Text"
                "rect": list(annot.rect),
                "info": annot.info,
            }

            # Annotation colors, when available
            colors = annot.colors
            if colors:
                data["colors"] = colors

            # For highlight/underline/etc., try to recover the
            # actual text associated with the annotation.
            try:
                vertices = annot.vertices
                if vertices:
                    data["vertices"] = [list(v) for v in vertices]
            except Exception:
                pass

            try:
                data["text"] = page.get_textbox(annot.rect)
            except Exception:
                pass

            annotations.append(data)
            annot = annot.next

    doc.close()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(annotations, f, indent=2, ensure_ascii=False)

    print(f"Exported {len(annotations)} annotations to {output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.pdf annotations.json")
        sys.exit(1)

    export_annotations(sys.argv[1], sys.argv[2])


