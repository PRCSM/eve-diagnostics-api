"""Catalog write operations. Reads live in the views as queryset filters."""

import logging
import uuid
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Model

from apps.catalog.exceptions import (
    DiagnosticTestCodeExists,
    DiagnosticTestNotFound,
    OfferingExists,
    OfferingNotFound,
)
from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest
from apps.common.db import violated_constraint

logger = logging.getLogger(__name__)


def _apply_changes(instance: Model, changes: dict[str, Any]) -> None:
    for field, value in changes.items():
        setattr(instance, field, value)
    instance.save(update_fields=[*changes, "updated_at"])


# --- Centres ----------------------------------------------------------------------------------


def create_centre(**fields: Any) -> DiagnosticCentre:
    centre = DiagnosticCentre.objects.create(**fields)
    logger.info("catalog.centre_created", extra={"centre_id": str(centre.id)})
    return centre


def update_centre(centre: DiagnosticCentre, **changes: Any) -> DiagnosticCentre:
    _apply_changes(centre, changes)
    return centre


def deactivate_centre(centre: DiagnosticCentre) -> None:
    """Soft delete: existing bookings keep referencing the centre; new bookings are refused."""
    _apply_changes(centre, {"is_active": False})
    logger.info("catalog.centre_deactivated", extra={"centre_id": str(centre.id)})


# --- Tests ------------------------------------------------------------------------------------


def _save_test(test: DiagnosticTest, changes: dict[str, Any] | None = None) -> DiagnosticTest:
    try:
        with transaction.atomic():
            if changes is None:
                test.save()
            else:
                _apply_changes(test, changes)
    except IntegrityError as exc:
        if violated_constraint(exc) == "catalog_test_code_unique":
            raise DiagnosticTestCodeExists() from exc
        raise
    return test


def create_test(**fields: Any) -> DiagnosticTest:
    test = _save_test(DiagnosticTest(**fields))
    logger.info("catalog.test_created", extra={"test_id": str(test.id)})
    return test


def update_test(test: DiagnosticTest, **changes: Any) -> DiagnosticTest:
    return _save_test(test, changes)


def deactivate_test(test: DiagnosticTest) -> None:
    _apply_changes(test, {"is_active": False})
    logger.info("catalog.test_deactivated", extra={"test_id": str(test.id)})


# --- Offerings --------------------------------------------------------------------------------


def add_offering(*, centre: DiagnosticCentre, test_id: uuid.UUID, price: Decimal) -> CentreTest:
    try:
        test = DiagnosticTest.objects.get(pk=test_id)
    except DiagnosticTest.DoesNotExist as exc:
        raise DiagnosticTestNotFound() from exc
    try:
        with transaction.atomic():
            offering = CentreTest.objects.create(centre=centre, test=test, price=price)
    except IntegrityError as exc:
        if violated_constraint(exc) == "catalog_offering_centre_test_unique":
            raise OfferingExists() from exc
        raise
    logger.info(
        "catalog.offering_added",
        extra={
            "centre_id": str(centre.id),
            "test_id": str(test.id),
            "offering_id": str(offering.id),
        },
    )
    return offering


def update_offering(offering: CentreTest, **changes: Any) -> CentreTest:
    """Price changes only affect new bookings: bookings snapshot the amount when created."""
    _apply_changes(offering, changes)
    logger.info("catalog.offering_updated", extra={"offering_id": str(offering.id)})
    return offering


def deactivate_offering(offering: CentreTest) -> None:
    _apply_changes(offering, {"is_active": False})
    logger.info("catalog.offering_deactivated", extra={"offering_id": str(offering.id)})


def get_bookable_offering(*, centre_id: uuid.UUID, test_id: uuid.UUID) -> CentreTest:
    """The active offering of `test_id` at `centre_id`, or OfferingNotFound."""
    try:
        return (
            CentreTest.objects.bookable()
            .select_related("centre", "test")
            .get(centre_id=centre_id, test_id=test_id)
        )
    except CentreTest.DoesNotExist as exc:
        raise OfferingNotFound() from exc
