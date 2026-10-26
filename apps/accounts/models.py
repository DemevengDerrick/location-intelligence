from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class Currency(models.TextChoices):
    XAF = "XAF", "XAF"
    CAD = "CAD", "CAD"
    EUR = "EUR", "EUR"
    USD = "USD", "USD"


class Organization(TimeStampedModel):
    """An agency or notary office that owns many orders (Journey D)."""

    name = models.CharField(_("name"), max_length=200)
    billing_email = models.EmailField(_("billing email"), blank=True)
    invoiced_monthly = models.BooleanField(_("invoiced monthly"), default=False)

    class Meta:
        verbose_name = _("organization")
        verbose_name_plural = _("organizations")
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField(_("email address"), unique=True)
    language = models.CharField(
        _("language"), max_length=5, choices=settings.LANGUAGES, default=settings.LANGUAGE_CODE
    )
    currency = models.CharField(
        _("currency"), max_length=3, choices=Currency.choices, default=Currency.XAF
    )
    phone = models.CharField(_("phone"), max_length=32, blank=True)
    organization = models.ForeignKey(
        Organization,
        verbose_name=_("organization"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.email
