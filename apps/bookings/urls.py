from django.urls import path

from apps.bookings import views

urlpatterns = [
    path("", views.BookingListCreateView.as_view(), name="booking-list"),
    path("<uuid:booking_id>/", views.BookingDetailView.as_view(), name="booking-detail"),
    path("<uuid:booking_id>/cancel/", views.BookingCancelView.as_view(), name="booking-cancel"),
]
