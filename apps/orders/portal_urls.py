from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import portal_views as views

app_name = "portal"

urlpatterns = [
    path("", views.order_list, name="orders"),
    path(_("details/"), views.account, name="account"),
    path(_("orders/<uuid:public_id>/"), views.order_detail, name="order"),
    path(_("orders/<uuid:public_id>/messages/"), views.post_message, name="message"),
    path(
        _("orders/<uuid:public_id>/files/<int:pk>/"),
        views.attachment_download,
        name="attachment",
    ),
]
