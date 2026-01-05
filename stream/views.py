from django.contrib import messages
from django.contrib.auth import logout as auth_logout, views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.generic import DeleteView, ListView, TemplateView, UpdateView
from django.views.generic.base import View

import requests
import re

from .forms import PortalLoginForm, VideoForm
from .models import Tenant, Video, VideoProgress


def get_tenant_from_slug(slug):
    tenant = Tenant.objects.filter(slug=slug, is_active=True).first()
    if not tenant:
        raise Http404("Tenant não encontrado ou inativo.")
    if tenant.access_end_date and tenant.access_end_date < timezone.now():
        raise Http404("Assinatura expirada.")
    return tenant



GOOGLE_DRIVE_DOWNLOAD_URL = "https://docs.google.com/uc"
GOOGLE_DRIVE_DOWNLOAD_PARAMS = {"export": "download"}

DRIVE_ID_PATTERNS = [
    r"/file/d/([0-9A-Za-z_-]+)",
    r"id=([0-9A-Za-z_-]+)",
    r"/open\\?id=([0-9A-Za-z_-]+)",
]
CONFIRM_TOKEN_PATTERN = re.compile(r"confirm=([0-9A-Za-z_-]+)")


def _extract_confirm_token(body):
    match = CONFIRM_TOKEN_PATTERN.search(body)
    return match.group(1) if match else None
CONFIRM_TOKEN_PATTERN = re.compile(r"confirm=([0-9A-Za-z_-]+)")
CONFIRM_TOKEN_PATTERN = re.compile(r"confirm=([0-9A-Za-z_-]+)")

def get_or_create_owner_tenant(user):
    tenant = getattr(user, "tenant_profile", None)
    if tenant is not None:
        return tenant
    base = slugify(
        user.get_full_name()
        or user.username
        or user.email
        or "proprietario"
    )
    if not base:
        base = "proprietario"
    slug = base
    idx = 1
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base}-{idx}"
        idx += 1
    return Tenant.objects.create(user=user, slug=slug)


def _extract_google_drive_id(url):
    if not url:
        return None
    for pattern in DRIVE_ID_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _follow_drive_download(file_id):
    session = requests.Session()
    params = {**GOOGLE_DRIVE_DOWNLOAD_PARAMS, "id": file_id}
    response = session.get(GOOGLE_DRIVE_DOWNLOAD_URL, params=params, stream=True)
    if response.status_code != 200:
        return response
    token = None
    for key, value in response.cookies.items():
        if key.startswith("download_warning"):
            token = value
            break
    if not token:
        token = _extract_confirm_token(response.text)
    if token:
        params["confirm"] = token
        response = session.get(GOOGLE_DRIVE_DOWNLOAD_URL, params=params, stream=True)
    return response


def google_drive_stream(request):
    file_id = request.GET.get("id")
    if not file_id:
        raise Http404("Arquivo do Google Drive não informado.")
    response = _follow_drive_download(file_id)
    if response.status_code != 200:
        raise Http404("Não foi possível acessar o arquivo do Google Drive.")
    content_type = response.headers.get("Content-Type", "application/octet-stream")
    content_length = response.headers.get("Content-Length")
    stream = StreamingHttpResponse(response.iter_content(chunk_size=8192), content_type=content_type)
    if content_length:
        stream["Content-Length"] = content_length
    stream["Content-Disposition"] = f'inline; filename="{file_id}"'
    return stream


def get_playback_source(source_url):
    drive_id = _extract_google_drive_id(source_url)
    if drive_id:
        return reverse("stream:google-drive-stream") + f"?id={drive_id}"
    return source_url


def format_duration_label(seconds):
    try:
        total_seconds = int(float(seconds))
    except (TypeError, ValueError):
        total_seconds = 0
    if total_seconds < 0:
        total_seconds = 0
    minutes, secs = divmod(total_seconds, 60)
    return f"{minutes}:{secs:02d}"


class TenantOwnerMixin:
    def get_tenant(self):
        tenant = getattr(self.request.user, "tenant_profile", None)
        if not tenant:
            raise PermissionDenied("Usuário sem tenant vinculado.")
        return tenant

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant = self.get_tenant()
        return queryset.filter(tenant=tenant)


class PublicLandingView(TemplateView):
    def get(self, request, *args, **kwargs):
        return redirect("login")


class TenantPublicView(TemplateView):
    template_name = "stream/tenant_public.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = get_tenant_from_slug(kwargs["slug"])
        context["tenant"] = tenant
        context["videos"] = tenant.videos.filter(is_public=True).filter(
            models.Q(blocked_tenants__isnull=True) | ~models.Q(blocked_tenants=tenant)
        ).distinct()
        return context


class TenantPortalView(LoginRequiredMixin, ListView):
    model = Video
    template_name = "stream/tenant_portal.html"
    context_object_name = "videos"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["tenant"] = getattr(self.request.user, "tenant_profile", None)
        context["progress_map"] = getattr(self, "_progress_map", {})
        context["continue_videos"] = getattr(self, "_continue_videos", [])
        return context

    def get_queryset(self):
        tenant = getattr(self.request.user, "tenant_profile", None)
        queryset = Video.objects.filter(is_public=True)
        if tenant:
            queryset = queryset.filter(
                models.Q(blocked_tenants__isnull=True) | ~models.Q(blocked_tenants=tenant)
            )
        else:
            queryset = queryset.filter(blocked_tenants__isnull=True)
        queryset = queryset.distinct()
        progress_entries = []
        if tenant:
            progress_entries = list(
                VideoProgress.objects.filter(tenant=tenant, video__in=queryset).select_related("video")
            )
        progress_map = {progress.video_id: progress.position for progress in progress_entries}
        for video in queryset:
            setattr(video, "resume_position", progress_map.get(video.id, 0))

        continue_videos = []
        if progress_entries:
            continue_entries = [
                progress for progress in progress_entries if progress.position > 0
            ]
            continue_entries.sort(key=lambda entry: entry.updated_at, reverse=True)
            continue_videos = [entry.video for entry in continue_entries[:4]]
            for video in continue_videos:
                video.resume_position = progress_map.get(video.id, 0)
                video.resume_label = format_duration_label(video.resume_position)

        self._progress_map = progress_map
        self._continue_videos = continue_videos
        return queryset


class ResetContinueView(LoginRequiredMixin, View):
    def post(self, request, video_slug):
        tenant = getattr(request.user, "tenant_profile", None)
        if not tenant:
            raise PermissionDenied("Usuário sem tenant vinculado.")
        video = get_object_or_404(Video, slug=video_slug, is_public=True)
        if not video.is_visible_to(tenant):
            raise Http404("Vídeo indisponível.")
        progress = VideoProgress.objects.filter(tenant=tenant, video=video)
        if progress.exists():
            progress.delete()
            messages.success(request, f'Progresso de "{video.title}" reiniciado.')
        else:
            messages.info(request, f'Nenhum progresso registrado para "{video.title}".')
        return redirect("stream:tenant-portal")


class WatchVideoView(TemplateView):
    template_name = "stream/watch_video.html"

    def get(self, request, slug, video_slug):
        tenant = get_tenant_from_slug(slug)
        queryset = Video.objects.filter(slug=video_slug, is_public=True)
        queryset = queryset.filter(
            models.Q(blocked_tenants__isnull=True) | ~models.Q(blocked_tenants=tenant)
        )
        video = queryset.first()
        if not video:
            raise Http404("Vídeo não disponível para este tenant.")
        progress_obj = VideoProgress.objects.filter(tenant=tenant, video=video).first()
        return render(
            request,
            self.template_name,
            {
                "tenant": tenant,
                "video": video,
                "progress_position": progress_obj.position if progress_obj else 0,
                "progress_url": reverse(
                    "stream:video-progress", kwargs={"slug": slug, "video_slug": video_slug}
                ),
                "video_stream_url": get_playback_source(video.source_url),
            },
        )


class OwnerDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "stream/owner_dashboard.html"

    def test_func(self):
        return self.request.user.is_active and self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["tenants"] = Tenant.objects.filter(is_active=True)
        owner_tenant = get_or_create_owner_tenant(self.request.user)
        context["video_form"] = VideoForm(owner=owner_tenant)
        context["videos"] = Video.objects.filter(tenant=owner_tenant)
        return context

    def post(self, request, *args, **kwargs):
        owner_tenant = get_or_create_owner_tenant(self.request.user)
        form = VideoForm(request.POST, owner=owner_tenant)
        if form.is_valid():
            video = form.save(commit=False)
            video.tenant = owner_tenant
            video.is_public = True
            video.save()
            form.save_m2m()
            blocked = form.cleaned_data["blocked_tenants"]
            if blocked:
                names = ", ".join(sorted(t.slug for t in blocked))
            else:
                names = "todos os tenants"
            messages.success(
                request,
                f"Vídeo {video.title} cadastrado e oculto para: {names}.",
            )
            return redirect("stream:owner-dashboard")
        context = self.get_context_data(**kwargs)
        context["video_form"] = form
        return self.render_to_response(context)


class OwnerVideoPermissionMixin(UserPassesTestMixin):
    def test_func(self):
        video = self.get_object()
        owner_tenant = get_or_create_owner_tenant(self.request.user)
        return self.request.user.is_active and self.request.user.is_staff and video.tenant == owner_tenant


class OwnerVideoEditView(LoginRequiredMixin, OwnerVideoPermissionMixin, UpdateView):
    model = Video
    form_class = VideoForm
    template_name = "stream/video_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["owner"] = get_or_create_owner_tenant(self.request.user)
        return kwargs

    def get_success_url(self):
        return reverse("stream:owner-dashboard")


class OwnerVideoDeleteView(LoginRequiredMixin, OwnerVideoPermissionMixin, DeleteView):
    model = Video
    template_name = "stream/video_confirm_delete.html"

    def get_success_url(self):
        return reverse("stream:owner-dashboard")


class VideoProgressView(LoginRequiredMixin, View):
    def post(self, request, slug, video_slug):
        tenant = get_tenant_from_slug(slug)
        user_tenant = getattr(request.user, "tenant_profile", None)
        if user_tenant != tenant:
            return JsonResponse({"detail": "Acesso negado."}, status=403)
        video = get_object_or_404(Video, slug=video_slug)
        if not video.is_visible_to(tenant):
            return JsonResponse({"detail": "Vídeo indisponível."}, status=404)
        position = 0.0
        if request.content_type == "application/json":
            import json

            try:
                payload = json.loads(request.body.decode())
                position = float(payload.get("position", 0.0))
            except (ValueError, json.JSONDecodeError):
                position = 0.0
        else:
            try:
                position = float(request.POST.get("position", 0.0))
            except (ValueError, TypeError):
                position = 0.0
        position = max(0.0, position)
        progress, _ = VideoProgress.objects.get_or_create(tenant=tenant, video=video)
        progress.position = position
        progress.save(update_fields=["position", "updated_at"])
        return JsonResponse({"position": progress.position})


class OwnerLoginView(auth_views.LoginView):
    template_name = "stream/painel_login.html"
    redirect_authenticated_user = True
    authentication_form = PortalLoginForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_staff:
            auth_logout(request)
        list(messages.get_messages(request))
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("stream:owner-dashboard")

    def form_valid(self, form):
        user = form.get_user()
        if not (user.is_active and user.is_staff):
            form.add_error(None, "Acesso restrito a proprietários.")
            return self.form_invalid(form)
        return super().form_valid(form)


class TenantLoginView(auth_views.LoginView):
    template_name = "stream/login.html"
    authentication_form = PortalLoginForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        list(messages.get_messages(request))
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        user = self.request.user
        if user.is_authenticated and user.is_staff:
            return reverse("stream:owner-dashboard")
        return reverse("stream:tenant-portal")


class SubscriptionExpiredView(TemplateView):
    template_name = "stream/subscription_expired.html"


class SupportView(TemplateView):
    template_name = "stream/support.html"
