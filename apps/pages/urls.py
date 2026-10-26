from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import views

app_name = "pages"

# Paths are translated, so French visitors get /fr/tarifs/ and English ones /en/pricing/.
urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path(_("how-it-works/"), views.HowItWorksView.as_view(), name="how_it_works"),
    path(_("pricing/"), views.PricingView.as_view(), name="pricing"),
    path(_("sample-reports/"), views.SamplesView.as_view(), name="samples"),
    path(_("sample-reports/<int:pk>/pdf/"), views.sample_download, name="sample_download"),
    path(_("faq/"), views.FAQView.as_view(), name="faq"),
    path(_("contact/"), views.ContactView.as_view(), name="contact"),
    path(_("about/"), views.PAGE_VIEWS["about"], name="about"),
    path(_("terms/"), views.PAGE_VIEWS["terms"], name="terms"),
    path(_("privacy/"), views.PAGE_VIEWS["privacy"], name="privacy"),
    path(_("disclaimer/"), views.PAGE_VIEWS["disclaimer"], name="disclaimer"),
]
