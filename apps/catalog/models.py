from django.db import models
from django.db.models.functions import Lower, Upper

from apps.common.models import BaseModel

# Single-currency system for now; stored on bookings/payments so it can change later.
CURRENCY = "INR"


class DiagnosticCentreQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class DiagnosticCentre(BaseModel):
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10)
    is_active = models.BooleanField(default=True)
    tests = models.ManyToManyField(
        "catalog.DiagnosticTest", through="catalog.CentreTest", related_name="centres"
    )

    objects = DiagnosticCentreQuerySet.as_manager()

    class Meta:
        ordering = ["name", "id"]
        indexes = [models.Index(Lower("city"), name="catalog_centre_city_ci_idx")]

    def __str__(self) -> str:
        return f"{self.name} ({self.city})"


class DiagnosticTestQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class DiagnosticTest(BaseModel):
    code = models.CharField(max_length=32, help_text="Short unique code, e.g. CBC.")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    objects = DiagnosticTestQuerySet.as_manager()

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["code"], name="catalog_test_code_unique"),
            models.CheckConstraint(
                condition=models.Q(code=Upper("code")), name="catalog_test_code_uppercase"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class CentreTestQuerySet(models.QuerySet):
    def bookable(self):
        """Offerings a patient can book: offering, centre and test are all active."""
        return self.filter(is_active=True, centre__is_active=True, test__is_active=True)


class CentreTest(BaseModel):
    """A test offered at a centre, with that centre's price ("offering")."""

    centre = models.ForeignKey(DiagnosticCentre, on_delete=models.PROTECT, related_name="offerings")
    test = models.ForeignKey(DiagnosticTest, on_delete=models.PROTECT, related_name="offerings")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)

    objects = CentreTestQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["centre", "test"], name="catalog_offering_centre_test_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(price__gt=0), name="catalog_offering_price_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.test_id} @ {self.centre_id}: {self.price}"
