from django import template
from django.urls import translate_url

register = template.Library()


@register.simple_tag(takes_context=True)
def translated_url(context, language, absolute=False):
    """The current page's URL in another language (works with translated URL patterns)."""
    request = context["request"]
    url = translate_url(request.path, language)
    return request.build_absolute_uri(url) if absolute else url
