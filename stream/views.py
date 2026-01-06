import json
import logging

from django.contrib import messages
from django.contrib.auth import logout as auth_logout, views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Count
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.generic import DeleteView, ListView, TemplateView, UpdateView
from django.views.generic.base import View

import requests
import re

logger = logging.getLogger(__name__)

from .forms import PortalLoginForm, SeriesForm, VideoForm
from .models import Series, Tenant, Video, VideoProgress


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

M3U8_URL_PATTERN = re.compile(r"https?://[^\"'\\s<>]+\\.m3u8[^\"'\\s<>]*", re.IGNORECASE)

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
    stream["Cache-Control"] = "public, max-age=86400"
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
    CACHE_TIMEOUT = 60 * 15

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["tenant"] = getattr(self.request.user, "tenant_profile", None)
        context["progress_map"] = getattr(self, "_progress_map", {})
        context["continue_videos"] = getattr(self, "_continue_videos", [])
        context["series_list"] = getattr(self, "_series_list", [])
        context["series_payload"] = getattr(self, "_series_payload_json", "[]")
        context["tv_channels"] = getattr(self, "_tv_channels", [])
        context["videos"] = getattr(self, "_movies", context.get("videos", []))
        context["continue_movies"] = getattr(self, "_continue_movies", [])
        context["continue_series"] = getattr(self, "_continue_series", [])
        context["continue_tv"] = getattr(self, "_continue_tv", [])
        return context

    def get_queryset(self):
        tenant = getattr(self.request.user, "tenant_profile", None)
        cache_key = self._get_cache_key(tenant)
        payload = cache.get(cache_key)
        if payload is None:
            payload = self._build_portal_payload(tenant)
            cache.set(cache_key, payload, timeout=self.CACHE_TIMEOUT)
        self._apply_portal_payload(payload)
        return payload["movie_videos"]

    def _get_cache_key(self, tenant):
        slug = getattr(tenant, "slug", None) or "anonymous"
        return f"tenant_portal:{slug}"

    def _apply_portal_payload(self, payload):
        self._progress_map = payload.get("progress_map", {})
        self._continue_videos = payload.get("continue_videos", [])
        self._continue_movies = payload.get("continue_movies", [])
        self._continue_series = payload.get("continue_series", [])
        self._continue_tv = payload.get("continue_tv", [])
        self._series_list = payload.get("series_list", [])
        self._series_payload_json = payload.get("series_payload_json", "[]")
        self._tv_channels = payload.get("tv_channels", [])
        self._movies = payload.get("movie_videos", [])
        self._videos_by_genre = payload.get("videos_by_genre", {})

    def _build_portal_payload(self, tenant):
        queryset = Video.objects.filter(is_public=True)
        if tenant:
            queryset = queryset.filter(
                models.Q(blocked_tenants__isnull=True) | ~models.Q(blocked_tenants=tenant)
            )
        else:
            queryset = queryset.filter(blocked_tenants__isnull=True)
        queryset = queryset.distinct()
        all_videos = list(queryset)
        progress_entries = []
        if tenant:
            progress_entries = list(
                VideoProgress.objects.filter(tenant=tenant, video__in=queryset).select_related("video")
            )
        progress_map = {progress.video_id: progress.position for progress in progress_entries}
        for video in all_videos:
            setattr(video, "resume_position", progress_map.get(video.id, 0))
            setattr(video, "resume_label", format_duration_label(progress_map.get(video.id, 0)))

        continue_videos = []
        if progress_entries:
            continue_entries = [
                progress for progress in progress_entries if progress.position > 0
            ]
            continue_entries.sort(key=lambda entry: entry.updated_at, reverse=True)
            continue_videos = [entry.video for entry in continue_entries[:20]]
            for video in continue_videos:
                video.resume_position = progress_map.get(video.id, 0)
                video.resume_label = format_duration_label(video.resume_position)

        continue_movies = [video for video in continue_videos if not video.series_id and video.category == Video.CATEGORY_MOVIE]
        continue_series = [video for video in continue_videos if video.series_id]
        continue_tv = [video for video in continue_videos if video.category == Video.CATEGORY_TV]

        series_payload, series_models = self._build_series_data(tenant, all_videos, progress_map)
        standalone_videos = [video for video in all_videos if not video.series_id]

        tv_channels = [video for video in standalone_videos if video.category == Video.CATEGORY_TV]
        videos_by_genre = {}
        for video in standalone_videos:
            if video.category == Video.CATEGORY_MOVIE:
                videos_by_genre.setdefault(video.genre or "outro", []).append(video)

        movie_videos = [video for video in standalone_videos if video.category == Video.CATEGORY_MOVIE]

        return {
            "progress_map": progress_map,
            "continue_videos": continue_videos,
            "continue_movies": continue_movies,
            "continue_series": continue_series,
            "continue_tv": continue_tv,
            "series_list": series_models,
            "series_payload_json": json.dumps(series_payload, cls=DjangoJSONEncoder),
            "tv_channels": tv_channels,
            "movie_videos": movie_videos,
            "videos_by_genre": videos_by_genre,
        }

    def _build_series_data(self, tenant, all_videos, progress_map):
        if not tenant:
            return [], []
        video_by_series = {}
        for video in all_videos:
            if not video.series_id:
                continue
            video_by_series.setdefault(video.series_id, []).append(video)
        series_payload = []
        series_ids = sorted(video_by_series.keys())
        series_qs = (
            Series.objects.filter(id__in=series_ids, is_active=True)
            .annotate(episode_count=Count("episodes"))
            .order_by("title")
        )
        series_models = list(series_qs)
        for series in series_models:
            episodes = video_by_series.get(series.id, [])
            episodes_sorted = sorted(
                episodes,
                key=lambda v: (
                    v.season_number or 1,
                    v.episode_number or 0,
                    v.created_at or timezone.now(),
                ),
            )
            episode_entries = []
            for idx, video in enumerate(episodes_sorted, start=1):
                season_number = video.season_number or 1
                episode_number = video.episode_number or idx
                resume_position = progress_map.get(video.id, 0)
                resume_label = (
                    format_duration_label(resume_position) if resume_position > 0 else ""
                )
                episode_entries.append(
                    {
                        "title": video.title,
                        "description": video.description,
                        "season_number": season_number,
                        "episode_number": episode_number,
                        "episode_label": f"S{season_number:02d} • E{episode_number:02d}",
                        "watch_url": reverse(
                            "stream:tenant-watch",
                            kwargs={"slug": tenant.slug, "video_slug": video.slug},
                        ),
                        "resume_position": resume_position,
                        "resume_label": resume_label,
                    }
                )
            seasons = sorted({entry["season_number"] for entry in episode_entries})
            series_payload.append(
                {
                    "title": series.title,
                    "slug": series.slug,
                    "description": series.description,
                    "cover_url": series.cover_url,
                    "episode_count": series.episode_count or len(episode_entries),
                    "seasons": seasons,
                    "episodes": episode_entries,
                }
            )
        return series_payload, series_models


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
        stream_url = None
        if video.uses_video_element:
            stream_url = get_playback_source(video.source_url)
        iframe_autoplay_url = None
        if video.uses_iframe_player:
            base = video.source_url
            separator = "?" if "?" not in base else "&"
            iframe_autoplay_url = f"{base}{separator}autoplay=1&muted=1&playsinline=1"
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
                "video_stream_url": stream_url,
                "autoplay": request.GET.get("autoplay") == "1",
                "iframe_autoplay_url": iframe_autoplay_url,
            },
        )


def _extract_m3u8_url(html):
    match = M3U8_URL_PATTERN.search(html or "")
    return match.group(0) if match else None


class TvChannelStreamView(LoginRequiredMixin, View):
    def get(self, request, video_pk):
        tenant = getattr(request.user, "tenant_profile", None)
        if not tenant:
            raise PermissionDenied("Usuário sem tenant vinculado.")
        video = get_object_or_404(
            Video,
            pk=video_pk,
            is_public=True,
            category=Video.CATEGORY_TV,
        )
        if not video.is_visible_to(tenant):
            raise Http404("Vídeo indisponível para este tenant.")
        try:
            response = requests.get(video.source_url, timeout=10, headers={"User-Agent": "Netfliz/1.0"})
        except requests.RequestException:
            return JsonResponse({"detail": "Não foi possível recuperar o canal."}, status=502)
        if response.status_code != 200:
            return JsonResponse({"detail": "Canal indisponível no momento."}, status=502)
        m3u8_url = _extract_m3u8_url(response.text)
        if not m3u8_url:
            return JsonResponse({"detail": "Não encontramos um link direto de reprodução."}, status=404)
        return JsonResponse({"url": m3u8_url})


class OwnerDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "stream/owner_dashboard.html"

    def test_func(self):
        return self.request.user.is_active and self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tenants'] = Tenant.objects.filter(is_active=True)
        owner_tenant = get_or_create_owner_tenant(self.request.user)
        context['video_form'] = VideoForm(owner=owner_tenant)
        context['series_form'] = SeriesForm()
        context['series_list'] = Series.objects.filter(tenant=owner_tenant)
        context['videos'] = Video.objects.filter(tenant=owner_tenant)
        return context

    def post(self, request, *args, **kwargs):
        owner_tenant = get_or_create_owner_tenant(self.request.user)
        if 'series-submit' in request.POST:
            series_form = SeriesForm(request.POST)
            if series_form.is_valid():
                series = series_form.save(commit=False)
                series.tenant = owner_tenant
                series.save()
                messages.success(request, f"Serie {series.title} cadastrada.")
                return redirect('stream:owner-dashboard')
            context = self.get_context_data(**kwargs)
            context['series_form'] = series_form
            context['video_form'] = VideoForm(owner=owner_tenant)
            return self.render_to_response(context)

        form = VideoForm(request.POST, owner=owner_tenant)
        if form.is_valid():
            video = form.save(commit=False)
            video.tenant = owner_tenant
            video.is_public = True
            video.save()
            form.save_m2m()
            blocked = form.cleaned_data['blocked_tenants']
            if blocked:
                names = ", ".join(sorted(t.slug for t in blocked))
            else:
                names = "todos os tenants"
            messages.success(
                request,
                f"Video {video.title} cadastrado e oculto para: {names}.",
            )
            return redirect('stream:owner-dashboard')
        context = self.get_context_data(**kwargs)
        context['video_form'] = form
        context['series_form'] = SeriesForm()
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
            logger.warning(
                "VideoProgressView access denied: user_tenant=%r tenant=%r",
                user_tenant,
                tenant,
            )
            return JsonResponse({"detail": "Acesso negado."}, status=403)
        video = get_object_or_404(Video, slug=video_slug)
        if not video.is_visible_to(tenant):
            logger.warning(
                "VideoProgressView video blocked: tenant=%r video=%r",
                tenant,
                video_slug,
            )
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
        logger.info(
            "VideoProgressView saved: tenant=%s video=%s position=%.2f",
            tenant.slug,
            video.slug,
            progress.position,
        )
        return JsonResponse({"position": progress.position})


class PwaHeartbeatView(LoginRequiredMixin, View):
    def get(self, request):
        request.session.modified = True
        return JsonResponse({"ok": True})


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
