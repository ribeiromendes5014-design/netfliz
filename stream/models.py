from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def _generate_unique_slug(model, base, instance=None):
    slug = slugify(base or "")
    if not slug:
        slug = "tenant"
    original = slug
    idx = 1
    while model.objects.exclude(pk=getattr(instance, "pk", None)).filter(slug=slug).exists():
        slug = f"{original}-{idx}"
        idx += 1
    return slug


class Tenant(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tenant_profile",
    )
    slug = models.SlugField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    access_end_date = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    show_subscription_popup = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.slug})"

    @property
    def is_subscription_active(self):
        return not self.access_end_date or self.access_end_date >= timezone.now()

    def _prepare_slug(self):
        if not self.slug:
            self.slug = _generate_unique_slug(
                Tenant,
                self.user.get_full_name() or self.user.email or self.user.username,
                instance=self,
            )

    def save(self, *args, **kwargs):
        previous = None
        if self.pk:
            previous = Tenant.objects.filter(pk=self.pk).only("access_end_date").first()
        self._prepare_slug()
        if (
            previous
            and self.access_end_date
            and previous.access_end_date
            and self.access_end_date > previous.access_end_date
        ):
            self.show_subscription_popup = True
        elif not previous and self.access_end_date:
            self.show_subscription_popup = True
        super().save(*args, **kwargs)


class Series(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="series",
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True)
    cover_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("tenant", "slug")
        ordering = ("title",)

    def __str__(self):
        return f"{self.title} ({self.tenant.slug})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _generate_unique_slug(Series, self.title, instance=self)
        super().save(*args, **kwargs)


class Video(models.Model):
    EMBED_TYPE = "iframe"
    VIDEO_ELEMENT_TYPES = {"mp4", "m3u8"}
    VIDEO_TYPES = (
        ("mp4", "MP4"),
        ("m3u8", "HLS / M3U8"),
        (EMBED_TYPE, "Embed (iframe)"),
    )

    series = models.ForeignKey(
        Series,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="episodes",
    )
    season_number = models.PositiveIntegerField(null=True, blank=True)
    episode_number = models.PositiveIntegerField(null=True, blank=True)

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="videos")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True)
    source_url = models.TextField(max_length=2048)
    video_type = models.CharField(max_length=10, choices=VIDEO_TYPES, default="mp4")
    cover_url = models.URLField(blank=True)
    CATEGORY_MOVIE = "movie"
    CATEGORY_SERIES = "series"
    CATEGORY_TV = "tv"
    CATEGORY_CHOICES = (
        (CATEGORY_MOVIE, "Filmes"),
        (CATEGORY_SERIES, "Séries"),
        (CATEGORY_TV, "TV"),
    )
    category = models.CharField(
        max_length=16,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_MOVIE,
        help_text="Classifique este conteúdo como filme, série ou canal de TV.",
    )
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    blocked_tenants = models.ManyToManyField(
        Tenant,
        blank=True,
        related_name="blocked_videos",
        help_text="Marque os tenants que não devem ver este vídeo.",
    )
    rotate_180 = models.BooleanField(
        default=False,
        help_text="Rotacione o vídeo em 180° durante a reprodução.",
    )

    class Meta:
        unique_together = ("tenant", "slug")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.title} ({self.tenant.slug})"

    @property
    def stream_mime(self):
        if self.video_type == "m3u8":
            return "application/x-mpegURL"
        if self.video_type == "mp4":
            return "video/mp4"
        return ""

    @property
    def uses_video_element(self):
        return self.video_type in self.VIDEO_ELEMENT_TYPES

    @property
    def uses_iframe_player(self):
        return self.video_type == self.EMBED_TYPE

    def is_visible_to(self, tenant):
        return not self.blocked_tenants.filter(pk=tenant.pk).exists()


class VideoProgress(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="video_progress")
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="progress_entries")
    position = models.FloatField(default=0.0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("tenant", "video")
