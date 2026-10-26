"""Site plans as images for the georeferencing view (FR-39): photos and scans are
re-encoded as PNG (turned upright from their EXIF orientation), PDFs give their first page."""

import io

from django.utils.translation import gettext as _

from .parsers import GeometryInputError

MAX_SIDE_PX = 2400  # enough to read a plan; keeps the browser responsive
PDF_SCALE = 200 / 72  # about 200 dpi before the size cap


def render_plan(data: bytes, content_type: str = "", name: str = ""):
    """PNG bytes, width and height of the plan, at most MAX_SIDE_PX on its longest side."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    is_pdf = content_type == "application/pdf" or name.lower().endswith(".pdf")
    try:
        image = (
            _first_pdf_page(data)
            if is_pdf
            else ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise GeometryInputError(_("This file could not be read as an image or a PDF.")) from exc
    image = image.convert("RGB")
    image.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), image.width, image.height


def _first_pdf_page(data):
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise ValueError(str(exc)) from exc
    try:
        if len(pdf) == 0:
            raise ValueError("empty PDF")
        return pdf[0].render(scale=PDF_SCALE).to_pil()
    finally:
        pdf.close()
