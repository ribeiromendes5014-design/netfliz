from django.urls import path

from .views import (
    OwnerDashboardView,
    OwnerLoginView,
    OwnerVideoDeleteView,
    OwnerVideoEditView,
    PublicLandingView,
    SubscriptionExpiredView,
    SupportView,
    TenantPortalView,
    TenantPublicView,
    VideoProgressView,
    WatchVideoView,
    ResetContinueView,
    google_drive_stream,
)

app_name = "stream"

urlpatterns = [
    path("", PublicLandingView.as_view(), name="public-home"),
    path("tenant/<slug:slug>/", TenantPublicView.as_view(), name="tenant-home"),
    path(
        "tenant/<slug:slug>/watch/<slug:video_slug>/",
        WatchVideoView.as_view(),
        name="tenant-watch",
    ),
    path(
        "tenant/<slug:slug>/watch/<slug:video_slug>/progress/",
        VideoProgressView.as_view(),
        name="video-progress",
    ),
    path("portal/", TenantPortalView.as_view(), name="tenant-portal"),
    path("portal/reset/<slug:video_slug>/", ResetContinueView.as_view(), name="portal-reset"),
    path("portal/reset/<slug:video_slug>/", ResetContinueView.as_view(), name="portal-reset"),
    path("painel/login/", OwnerLoginView.as_view(), name="owner-login"),
    path("owner/", OwnerDashboardView.as_view(), name="owner-dashboard"),
    path("owner/video/<int:pk>/edit/", OwnerVideoEditView.as_view(), name="owner-video-edit"),
    path("owner/video/<int:pk>/delete/", OwnerVideoDeleteView.as_view(), name="owner-video-delete"),
    path("subscription-expired/", SubscriptionExpiredView.as_view(), name="subscription-expired"),
    path("support/", SupportView.as_view(), name="support"),
    path("drive/", google_drive_stream, name="google-drive-stream"),
]
