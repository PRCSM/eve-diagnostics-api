from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest

TESTS = [
    ("CBC", "Complete Blood Count", "Measures red cells, white cells and platelets."),
    ("LIPID", "Lipid Profile", "Cholesterol and triglycerides. 10-12 hours fasting."),
    ("HBA1C", "HbA1c", "Average blood sugar over roughly three months."),
    ("TFT", "Thyroid Function Test", "TSH, T3 and T4."),
    ("VITD", "Vitamin D (25-OH)", "Vitamin D level."),
]

CENTRES = [
    {
        "name": "Sample Diagnostics Baner",
        "address": "12 Baner Road",
        "city": "Pune",
        "pincode": "411045",
        "prices": {"CBC": "349.00", "LIPID": "599.00", "HBA1C": "449.00", "TFT": "499.00"},
    },
    {
        "name": "Sample Diagnostics Andheri",
        "address": "7 Link Road, Andheri West",
        "city": "Mumbai",
        "pincode": "400053",
        "prices": {"CBC": "399.00", "LIPID": "649.00", "VITD": "1199.00"},
    },
    {
        "name": "Sample Diagnostics Indiranagar",
        "address": "100 Feet Road, Indiranagar",
        "city": "Bengaluru",
        "pincode": "560038",
        "prices": {"CBC": "379.00", "HBA1C": "479.00", "TFT": "529.00", "VITD": "1099.00"},
    },
]


class Command(BaseCommand):
    help = "Create demo centres, tests and prices. Safe to run repeatedly."

    @transaction.atomic
    def handle(self, *args, **options):
        tests = {}
        for code, name, description in TESTS:
            tests[code], _ = DiagnosticTest.objects.update_or_create(
                code=code, defaults={"name": name, "description": description, "is_active": True}
            )

        for spec in CENTRES:
            centre, _ = DiagnosticCentre.objects.update_or_create(
                name=spec["name"],
                city=spec["city"],
                defaults={
                    "address": spec["address"],
                    "pincode": spec["pincode"],
                    "is_active": True,
                },
            )
            for code, price in spec["prices"].items():
                CentreTest.objects.update_or_create(
                    centre=centre,
                    test=tests[code],
                    defaults={"price": Decimal(price), "is_active": True},
                )

        self.stdout.write(
            self.style.SUCCESS(f"Seeded {len(TESTS)} tests across {len(CENTRES)} centres.")
        )
