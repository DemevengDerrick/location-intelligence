from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import views

app_name = "reports"

urlpatterns = [
    path(_("verify/<uuid:reference>/"), views.verify, name="verify"),
    path(
        _("my-account/orders/<uuid:public_id>/report/v<int:number>-<str:language>.pdf"),
        views.download,
        name="download",
    ),
    path(_("my-account/orders/<uuid:public_id>/report/"), views.report_page, name="page"),
    path(
        _("my-account/orders/<uuid:public_id>/report/share/"),
        views.share_create,
        name="share_create",
    ),
    path(
        _("my-account/orders/<uuid:public_id>/report/share/<int:pk>/revoke/"),
        views.share_revoke,
        name="share_revoke",
    ),
    path(_("shared-report/<str:token>/"), views.shared_report, name="shared"),
    path(
        _("shared-report/<str:token>/v<int:number>-<str:language>.pdf"),
        views.shared_download,
        name="shared_download",
    ),
]
