from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import intake_views as views

app_name = "intake"

urlpatterns = [
    path("", views.start, name="start"),
    path(_("resume/"), views.resume, name="resume"),
    path(_("search/"), views.search, name="search"),
    path(_("<uuid:token>/step-<int:number>/"), views.step, name="step"),
    path(_("<uuid:token>/area-check/"), views.area_check, name="area_check"),
    path(
        _("<uuid:token>/attachments/<int:pk>/delete/"),
        views.delete_attachment,
        name="delete_attachment",
    ),
]
