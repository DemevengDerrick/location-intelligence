from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Lead


class LeadForm(forms.ModelForm):
    # Honeypot: hidden from people, filled in by naive bots.
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    consent = forms.BooleanField(
        label=_("I agree to be contacted about my request, as described in the privacy policy.")
    )

    class Meta:
        model = Lead
        fields = ["name", "email", "phone", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 5})}

    def is_bot(self):
        return bool(self.cleaned_data.get("website"))
