from django.urls import path

from apps.catalog import views

urlpatterns = [
    path("centres/", views.CentreListCreateView.as_view(), name="centre-list"),
    path("centres/<uuid:centre_id>/", views.CentreDetailView.as_view(), name="centre-detail"),
    path(
        "centres/<uuid:centre_id>/tests/",
        views.OfferingListCreateView.as_view(),
        name="offering-list",
    ),
    path(
        "centres/<uuid:centre_id>/tests/<uuid:test_id>/",
        views.OfferingDetailView.as_view(),
        name="offering-detail",
    ),
    path("tests/", views.DiagnosticTestListCreateView.as_view(), name="test-list"),
    path("tests/<uuid:test_id>/", views.DiagnosticTestDetailView.as_view(), name="test-detail"),
]
