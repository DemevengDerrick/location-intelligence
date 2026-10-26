from urllib.parse import quote

from django.utils.translation import gettext as _

from apps.core.site_settings import get_setting


def public(request):
    number = "".join(ch for ch in str(get_setting("whatsapp_number", "")) if ch.isdigit())
    if not number:
        return {"WHATSAPP_URL": ""}
    text = _("Hello, I would like to know more about your land reports.")
    return {"WHATSAPP_URL": f"https://wa.me/{number}?text={quote(text)}"}
