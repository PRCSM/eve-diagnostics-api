from django.db.models import Prefetch, Q, QuerySet
from django.db.models.functions import Lower
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from apps.catalog import services
from apps.catalog.exceptions import CentreNotFound, DiagnosticTestNotFound, OfferingNotFound
from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest
from apps.catalog.serializers import (
    CentreDetailSerializer,
    CentreListQuerySerializer,
    CentreSerializer,
    CentreWriteSerializer,
    DiagnosticTestListQuerySerializer,
    DiagnosticTestSerializer,
    DiagnosticTestWriteSerializer,
    IncludeInactiveQuerySerializer,
    OfferingCreateSerializer,
    OfferingSerializer,
    OfferingUpdateSerializer,
)
from apps.common.permissions import IsAdminOrReadOnly


class CatalogView(GenericAPIView):
    """Shared behaviour: public reads, staff-only writes, staff may see inactive records."""

    permission_classes = [IsAdminOrReadOnly]

    @property
    def is_staff(self) -> bool:
        user = self.request.user
        return bool(user and user.is_authenticated and user.is_staff)

    def query_params(self, serializer_class) -> dict:
        serializer = serializer_class(data=self.request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def show_inactive(self, params: dict | None = None) -> bool:
        """Staff see inactive records on detail endpoints, and on lists when they ask to."""
        if not self.is_staff:
            return False
        return True if params is None else params.get("include_inactive", False)

    def paginated(self, queryset: QuerySet, serializer_class) -> Response:
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(serializer_class(page, many=True).data)


def _active_offerings_prefetch() -> Prefetch:
    return Prefetch(
        "offerings",
        queryset=CentreTest.objects.filter(is_active=True, test__is_active=True)
        .select_related("test")
        .order_by("test__name"),
        to_attr="active_offerings",
    )


# --- Centres ----------------------------------------------------------------------------------


class CentreListCreateView(CatalogView):
    filter_backends = [OrderingFilter]
    ordering_fields = ["name", "city", "created_at"]
    ordering = ["name"]

    def get_queryset(self) -> QuerySet:
        params = self.query_params(CentreListQuerySerializer)
        queryset = DiagnosticCentre.objects.all()
        if not self.show_inactive(params):
            queryset = queryset.active()
        if city := params.get("city"):
            # Matches the functional index on lower(city).
            queryset = queryset.alias(city_ci=Lower("city")).filter(city_ci=city.strip().lower())
        if test_id := params.get("test"):
            queryset = queryset.filter(
                offerings__test_id=test_id,
                offerings__is_active=True,
                offerings__test__is_active=True,
            )
        if search := params.get("search"):
            queryset = queryset.filter(name__icontains=search)
        return queryset

    @extend_schema(
        tags=["catalog"],
        parameters=[CentreListQuerySerializer],
        responses={200: CentreSerializer(many=True)},
    )
    def get(self, request):
        """List diagnostic centres (public)."""
        return self.paginated(self.filter_queryset(self.get_queryset()), CentreSerializer)

    @extend_schema(
        tags=["catalog"], request=CentreWriteSerializer, responses={201: CentreSerializer}
    )
    def post(self, request):
        """Create a centre (staff only)."""
        serializer = CentreWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        centre = services.create_centre(**serializer.validated_data)
        return Response(CentreSerializer(centre).data, status=status.HTTP_201_CREATED)


class CentreDetailView(CatalogView):
    def get_object(self) -> DiagnosticCentre:
        queryset = DiagnosticCentre.objects.prefetch_related(_active_offerings_prefetch())
        if not self.show_inactive():
            queryset = queryset.active()
        try:
            return queryset.get(pk=self.kwargs["centre_id"])
        except DiagnosticCentre.DoesNotExist as exc:
            raise CentreNotFound() from exc

    @extend_schema(tags=["catalog"], responses={200: CentreDetailSerializer})
    def get(self, request, centre_id):
        """A centre with the tests it offers and their prices (public)."""
        return Response(CentreDetailSerializer(self.get_object()).data)

    @extend_schema(
        tags=["catalog"],
        request=CentreWriteSerializer(partial=True),
        responses={200: CentreSerializer},
    )
    def patch(self, request, centre_id):
        """Update a centre (staff only)."""
        centre = self.get_object()
        serializer = CentreWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_centre(centre, **serializer.validated_data)
        return Response(CentreSerializer(centre).data)

    @extend_schema(tags=["catalog"], responses={204: None})
    def delete(self, request, centre_id):
        """Deactivate a centre (staff only). Soft delete; history is preserved."""
        services.deactivate_centre(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Diagnostic tests -------------------------------------------------------------------------


class DiagnosticTestListCreateView(CatalogView):
    filter_backends = [OrderingFilter]
    ordering_fields = ["name", "code", "created_at"]
    ordering = ["name"]

    def get_queryset(self) -> QuerySet:
        params = self.query_params(DiagnosticTestListQuerySerializer)
        queryset = DiagnosticTest.objects.all()
        if not self.show_inactive(params):
            queryset = queryset.active()
        if search := params.get("search"):
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__iexact=search))
        return queryset

    @extend_schema(
        tags=["catalog"],
        parameters=[DiagnosticTestListQuerySerializer],
        responses={200: DiagnosticTestSerializer(many=True)},
    )
    def get(self, request):
        """List diagnostic tests (public)."""
        return self.paginated(self.filter_queryset(self.get_queryset()), DiagnosticTestSerializer)

    @extend_schema(
        tags=["catalog"],
        request=DiagnosticTestWriteSerializer,
        responses={201: DiagnosticTestSerializer},
    )
    def post(self, request):
        """Create a diagnostic test (staff only)."""
        serializer = DiagnosticTestWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        test = services.create_test(**serializer.validated_data)
        return Response(DiagnosticTestSerializer(test).data, status=status.HTTP_201_CREATED)


class DiagnosticTestDetailView(CatalogView):
    def get_object(self) -> DiagnosticTest:
        queryset = DiagnosticTest.objects.all()
        if not self.show_inactive():
            queryset = queryset.active()
        try:
            return queryset.get(pk=self.kwargs["test_id"])
        except DiagnosticTest.DoesNotExist as exc:
            raise DiagnosticTestNotFound() from exc

    @extend_schema(tags=["catalog"], responses={200: DiagnosticTestSerializer})
    def get(self, request, test_id):
        return Response(DiagnosticTestSerializer(self.get_object()).data)

    @extend_schema(
        tags=["catalog"],
        request=DiagnosticTestWriteSerializer(partial=True),
        responses={200: DiagnosticTestSerializer},
    )
    def patch(self, request, test_id):
        """Update a diagnostic test (staff only)."""
        test = self.get_object()
        serializer = DiagnosticTestWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_test(test, **serializer.validated_data)
        return Response(DiagnosticTestSerializer(test).data)

    @extend_schema(tags=["catalog"], responses={204: None})
    def delete(self, request, test_id):
        """Deactivate a diagnostic test everywhere (staff only)."""
        services.deactivate_test(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Offerings (tests at a centre) ------------------------------------------------------------


class OfferingView(CatalogView):
    def get_centre(self) -> DiagnosticCentre:
        queryset = DiagnosticCentre.objects.all()
        if not self.show_inactive():
            queryset = queryset.active()
        try:
            return queryset.get(pk=self.kwargs["centre_id"])
        except DiagnosticCentre.DoesNotExist as exc:
            raise CentreNotFound() from exc

    def offerings(self, centre: DiagnosticCentre, include_inactive: bool) -> QuerySet:
        queryset = CentreTest.objects.filter(centre=centre).select_related("test")
        if not include_inactive:
            queryset = queryset.filter(is_active=True, test__is_active=True)
        return queryset.order_by("test__name")


class OfferingListCreateView(OfferingView):
    @extend_schema(
        tags=["catalog"],
        parameters=[IncludeInactiveQuerySerializer],
        responses={200: OfferingSerializer(many=True)},
    )
    def get(self, request, centre_id):
        """Tests offered at a centre, with prices (public)."""
        params = self.query_params(IncludeInactiveQuerySerializer)
        centre = self.get_centre()
        return self.paginated(
            self.offerings(centre, self.show_inactive(params)), OfferingSerializer
        )

    @extend_schema(
        tags=["catalog"], request=OfferingCreateSerializer, responses={201: OfferingSerializer}
    )
    def post(self, request, centre_id):
        """Offer a test at this centre at a price (staff only)."""
        centre = self.get_centre()
        serializer = OfferingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        offering = services.add_offering(centre=centre, **serializer.validated_data)
        return Response(OfferingSerializer(offering).data, status=status.HTTP_201_CREATED)


class OfferingDetailView(OfferingView):
    def get_object(self) -> CentreTest:
        centre = self.get_centre()
        try:
            return self.offerings(centre, self.show_inactive()).get(test_id=self.kwargs["test_id"])
        except CentreTest.DoesNotExist as exc:
            raise OfferingNotFound() from exc

    @extend_schema(tags=["catalog"], responses={200: OfferingSerializer})
    def get(self, request, centre_id, test_id):
        return Response(OfferingSerializer(self.get_object()).data)

    @extend_schema(
        tags=["catalog"], request=OfferingUpdateSerializer, responses={200: OfferingSerializer}
    )
    def patch(self, request, centre_id, test_id):
        """Change the price or re-enable/disable an offering (staff only)."""
        offering = self.get_object()
        serializer = OfferingUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_offering(offering, **serializer.validated_data)
        return Response(OfferingSerializer(offering).data)

    @extend_schema(tags=["catalog"], responses={204: None})
    def delete(self, request, centre_id, test_id):
        """Stop offering this test at this centre (staff only)."""
        services.deactivate_offering(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)
