from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import views

app_name = "payments"

urlpatterns = [
    path(_("pay/<uuid:public_id>/"), views.pay, name="pay"),
    path(_("pay/<uuid:public_id>/upgrade/"), views.upgrade, name="upgrade"),
    path(_("payment/<uuid:public_id>/"), views.payment_return, name="return"),
    path(_("payment/<uuid:public_id>/demo/"), views.demo_checkout, name="demo"),
]
