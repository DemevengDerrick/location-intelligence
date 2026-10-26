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
]
