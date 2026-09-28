from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.common.views import liveness, readiness

api_v1_patterns = [
    path("auth/", include("apps.accounts.urls")),
    path("", include("apps.catalog.urls")),
    path("bookings/", include("apps.bookings.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/live/", liveness, name="health-live"),
    path("health/ready/", readiness, name="health-ready"),
    path("api/v1/", include(api_v1_patterns)),
]

if settings.API_DOCS_ENABLED:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]

handler404 = "apps.common.views.json_not_found"
handler500 = "apps.common.views.json_server_error"
