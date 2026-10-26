from datetime import date, timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.gis.geos import GEOSException, GEOSGeometry
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.uploads import DOCUMENT_TYPES, check_upload
from apps.parcels.choices import InputMethod
from apps.parcels.parsers import GeometryInputError, parse_geometry_file
from apps.parcels.validation import check_pin, check_polygon
from apps.pricing.models import Product, ProductKind

from .models import AttachmentKind, IntakeDraft, Tier

MAX_GEOJSON_CHARS = 200_000
MAX_ATTACHMENTS = 10


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, list | tuple):
            return [single(item, initial) for item in data]
        return [single(data, initial)] if data else []


class FlexibleDecimalField(forms.DecimalField):
    """Accepts "1 250,5" (French) and "1250.5": spaces dropped, a lone comma is the decimal mark."""

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(" ", "").replace(" ", "").replace(" ", "")
            if "," in value and "." not in value:
                value = value.replace(",", ".")
        return super().to_python(value)


def geometry_from_json(text):
    if not text or len(text) > MAX_GEOJSON_CHARS:
        return None
    try:
        geom = GEOSGeometry(text, srid=4326)
    except (GEOSException, ValueError, TypeError):
        return None
    return geom


class LocateForm(forms.Form):
    """Step 1 (FR-7): pin, drawn polygon, coordinates file or site plan."""

    CRS_CHOICES = [
        ("wgs84", _("Longitude / latitude (WGS84)")),
        ("utm32n", _("UTM zone 32N (west of 12°E: Douala, Buea, Bafoussam)")),
        ("utm33n", _("UTM zone 33N (east of 12°E: Bertoua, Garoua, Maroua)")),
    ]
    METHODS = [InputMethod.PIN, InputMethod.DRAWN, InputMethod.FILE, InputMethod.SITE_PLAN]

    method = forms.ChoiceField(
        choices=[(m.value, m.label) for m in METHODS], widget=forms.RadioSelect
    )
    geometry = forms.CharField(required=False, widget=forms.HiddenInput)
    coords_file = forms.FileField(label=_("Coordinates file"), required=False)
    crs = forms.ChoiceField(
        label=_("Coordinate system (CSV files only)"), choices=CRS_CHOICES, initial="wgs84"
    )
    site_plan = forms.FileField(label=_("Photo or PDF of the site plan"), required=False)

    def __init__(self, *args, draft, **kwargs):
        self.draft = draft
        super().__init__(*args, **kwargs)
        self.checked = None
        self.site_plan_mime = None

    def clean(self):
        data = super().clean()
        method = data.get("method")
        try:
            if method == InputMethod.PIN:
                point = geometry_from_json(data.get("geometry"))
                if point is None or point.geom_type != "Point":
                    raise GeometryInputError(_("Click on the map to drop a pin on the parcel."))
                self.checked = check_pin(point)
            elif method == InputMethod.DRAWN:
                polygon = geometry_from_json(data.get("geometry"))
                if polygon is None or polygon.geom_type not in ("Polygon", "MultiPolygon"):
                    raise GeometryInputError(
                        _("Draw the parcel boundary on the map, then continue.")
                    )
                self.checked = check_polygon(polygon)
            elif method == InputMethod.FILE:
                upload = data.get("coords_file")
                if not upload:
                    raise GeometryInputError(_("Choose a coordinates file to upload."))
                self.checked = check_polygon(parse_geometry_file(upload, data.get("crs", "wgs84")))
            elif method == InputMethod.SITE_PLAN:
                self._clean_site_plan(data)
        except GeometryInputError as exc:
            raise ValidationError(str(exc)) from exc
        return data

    def _clean_site_plan(self, data):
        upload = data.get("site_plan")
        has_plan = self.draft.attachments.filter(kind=AttachmentKind.SITE_PLAN).exists()
        if upload:
            self.site_plan_mime = check_upload(upload, DOCUMENT_TYPES)
        elif not has_plan:
            raise ValidationError(_("Upload a photo or PDF of the site plan."))
        point = geometry_from_json(data.get("geometry"))
        if point is not None and point.geom_type == "Point":
            # Optional rough location: used to centre the analyst's map, not as a boundary.
            self.checked = check_pin(point)


class DetailsForm(forms.ModelForm):
    """Step 2 (FR-10)."""

    UNITS = [("m2", "m²"), ("ha", "ha")]

    stated_area = FlexibleDecimalField(
        label=_("Area stated by the seller"),
        required=False,
        min_value=0,
        max_digits=12,
        decimal_places=2,
        # Text, not type=number: browsers reject "1 250,5", which French users type.
        widget=forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"}),
    )
    stated_area_unit = forms.ChoiceField(label=_("Unit"), choices=UNITS, initial="m2")
    documents = MultipleFileField(
        label=_("Photos and documents"),
        required=False,
        help_text=_(
            "Photos of the land, the seller's documents… JPEG, PNG or PDF, up to 20 MB each."
        ),
    )

    class Meta:
        model = IntakeDraft
        fields = ["quartier", "commune", "region", "title_number", "intended_use", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}
        help_texts = {
            "title_number": _("Optional. We record it as given; we do not verify titles."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        area = self.instance.stated_area_m2
        if area and not self.is_bound:
            if area >= 10_000 and area % 100 == 0:
                self.initial.update(stated_area=area / 10_000, stated_area_unit="ha")
            else:
                self.initial.update(stated_area=area, stated_area_unit="m2")
        self.mimes = []

    def clean_documents(self):
        files = self.cleaned_data["documents"]
        existing = self.instance.attachments.exclude(kind=AttachmentKind.SITE_PLAN).count()
        if existing + len(files) > MAX_ATTACHMENTS:
            raise ValidationError(_("You can attach up to %(n)s files.") % {"n": MAX_ATTACHMENTS})
        self.mimes = [check_upload(f, DOCUMENT_TYPES) for f in files]
        return files

    def save(self, commit=True):
        draft = super().save(commit=False)
        area, unit = self.cleaned_data.get("stated_area"), self.cleaned_data.get("stated_area_unit")
        draft.stated_area_m2 = float(area) * (10_000 if unit == "ha" else 1) if area else None
        if commit:
            draft.save()
        return draft


class TierForm(forms.ModelForm):
    """Step 3: tier, add-ons, deadline and report language."""

    tier = forms.ChoiceField(label=_("Report"), widget=forms.RadioSelect)
    add_ons = forms.MultipleChoiceField(
        label=_("Options"), required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = IntakeDraft
        fields = ["tier", "add_ons", "deadline", "report_language"]
        # Browsers' date pickers read and send ISO dates whatever the page language.
        widgets = {"deadline": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        labels = {"deadline": _("When do you need it?")}
        error_messages = {
            "deadline": {"invalid": _("Choose the date in the calendar, or leave it empty.")}
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tiers = Product.objects.filter(kind=ProductKind.TIER, is_active=True, code__in=Tier.values)
        self.fields["tier"].choices = [(p.code, p.name) for p in tiers]
        # Bounds make browsers treat the year as 4 digits; without max, Chrome's year part
        # accepts 6 digits and typing "20261120" becomes an invalid "202611-…" date.
        self.fields["deadline"].widget.attrs.update(
            min=(date.today() + timedelta(days=1)).isoformat(),
            max=(date.today() + timedelta(days=730)).isoformat(),
        )
        add_ons = Product.objects.filter(kind=ProductKind.ADD_ON, is_active=True)
        self.fields["add_ons"].choices = [(p.code, p.name) for p in add_ons]
        if not add_ons:
            del self.fields["add_ons"]

    def clean_deadline(self):
        deadline = self.cleaned_data.get("deadline")
        if deadline and deadline < date.today():
            raise ValidationError(_("The deadline cannot be in the past."))
        if deadline and deadline > date.today() + timedelta(days=730):
            raise ValidationError(_("Choose the date in the calendar, or leave it empty."))
        return deadline


class AccountForm(forms.Form):
    """Step 4: contact details, an account if needed (FR-17), and the terms (NFR-15)."""

    email = forms.EmailField(label=_("Email"))
    contact_name = forms.CharField(label=_("Full name"), max_length=200)
    contact_phone = forms.CharField(
        label=_("Phone or WhatsApp"),
        max_length=32,
        required=False,
        help_text=_("With country code, e.g. +237 6…, +33 6…, +1 514…"),
    )
    password = forms.CharField(
        label=_("Password"),
        required=False,
        # A new account: browsers must offer to generate a password, not fill a saved one.
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text=_("Leave empty to sign in later with a code sent by email."),
    )
    accept_terms = forms.BooleanField(
        label=_("I accept the terms of service and understand the report is not a title search.")
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user if user and user.is_authenticated else None
        self.email_taken = False
        if self.user:
            del self.fields["email"]
            del self.fields["password"]

    def clean_email(self):
        email = get_user_model().objects.normalize_email(self.cleaned_data["email"]).lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            self.email_taken = True
            raise ValidationError(
                _("An account already exists for this email. Sign in to continue your order.")
            )
        return email

    def clean(self):
        data = super().clean()
        password = data.get("password")
        if password:
            candidate = get_user_model()(email=data.get("email", ""))
            try:
                validate_password(password, candidate)
            except ValidationError as exc:
                self.add_error("password", exc)
        return data
