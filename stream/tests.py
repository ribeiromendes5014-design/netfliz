from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.http import Http404
from django.urls import reverse
from django.utils import timezone

from .models import Tenant, Video
from .views import get_tenant_from_slug


class TenantIsolationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user_one = User.objects.create_user(
            username="tenant-alpha",
            email="alpha@example.com",
            password="password123",
        )
        self.user_two = User.objects.create_user(
            username="tenant-beta",
            email="beta@example.com",
            password="password123",
        )
        self.tenant_one = Tenant.objects.create(
            user=self.user_one,
            slug="tenant-alpha",
            access_end_date=timezone.now() + timedelta(days=30),
        )
        self.tenant_two = Tenant.objects.create(
            user=self.user_two,
            slug="tenant-beta",
            access_end_date=timezone.now() + timedelta(days=30),
        )
        self.video_one = Video.objects.create(
            tenant=self.tenant_one,
            title="Alpha Intro",
            slug="alpha-intro",
            source_url="https://cdn.example.com/videos/alpha.mp4",
            video_type="mp4",
            is_public=False,
        )
        self.video_two = Video.objects.create(
            tenant=self.tenant_two,
            title="Beta Intro",
            slug="beta-intro",
            source_url="https://cdn.example.com/videos/beta.mp4",
            video_type="mp4",
            is_public=False,
        )

    def test_tenant_portal_shows_only_owned_videos(self):
        self.client.login(username="tenant-alpha", password="password123")
        response = self.client.get(reverse("stream:tenant-portal"))
        self.assertContains(response, self.video_one.title)
        self.assertNotContains(response, self.video_two.title)

    def test_expired_tenant_redirects_to_subscription_view(self):
        expired_user = get_user_model().objects.create_user(
            username="tenant-expired",
            email="expired@example.com",
            password="password123",
        )
        expired_tenant = Tenant.objects.create(
            user=expired_user,
            slug="tenant-expired",
            access_end_date=timezone.now() - timedelta(days=1),
        )
        self.client.login(username="tenant-expired", password="password123")
        response = self.client.get(reverse("stream:tenant-portal"))
        self.assertRedirects(response, reverse("stream:subscription-expired"))

    def test_get_tenant_from_slug_blocks_expired(self):
        slug = self.tenant_one.slug
        self.tenant_one.access_end_date = timezone.now() - timedelta(days=1)
        self.tenant_one.save()
        with self.assertRaises(Http404):
            get_tenant_from_slug(slug)

    def test_tenant_portal_exposes_mininovela_videos(self):
        self.client.login(username="tenant-alpha", password="password123")
        Video.objects.create(
            tenant=self.tenant_one,
            title="Novela Extra",
            slug="novela-extra",
            source_url="https://cdn.example.com/videos/novela.mp4",
            video_type="mp4",
            category=Video.CATEGORY_MININOVELA,
            is_public=True,
        )
        response = self.client.get(reverse("stream:tenant-portal"))
        self.assertEqual(len(response.context["mininovela_videos"]), 1)
