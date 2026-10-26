from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.utils import translation
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.generic import FormView, TemplateView
from django_ratelimit.decorators import ratelimit

from apps.pricing.currency import get_currency
from apps.pricing.services import priced_tiers

from .forms import LeadForm
from .models import FAQItem, Page, PageSlug, SampleReport
from .tasks import notify_new_lead


class PricingContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["tiers"] = priced_tiers(get_currency(self.request))
        return context


class HomeView(PricingContextMixin, TemplateView):
    template_name = "pages/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["faq_items"] = FAQItem.objects.filter(is_published=True)[:4]
        return context


class HowItWorksView(TemplateView):
    template_name = "pages/how_it_works.html"


class PricingView(PricingContextMixin, TemplateView):
    template_name = "pages/pricing.html"


class SamplesView(TemplateView):
    template_name = "pages/samples.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["samples"] = SampleReport.objects.filter(is_published=True)
        return context


def sample_download(request, pk):
    sample = get_object_or_404(SampleReport, pk=pk, is_published=True)
    pdf = sample.pdf_for(translation.get_language())
    if not pdf:
        raise Http404
    # Files live in the private bucket; hand out a short-lived signed URL.
    return HttpResponseRedirect(pdf.url)


class FAQView(TemplateView):
    template_name = "pages/faq.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["faq_items"] = FAQItem.objects.filter(is_published=True)
        return context


class ContentPageView(TemplateView):
    template_name = "pages/content_page.html"
    slug = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page"] = get_object_or_404(Page, slug=self.slug)
        return context


@method_decorator(ratelimit(key="ip", rate="5/h", method="POST", block=False), name="post")
class ContactView(FormView):
    template_name = "pages/contact.html"
    form_class = LeadForm

    def form_valid(self, form):
        if getattr(self.request, "limited", False):
            form.add_error(None, _("Too many messages from your connection. Please try later."))
            return self.form_invalid(form)
        if not form.is_bot():
            lead = form.save(commit=False)
            lead.language = translation.get_language()
            lead.source_path = self.request.POST.get("source", "")[:300]
            lead.save()
            transaction.on_commit(lambda: notify_new_lead.delay(lead.pk))
        messages.success(self.request, _("Thank you. We will reply within one business day."))
        return redirect("pages:contact")


def robots_txt(request):
    lines = [
        "User-agent: *",
        *(f"Disallow: /{code}/admin/" for code, _name in settings.LANGUAGES),
        *(f"Disallow: /{code}/accounts/" for code, _name in settings.LANGUAGES),
        f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


PAGE_VIEWS = {slug: ContentPageView.as_view(slug=slug) for slug in PageSlug.values}
