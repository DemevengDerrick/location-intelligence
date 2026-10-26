"""Check uploaded files by size and by their actual content, not their name (NFR-8)."""

import filetype
from django.conf import settings
from django.core.exceptions import ValidationError
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext as _

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
PDF_TYPES = {"application/pdf"}
DOCUMENT_TYPES = IMAGE_TYPES | PDF_TYPES


def check_upload(uploaded, allowed=DOCUMENT_TYPES, max_bytes=None):
    """Return the detected MIME type, or raise ValidationError with a customer-facing message."""
    max_bytes = max_bytes or settings.MAX_ATTACHMENT_BYTES
    if uploaded.size > max_bytes:
        raise ValidationError(
            _("%(name)s is too large (maximum %(size)s).")
            % {"name": uploaded.name, "size": filesizeformat(max_bytes)}
        )
    head = uploaded.read(8192)
    uploaded.seek(0)
    kind = filetype.guess(head)
    if kind is None or kind.mime not in allowed:
        raise ValidationError(
            _("%(name)s is not an accepted file type. Use a photo (JPEG, PNG) or a PDF.")
            % {"name": uploaded.name}
        )
    return kind.mime
