from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse


class AccountAdapter(DefaultAccountAdapter):
    def get_password_change_redirect_url(self, request):
        """After setting or changing a password, back to the customer's details page."""
        return reverse("portal:account")
