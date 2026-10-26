from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _


class MessageForm(forms.Form):
    body = forms.CharField(
        label=_("Your message"),
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )


class ProfileForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "phone", "language", "currency"]
        labels = {
            "language": _("Language for emails and reports"),
            "currency": _("Currency for prices"),
        }
