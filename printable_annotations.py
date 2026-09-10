import pymupdf 
import json
import math


# ============================================================
# Configuration
# ============================================================

INPUT_PDF = "intput.pdf" #change to your file
ANNOTATIONS_JSON = "input_annotations.json"
OUTPUT_PDF = "article_printable.pdf"

# Initial width of the comment column
INITIAL_MARGIN_WIDTH = 220

# Space between original page and comment column
MARGIN_GAP = 20

# Padding inside comment boxes
COMMENT_PADDING = 1

# Gap between comment boxes
COMMENT_GAP = 5

# Font size
INITIAL_FONT_SIZE = 9

# Smallest font size we'll use if necessary
MIN_FONT_SIZE = 6

# Rendering resolution for the original page.
# 2.5 gives good print quality.
RENDER_SCALE = 2.5

# Horizontal padding around the detected content.
#
# 0 = tightest possible crop.
# For example:
#     HORIZONTAL_PADDING = 2
# adds 2 pt on each side.
HORIZONTAL_PADDING = 2


# ============================================================
# Annotation / comment helpers
# ============================================================

def get_comment(annotation):
    """
    Return the actual comment written by the annotator.

    The comment is stored in annotation.info["content"].
    We deliberately do NOT fall back to text in the annotated
    region, because that is the document text, not the comment.
    """

    info = annotation.get("info", {})

    if not isinstance(info, dict):
        return ""

    content = info.get("content", "")

    if content is None:
        return ""

    return str(content).strip()


def get_annotation_type(annotation):
    """
    Return a human-readable annotation type.
    """

    annotation_type = annotation.get("type")

    if annotation_type:
        return str(annotation_type)

    return "Annotation"


def get_writer_initials(annotation):
    """
    Extract the writer's initials.

    PyMuPDF normally stores the author in info["title"].
    """

    info = annotation.get("info", {})

    if not isinstance(info, dict):
        return "??"

    author = (
        info.get("title")
        or info.get("author")
        or ""
    )

    author = str(author).strip()

    if not author:
        return "??"

    parts = author.replace(".", " ").split()

    if not parts:
        return "??"

    if len(parts) == 1:
        return parts[0][0].upper()

    return (
        parts[0][0] +
        parts[-1][0]
    ).upper()


# ============================================================
# Find tight horizontal content bounds
# ============================================================

def get_content_horizontal_bounds(page, annotations):
    """
    Find the smallest horizontal zone containing all visible
    content on the page.

    We use PyMuPDF's bboxlog(), which reports the bounding boxes
    of displayed page objects such as:

        - text
        - images
        - drawings
        - filled/stroked objects
        - other page graphics

    PDF annotations are added separately because they are not
    necessarily included in the normal page content bbox.

    Returns:
        (x0, x1)

    If no content can be detected, the full page width is used.
    """

    page_rect = page.rect

    min_x = page_rect.x1
    max_x = page_rect.x0

    # --------------------------------------------------------
    # 1. Normal PDF page content
    # --------------------------------------------------------

    try:
        bbox_log = page.get_bboxlog()

        for item in bbox_log:
            if len(item) < 2:
                continue

            bbox = item[1]

            if not bbox or len(bbox) != 4:
                continue

            x0, y0, x1, y1 = bbox

            # Ignore invalid / empty boxes.
            if x1 <= x0 or y1 <= y0:
                continue

            min_x = min(min_x, x0)
            max_x = max(max_x, x1)

    except Exception:
        # ----------------------------------------------------
        # Fallback for older / unusual PyMuPDF versions.
        # ----------------------------------------------------

        try:
            blocks = page.get_text("blocks")

            for block in blocks:
                if len(block) < 4:
                    continue

                x0, y0, x1, y1 = block[:4]

                if x1 <= x0 or y1 <= y0:
                    continue

                min_x = min(min_x, x0)
                max_x = max(max_x, x1)

        except Exception:
            pass

    # --------------------------------------------------------
    # 2. Include all PDF annotations
    #
    # They are rendered with annots=True later, so they must
    # also be included in the crop calculation.
    # --------------------------------------------------------

    for annotation in annotations:

        # Annotation rectangle
        rect = annotation.get("rect")

        if rect and len(rect) == 4:

            try:
                x0, y0, x1, y1 = map(float, rect)

                min_x = min(min_x, x0)
                max_x = max(max_x, x1)

            except (TypeError, ValueError):
                pass

        # Annotation vertices can extend outside the annotation
        # rectangle for some annotation types.
        vertices = annotation.get("vertices")

        if vertices:

            try:

                # Nested format:
                #
                # [[x1, y1], [x2, y2], ...]
                #
                if (
                    isinstance(vertices, list)
                    and vertices
                    and isinstance(vertices[0], list)
                ):

                    if len(vertices[0]) == 2:

                        for point in vertices:

                            if len(point) >= 2:

                                x = float(point[0])

                                min_x = min(min_x, x)
                                max_x = max(max_x, x)

                    else:

                        # Quad format:
                        #
                        # [[x1,y1,x2,y2,x3,y3,x4,y4], ...]
                        #

                        for quad in vertices:

                            if len(quad) >= 8:

                                for i in range(0, 8, 2):

                                    x = float(quad[i])

                                    min_x = min(min_x, x)
                                    max_x = max(max_x, x)

                # Flat format:
                #
                # [x1,y1,x2,y2,...]
                #
                elif (
                    isinstance(vertices, list)
                    and len(vertices) >= 2
                ):

                    for i in range(
                        0,
                        len(vertices) - 1,
                        2
                    ):

                        x = float(vertices[i])

                        min_x = min(min_x, x)
                        max_x = max(max_x, x)

            except (
                TypeError,
                ValueError,
                IndexError
            ):
                pass

    # --------------------------------------------------------
    # 3. If nothing was found, keep the complete page.
    # --------------------------------------------------------

    if (
        min_x >= max_x
        or min_x == page_rect.x1
        or max_x == page_rect.x0
    ):
        return page_rect.x0, page_rect.x1

    # --------------------------------------------------------
    # 4. Add optional safety padding.
    # --------------------------------------------------------

    min_x -= HORIZONTAL_PADDING
    max_x += HORIZONTAL_PADDING

    # Keep crop inside the actual page.
    min_x = max(
        page_rect.x0,
        min_x
    )

    max_x = min(
        page_rect.x1,
        max_x
    )

    return min_x, max_x


# ============================================================
# Annotation geometry
# ============================================================

def get_annotation_anchor(annotation, page_rect):
    """
    Find the point where the connector should start.

    For highlight-like annotations, use the actual vertices
    stored in annotations.json.

    For other annotations, use the center of their rectangle.
    """

    vertices = annotation.get("vertices")

    if vertices:

        points = []

        try:

            # Nested [x, y] format
            if (
                isinstance(vertices, list)
                and vertices
                and isinstance(vertices[0], list)
            ):

                if (
                    len(vertices[0]) == 2
                    and isinstance(
                        vertices[0][0],
                        (int, float)
                    )
                ):

                    for point in vertices:

                        if len(point) >= 2:

                            points.append(
                                pymupdf.Point(
                                    float(point[0]),
                                    float(point[1])
                                )
                            )

                # Quad format
                else:

                    for quad in vertices:

                        if len(quad) >= 8:

                            for i in range(0, 8, 2):

                                points.append(
                                    pymupdf.Point(
                                        float(quad[i]),
                                        float(quad[i + 1])
                                    )
                                )

            # Flat format
            elif (
                isinstance(vertices, list)
                and len(vertices) >= 2
            ):

                for i in range(
                    0,
                    len(vertices) - 1,
                    2
                ):

                    points.append(
                        pymupdf.Point(
                            float(vertices[i]),
                            float(vertices[i + 1])
                        )
                    )

        except (
            TypeError,
            ValueError,
            IndexError
        ):
            points = []

        if points:

            x = sum(
                point.x for point in points
            ) / len(points)

            y = sum(
                point.y for point in points
            ) / len(points)

            x = max(
                page_rect.x0,
                min(page_rect.x1, x)
            )

            y = max(
                page_rect.y0,
                min(page_rect.y1, y)
            )

            return pymupdf.Point(x, y)

    # ========================================================
    # Fallback: annotation rectangle
    # ========================================================

    rect = annotation.get("rect")

    if rect and len(rect) == 4:

        x0, y0, x1, y1 = rect

        x = (x0 + x1) / 2
        y = (y0 + y1) / 2

        x = max(
            page_rect.x0,
            min(page_rect.x1, x)
        )

        y = max(
            page_rect.y0,
            min(page_rect.y1, y)
        )

        return pymupdf.Point(x, y)

    return None


# ============================================================
# Text wrapping
# ============================================================

def wrap_text(
    font,
    text,
    max_width,
    font_size
):
    """
    Wrap comment text according to the actual PDF font width.
    """

    if not text:
        return []

    words = text.split()
    lines = []
    current = ""

    for word in words:

        candidate = (
            word
            if not current
            else current + " " + word
        )

        width = font.text_length(
            candidate,
            fontsize=font_size
        )

        if width <= max_width:

            current = candidate

        else:

            if current:
                lines.append(current)

            # Handle a single word wider than the column.
            if (
                font.text_length(
                    word,
                    fontsize=font_size
                ) > max_width
            ):

                remaining = word

                while remaining:

                    piece = ""

                    for char in remaining:

                        candidate_piece = (
                            piece + char
                        )

                        if font.text_length(
                            candidate_piece,
                            fontsize=font_size
                        ) <= max_width:

                            piece = candidate_piece

                        else:

                            break

                    if not piece:
                        piece = remaining[0]

                    lines.append(piece)

                    remaining = remaining[
                        len(piece):
                    ]

                current = ""

            else:

                current = word

    if current:
        lines.append(current)

    return lines


# ============================================================
# Calculate comment layout
# ============================================================

def calculate_comment_layout(
    comments,
    page_height,
    margin_width,
    font_size
):
    """
    Calculate the height and positions of all comment boxes.
    """

    font = pymupdf.Font("helv")

    text_width = (
        margin_width
        - 2 * COMMENT_PADDING
    )

    comments_sorted = sorted(
        comments,
        key=lambda annotation:
            (
                annotation.get("page", 0),
                annotation.get(
                    "rect",
                    [0, 0, 0, 0]
                )[1]
            )
    )

    layout = []

    for annotation in comments:

        comment = get_comment(annotation)

        if not comment:
            continue

        annotation_type = (
            get_annotation_type(annotation)
        )

        initials = (
            get_writer_initials(annotation)
        )

        label = (
            f"{annotation_type} — {initials}"
        )

        lines = wrap_text(
            font,
            comment,
            text_width,
            font_size
        )

        if not lines:
            lines = [""]

        line_height = (
            font_size * 1.25
        )

        label_height = (
            font_size + 4
        )

        box_height = (
            COMMENT_PADDING
            + label_height
            + 4
            + len(lines) * line_height
            + COMMENT_PADDING
        )

        layout.append({
            "annotation": annotation,
            "lines": lines,
            "label": label,
            "height": box_height,
        })

    if not layout:
        return [], 0

    current_bottom = 0

    for item in layout:

        item["y0"] = current_bottom

        item["y1"] = (
            item["y0"]
            + item["height"]
        )

        current_bottom = (
            item["y1"]
            + COMMENT_GAP
        )

    total_height = (
        current_bottom
        - COMMENT_GAP
    )

    return layout, total_height


# ============================================================
# Find suitable column width and font size
# ============================================================

def fit_comment_layout(
    comments,
    page_height
):
    """
    Find a column width/font size combination that allows
    every comment to fit on the page.
    """

    margin_width = INITIAL_MARGIN_WIDTH
    font_size = INITIAL_FONT_SIZE

    while font_size >= MIN_FONT_SIZE:

        layout, total_height = (
            calculate_comment_layout(
                comments,
                page_height,
                margin_width,
                font_size
            )
        )

        if total_height <= page_height:

            return (
                margin_width,
                font_size,
                layout
            )

        margin_width += 40

        if margin_width > 500:

            margin_width = 300
            font_size -= 0.5

    # Last resort

    margin_width = 550
    font_size = MIN_FONT_SIZE

    layout, total_height = (
        calculate_comment_layout(
            comments,
            page_height,
            margin_width,
            font_size
        )
    )

    return (
        margin_width,
        font_size,
        layout
    )

def printable_annotations(INPUT_PDF, ANNOTATIONS_JSON, OUTPUT_PDF):

    # ============================================================
    # Load files
    # ============================================================

    doc = pymupdf.open(INPUT_PDF)

    with open(
        ANNOTATIONS_JSON,
        "r",
        encoding="utf-8"
    ) as f:

        annotations = json.load(f)


    # ============================================================
    # Group annotations by page
    # ============================================================

    annotations_by_page = {}

    for annotation in annotations:

        page_number = (
            annotation.get("page", 0) - 1
        )

        annotations_by_page.setdefault(
            page_number,
            []
        ).append(annotation)


    # ============================================================
    # Create output document
    # ============================================================

    out = pymupdf.open()


    # ============================================================
    # Process every page
    # ============================================================

    for page_number in range(len(doc)):

        original_page = doc[page_number]

        page_rect = original_page.rect

        page_height = page_rect.height

        page_annotations = (
            annotations_by_page.get(
                page_number,
                []
            )
        )

        # --------------------------------------------------------
        # Find the tightest horizontal content zone.
        # --------------------------------------------------------

        crop_x0, crop_x1 = (
            get_content_horizontal_bounds(
                original_page,
                page_annotations
            )
        )

        crop_rect = pymupdf.Rect(
            crop_x0,
            page_rect.y0,
            crop_x1,
            page_rect.y1
        )

        cropped_width = crop_rect.width

        # --------------------------------------------------------
        # Only include annotations which actually have comments.
        # --------------------------------------------------------

        comments = [
            annotation
            for annotation in page_annotations
            if get_comment(annotation)
        ]

        # --------------------------------------------------------
        # Calculate comment column.
        # --------------------------------------------------------

        if comments:

            (
                margin_width,
                font_size,
                layout
            ) = fit_comment_layout(
                comments,
                page_height
            )

        else:

            margin_width = 0
            font_size = INITIAL_FONT_SIZE
            layout = []

        # --------------------------------------------------------
        # Total output page width.
        #
        # The original page is now cropped horizontally.
        # --------------------------------------------------------

        output_width = (
            cropped_width
            + MARGIN_GAP
            + margin_width
        )

        output_page = out.new_page(
            width=output_width,
            height=page_height
        )

        # ========================================================
        # Render only the cropped horizontal zone
        # ========================================================

        pix = original_page.get_pixmap(
            matrix=pymupdf.Matrix(
                RENDER_SCALE,
                RENDER_SCALE
            ),
            clip=crop_rect,
            alpha=False,
            annots=True
        )

        output_page.insert_image(
            pymupdf.Rect(
                0,
                0,
                cropped_width,
                page_height
            ),
            pixmap=pix
        )

        # ========================================================
        # No comments -> nothing else to draw.
        # ========================================================

        if not comments:
            continue

        # ========================================================
        # Comment column separator
        # ========================================================

        separator_x = (
            cropped_width
            + MARGIN_GAP / 2
        )

        output_page.draw_line(
            pymupdf.Point(
                separator_x,
                0
            ),
            pymupdf.Point(
                separator_x,
                page_height
            ),
            width=0.5
        )

        # ========================================================
        # Draw comments
        # ========================================================

        margin_x0 = (
            cropped_width
            + MARGIN_GAP
        )

        margin_x1 = output_width

        font = pymupdf.Font("helv")

        for index, item in enumerate(
            layout,
            start=1
        ):

            annotation = item["annotation"]

            y0 = item["y0"]
            y1 = item["y1"]

            x0 = margin_x0
            x1 = margin_x1

            # ----------------------------------------------------
            # Comment box
            # ----------------------------------------------------

            box = pymupdf.Rect(
                x0,
                y0,
                x1,
                y1
            )

            output_page.draw_rect(
                box,
                width=0.7
            )

            # ----------------------------------------------------
            # Label
            # ----------------------------------------------------

            text_x = (
                x0
                + COMMENT_PADDING
            )

            text_y = (
                y0
                + COMMENT_PADDING
                + font_size
            )

            label = (
                f"[{index}] {item['label']}"
            )

            output_page.insert_text(
                pymupdf.Point(
                    text_x,
                    text_y
                ),
                label,
                fontname="helv",
                fontsize=font_size
            )

            # ----------------------------------------------------
            # Comment body
            # ----------------------------------------------------

            line_height = (
                font_size * 1.25
            )

            text_y += (
                font_size
                + 4
            )

            for line in item["lines"]:

                output_page.insert_text(
                    pymupdf.Point(
                        text_x,
                        text_y
                    ),
                    line,
                    fontname="helv",
                    fontsize=font_size
                )

                text_y += line_height

            # ====================================================
            # Connector
            # ====================================================

            # Get the anchor in the ORIGINAL page coordinates.
            anchor = get_annotation_anchor(
                annotation,
                page_rect
            )

            if anchor is None:
                continue

            # ----------------------------------------------------
            # Translate the anchor into the CROPPED page's
            # coordinate system.
            #
            # Original:
            #     x = 150
            #
            # Crop starts at:
            #     x = 50
            #
            # New coordinate:
            #     x = 100
            # ----------------------------------------------------

            anchor = pymupdf.Point(
                anchor.x - crop_x0,
                anchor.y - page_rect.y0
            )

            # Keep anchor inside the cropped page.
            anchor.x = max(
                0,
                min(cropped_width, anchor.x)
            )

            anchor.y = max(
                0,
                min(page_height, anchor.y)
            )

            # ----------------------------------------------------
            # The connector points to the middle of the left edge
            # of the corresponding comment box.
            # ----------------------------------------------------

            target = pymupdf.Point(
                x0,
                (y0 + y1) / 2
            )

            # ----------------------------------------------------
            # Draw connector.
            # ----------------------------------------------------

            output_page.draw_line(
                anchor,
                target,
                width=0.6
            )

            # ----------------------------------------------------
            # Small circle marking the actual annotation point.
            # ----------------------------------------------------

            output_page.draw_circle(
                anchor,
                2.5,
                width=0.6
            )


    # ============================================================
    # Save
    # ============================================================

    out.save(
        OUTPUT_PDF,
        garbage=4,
        deflate=True
    )

    out.close()
    doc.close()

    print(
        f"Created: {OUTPUT_PDF}"
    )

if __name__ == "__main__":
    printable_annotations(INPUT_PDF, ANNOTATIONS_JSON, OUTPUT_PDF)