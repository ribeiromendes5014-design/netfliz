import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from stream.models import Tenant, Video


class Command(BaseCommand):
    help = "Cria um novo tenant com usuário, assinatura e registros iniciais."

    def add_arguments(self, parser):
        parser.add_argument("business", help="Nome do negócio / tenant.")
        parser.add_argument("--email", required=True, help="E-mail do usuário do tenant.")
        parser.add_argument("--password", required=True, help="Senha inicial do usuário.")
        parser.add_argument(
            "--duration",
            type=int,
            default=30,
            help="Duração da assinatura em dias.",
        )
        parser.add_argument(
            "--metadata",
            default="{}",
            help="JSON com metadados adicionais para o tenant.",
        )
        parser.add_argument(
            "--sample-video-title",
            help="Título de um vídeo exemplo cadastrado automaticamente.",
        )
        parser.add_argument(
            "--sample-video-url",
            help="URL pública (mp4/m3u8) do vídeo de exemplo.",
        )
        parser.add_argument(
            "--sample-video-type",
            choices=[choice[0] for choice in Video.VIDEO_TYPES],
            default="mp4",
            help="Formato do vídeo de exemplo.",
        )
        parser.add_argument(
            "--sample-video-cover",
            help="URL da imagem de capa do vídeo de exemplo.",
        )

    def handle(self, *args, **options):
        business = options["business"]
        email = options["email"]
        password = options["password"]
        duration = options["duration"]
        metadata_raw = options["metadata"]
        metadata = {}
        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError:
            self.stderr.write("Metadata inválido. Use um JSON válido.")
            return

        username = slugify(business) or f"user-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=email,
            defaults={"username": username, "is_active": True},
        )
        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(f"Usuário {user.email} criado.")
        else:
            user.username = username
            user.set_password(password)
            user.save(update_fields=["username", "password"])
            self.stdout.write(f"Usuário {user.email} existente atualizado.")

        tenant_slug = slugify(business)
        if not tenant_slug:
            tenant_slug = username

        tenant = Tenant(
            user=user,
            slug=tenant_slug,
            access_end_date=timezone.now() + timedelta(days=duration),
            metadata=metadata,
        )
        tenant.save()
        self.stdout.write(f"Tenant {tenant.slug} criado para {user.email}.")

        title = options.get("sample_video_title")
        url = options.get("sample_video_url")
        if title and url:
            cover = options.get("sample_video_cover") or ""
            video = Video.objects.create(
                tenant=tenant,
                title=title,
                slug=slugify(title),
                source_url=url,
                video_type=options["sample_video_type"],
                cover_url=cover,
                is_public=True,
            )
            self.stdout.write(f"Vídeo exemplo '{video.title}' cadastrado.")
