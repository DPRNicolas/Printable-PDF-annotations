#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pymupdf

import printable_annotations
import import_annotations
import export_annotations

# ============================================================
# Existing scripts
# ============================================================

HERE = os.path.dirname(os.path.abspath(__file__))

EXPORT_SCRIPT = os.path.join(
    HERE,
    "export_annotations.py"
)

PRINTABLE_SCRIPT = os.path.join(
    HERE,
    "printable_annotations.py"
)

BORDER_REDUCTION = 20  # points, on every side

# ============================================================
# Combine annotation JSON files
# ============================================================

def combine_annotations(json_files, page_offsets):
    """
    Combine annotation JSON files.

    The exporter uses 1-based page numbers, so the offset is
    added directly.

    Example:

        PDF 1: pages 1..10
        PDF 2: page 1 becomes page 11

    """

    combined = []

    for json_file, offset in zip(
        json_files,
        page_offsets
    ):

        with open(
            json_file,
            "r",
            encoding="utf-8"
        ) as f:
            annotations = json.load(f)

        for annotation in annotations:

            annotation = dict(annotation)

            annotation["page"] = (
                annotation["page"]
                + offset
            )

            combined.append(annotation)

    return combined

# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Combine annotated PDFs and create a "
            "computer-readable PDF and printable PDF."
        )
    )

    parser.add_argument(
        "-o",
        "--output",
        default="combined",
        help=(
            "Output prefix. Default: combined"
        )
    )

    parser.add_argument(
        "pdfs",
        nargs="+",
        help="PDF files to combine"
    )

    args = parser.parse_args()
    print(f'{args = }')

    # --------------------------------------------------------
    # Check scripts
    # --------------------------------------------------------

    if not os.path.isfile(
        EXPORT_SCRIPT
    ):
        parser.error(
            f"Cannot find {EXPORT_SCRIPT}"
        )

    if not os.path.isfile(
        PRINTABLE_SCRIPT
    ):
        parser.error(
            f"Cannot find {PRINTABLE_SCRIPT}"
        )

    # --------------------------------------------------------
    # Check input PDFs
    # --------------------------------------------------------

    for pdf in args.pdfs:
        print(f'{pdf = }')
        if not os.path.isfile(pdf):
            parser.error(
                f"Cannot find PDF: {pdf}"
            )

    # --------------------------------------------------------
    # Output filenames
    # --------------------------------------------------------

    combined_pdf = (
        args.output + ".pdf"
    )

    combined_json = (
        args.output + "_annotations.json"
    )

    printable_pdf = (
        args.output + "_printable.pdf"
    )

    # ========================================================
    # Temporary directory for individual JSON files
    # ========================================================

    with tempfile.TemporaryDirectory() as tmp:

        json_files = []
        page_offsets = []

        page_offset = 0

        # ====================================================
        # 1. Export annotations from every PDF
        # ====================================================

        for index, pdf in enumerate(args.pdfs):

            json_file = os.path.join(
                tmp,
                f"annotations_{index}.json"
            )

            export_annotations.export_annotations(
                pdf,
                json_file
            )

            json_files.append(
                json_file
            )

            # ------------------------------------------------
            # Page numbers in your exporter are 1-based.
            #
            # First PDF:
            #   pages 1..N
            #
            # Second PDF:
            #   pages N+1..N+M
            # ------------------------------------------------

            page_offsets.append(
                page_offset
            )

            source = pymupdf.open(pdf)
            source.close()

        # ====================================================
        # 2. Combine annotation JSON
        # ====================================================

        print()
        print(
            "Combining annotation data..."
        )

        combined_annotations = combine_annotations(
            json_files,
            page_offsets
        )

        with open(
            combined_json,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                combined_annotations,
                f,
                indent=2,
                ensure_ascii=False
            )

        print(
            f"Annotations: {len(combined_annotations)}"
        )

        # ====================================================
        # 3. Combine PDFs
        # ====================================================

        print()
        print(
            "Combining PDFs..."
        )

        import_annotations.import_annotations(
            args.pdfs[0],
            combined_json,
            combined_pdf,
        )

        # ====================================================
        # 4. Generate printable version
        # ====================================================

        printable_annotations.printable_annotations(
            combined_pdf,
            combined_json,
            printable_pdf
        )

    # ========================================================
    # Finished
    # ========================================================

    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)
    print()
    print(
        f"Computer PDF : {combined_pdf}"
    )
    print(
        f"Annotations  : {combined_json}"
    )
    print(
        f"Printable PDF: {printable_pdf}"
    )
    print()


if __name__ == "__main__":
    main()

