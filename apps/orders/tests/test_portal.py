from decimal import Decimal

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse
from django.utils import translation

from apps.accounts import roles
from apps.orders.models import Attachment, AttachmentKind, Message, OrderStatus
from apps.orders.status import transition
from apps.orders.testing import make_order
from apps.payments.models import Payment, PaymentPurpose
from apps.payments.services import can_upgrade

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


@pytest.fixture
def signed_in(client, customer):
    customer.language = "en"  # emails follow the customer's language, not the page's
    customer.save()
    client.force_login(customer)
    return client


def pay_with_demo(client, order, path="payments:pay"):
    client.post(reverse(path, args=[order.public_id]), {"method": "card"})
    payment = Payment.objects.filter(order=order).latest("created_at")
    client.post(reverse("payments:demo", args=[payment.public_id]), {"decision": "approve"})
    return payment


# --- Navigation and orders list -----------------------------------------------------------


def test_signing_in_lands_on_my_orders(client, customer):
    response = client.post(
        reverse("account_login"), {"login": customer.email, "password": "pw-12345-secret"}
    )
    assert response.url == reverse("portal:orders")


def test_menu_shows_my_orders_when_signed_in(signed_in):
    assert "My orders" in signed_in.get(reverse("pages:home")).content.decode()


def test_orders_list_shows_only_my_orders(signed_in, customer, make_user):
    mine = make_order(customer)
    other = make_order(make_user("other@example.com"))
    html = signed_in.get(reverse("portal:orders")).content.decode()
    assert str(mine.public_id)[:8] in html
    assert str(other.public_id)[:8] not in html
    assert "Bonamoussadi, Douala V" in html
    assert "Submitted" in html


def test_portal_requires_sign_in(client):
    response = client.get(reverse("portal:orders"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))


# --- Order page ---------------------------------------------------------------------------


def test_other_customers_get_404(signed_in, make_user):
    order = make_order(make_user("other@example.com"))
    Attachment.objects.create(
        order=order, kind=AttachmentKind.PHOTO, file=ContentFile(b"x", "a.png")
    )
    attachment = order.attachments.get()
    assert signed_in.get(reverse("portal:order", args=[order.public_id])).status_code == 404
    url = reverse("portal:attachment", args=[order.public_id, attachment.pk])
    assert signed_in.get(url).status_code == 404
    post = signed_in.post(reverse("portal:message", args=[order.public_id]), {"body": "hi"})
    assert post.status_code == 404


def test_unpaid_order_offers_payment(signed_in, customer):
    order = make_order(customer)
    html = signed_in.get(reverse("portal:order", args=[order.public_id])).content.decode()
    assert "waiting for payment" in html
    assert reverse("payments:pay", args=[order.public_id]) in html


def test_timeline_follows_the_status_changes(signed_in, customer):
    order = make_order(customer)
    pay_with_demo(signed_in, order)
    html = signed_in.get(reverse("portal:order", args=[order.public_id])).content.decode()
    timeline = html.split("Progress", 1)[1]
    assert timeline.index("Submitted") < timeline.index("Paid") < timeline.index("Processing")


def test_own_files_download_through_signed_urls(signed_in, customer):
    order = make_order(customer)
    attachment = Attachment.objects.create(
        order=order,
        kind=AttachmentKind.PHOTO,
        file=ContentFile(b"x", "plot.png"),
        original_name="plot.png",
    )
    response = signed_in.get(reverse("portal:attachment", args=[order.public_id, attachment.pk]))
    assert response.status_code == 302
    assert "plot" in response.url


# --- Messages -----------------------------------------------------------------------------


def test_customer_message_reaches_staff(signed_in, customer, django_capture_on_commit_callbacks):
    order = make_order(customer)
    with django_capture_on_commit_callbacks(execute=True):
        response = signed_in.post(
            reverse("portal:message", args=[order.public_id]), {"body": "Is the road paved?"}
        )
    assert response.url.endswith("#messages")
    assert Message.objects.get().author == customer
    assert mail.outbox[-1].to == ["ops@example.com"]
    assert "Is the road paved?" in mail.outbox[-1].body


def test_staff_reply_is_emailed_in_the_customers_language(
    customer, analyst, django_capture_on_commit_callbacks
):
    customer.language = "fr"
    customer.save()
    order = make_order(customer)
    with django_capture_on_commit_callbacks(execute=True):
        Message.objects.create(order=order, author=analyst, body="Oui, sur 200 m.")
    reply = mail.outbox[-1]
    assert reply.to == [customer.email]
    assert "Nouveau message" in reply.subject
    assert "/fr/mon-compte/" in reply.body


def test_replies_are_marked_read_when_the_customer_opens_the_order(signed_in, customer, analyst):
    order = make_order(customer)
    reply = Message.objects.create(order=order, author=analyst, body="Hello")
    signed_in.get(reverse("portal:order", args=[order.public_id]))
    reply.refresh_from_db()
    assert reply.read_at is not None


def test_admin_reply_is_authored_by_the_staff_member(client, customer, make_user):
    admin = make_user("founder@example.com", role=roles.ADMIN, is_staff=True)
    client.force_login(admin)
    order = make_order(customer)
    url = reverse("admin:orders_order_change", args=[order.pk])
    page = client.get(url)
    form = page.context["adminform"].form
    data = {k: v for k, v in form.initial.items() if v is not None and not hasattr(v, "pk")}
    data.update(
        {
            "customer": customer.pk,
            "tier": order.tier,
            "currency": order.currency,
            "language": order.language,
            "add_ons": "[]",
            "discount_amount": "0",
            "price_amount": "10000",
            "payments-TOTAL_FORMS": "0", "payments-INITIAL_FORMS": "0",
            "attachments-TOTAL_FORMS": "0", "attachments-INITIAL_FORMS": "0",
            "messages-TOTAL_FORMS": "1", "messages-INITIAL_FORMS": "0",
            "messages-0-body": "We checked the road: it is paved.",
        }
    )  # fmt: skip
    response = client.post(url, data)
    assert response.status_code == 302, response.context["adminform"].form.errors
    assert Message.objects.get().author == admin


# --- Status emails ------------------------------------------------------------------------


def test_payment_sends_one_receipt_not_three_emails(
    signed_in, customer, django_capture_on_commit_callbacks
):
    order = make_order(customer)
    with django_capture_on_commit_callbacks(execute=True):
        pay_with_demo(signed_in, order)
    assert [m.subject.split(" ")[0] for m in mail.outbox] == ["Receipt"]


def test_later_status_changes_are_emailed_in_the_customers_language(
    customer, django_capture_on_commit_callbacks
):
    customer.language = "fr"
    customer.save()
    order = make_order(customer, status=OrderStatus.PROCESSING)
    with django_capture_on_commit_callbacks(execute=True):
        transition(order, OrderStatus.IN_REVIEW)
    email = mail.outbox[-1]
    assert email.to == [customer.email]
    assert "analyse terminée" in email.subject
    assert f"/fr/mon-compte/commandes/{order.public_id}/" in email.body


# --- Upgrade to field verification --------------------------------------------------------


def test_desk_order_can_be_upgraded_by_paying_the_difference(
    signed_in, customer, django_capture_on_commit_callbacks
):
    order = make_order(customer)
    pay_with_demo(signed_in, order)
    order.refresh_from_db()
    assert can_upgrade(order)

    page = signed_in.get(reverse("payments:upgrade", args=[order.public_id])).content.decode()
    assert "40,000" in page  # 50 000 field − 10 000 desk

    with django_capture_on_commit_callbacks(execute=True):
        upgrade = pay_with_demo(signed_in, order, path="payments:upgrade")
    order.refresh_from_db()
    assert upgrade.purpose == PaymentPurpose.UPGRADE
    assert upgrade.amount == Decimal("40000")
    assert order.tier == "field"
    assert order.price_amount == Decimal("50000")
    assert order.status == OrderStatus.PROCESSING  # the upgrade doesn't touch the status
    assert "Field verification has been added" in mail.outbox[-1].body
    assert not can_upgrade(order)


def test_unpaid_or_field_orders_cannot_be_upgraded(signed_in, customer):
    unpaid = make_order(customer)
    response = signed_in.get(reverse("payments:upgrade", args=[unpaid.public_id]))
    assert response.url == reverse("portal:order", args=[unpaid.public_id])

    field = make_order(customer, status=OrderStatus.PROCESSING)
    field.tier = "field"
    field.save()
    assert not can_upgrade(field)


# --- Account ------------------------------------------------------------------------------


def test_account_settings_switch_language_and_currency(signed_in, customer):
    response = signed_in.post(
        reverse("portal:account"),
        {
            "first_name": "Ama",
            "last_name": "Nkeng",
            "phone": "+237 6",
            "language": "fr",
            "currency": "EUR",
        },
    )
    customer.refresh_from_db()
    assert (customer.language, customer.currency) == ("fr", "EUR")
    with translation.override("fr"):
        assert response.url == reverse("portal:account")
    assert response.cookies["django_language"].value == "fr"
    assert response.cookies["currency"].value == "EUR"
    assert Client().get(reverse("portal:account")).status_code == 302
