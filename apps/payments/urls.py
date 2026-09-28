from django.urls import path

from apps.payments import views

urlpatterns = [
    path("", views.PaymentCreateView.as_view(), name="payment-create"),
    path("<uuid:payment_id>/", views.PaymentDetailView.as_view(), name="payment-detail"),
]
