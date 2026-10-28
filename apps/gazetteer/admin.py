from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _

from apps.core.maps import GISModelAdmin
from apps.parcels.parsers import GeometryInputError

from .layer_import import import_layer
from .models import GazetteerPlace, ReferenceLayer, ReferenceLayerKind


@admin.register(GazetteerPlace)
class GazetteerPlaceAdmin(GISModelAdmin):
    list_display = ["name", "place_type", "commune", "department", "region"]
    list_filter = ["place_type", "region"]
    search_fields = ["name", "aliases", "commune"]


class LayerImportForm(forms.Form):
    kind = forms.ChoiceField(label=_("Kind"), choices=ReferenceLayerKind.choices)
    file = forms.FileField(
        label=_("File"), help_text=_("GeoJSON, KML or a zipped shapefile (50 MB maximum).")
    )
    name_field = forms.CharField(
        label=_("Name attribute"),
        required=False,
        help_text=_("The attribute that holds each feature's name (optional)."),
    )
    source = forms.CharField(
        label=_("Source"),
        max_length=200,
        help_text=_("For example the decree or ministry the layer comes from."),
    )
    valid_from = forms.DateField(label=_("Valid from"), required=False)
    replace = forms.BooleanField(
        label=_("Replace the features previously imported from this source"), required=False
    )


@admin.register(ReferenceLayer)
class ReferenceLayerAdmin(GISModelAdmin):
    list_display = ["name", "kind", "source", "is_active", "valid_from"]
    list_filter = ["kind", "is_active", "source"]
    search_fields = ["name", "source"]
    change_list_template = "admin/gazetteer/referencelayer/change_list.html"

    def get_urls(self):
        view = self.admin_site.admin_view(self.import_view)
        return [path("import/", view, name="gazetteer_referencelayer_import"), *super().get_urls()]

    def import_view(self, request):
        if not self.has_add_permission(request):
            return redirect("admin:gazetteer_referencelayer_changelist")
        form = LayerImportForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            try:
                count = import_layer(
                    data["file"],
                    data["kind"],
                    data["name_field"],
                    data["source"],
                    data["valid_from"],
                    data["replace"],
                )
            except GeometryInputError as exc:
                form.add_error("file", str(exc))
            else:
                self.message_user(
                    request, _("%(n)s features imported.") % {"n": count}, messages.SUCCESS
                )
                return redirect(reverse("admin:gazetteer_referencelayer_changelist"))
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "form": form,
            "title": _("Import a constraint layer"),
        }
        return render(request, "admin/gazetteer/referencelayer/import.html", context)
