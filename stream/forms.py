import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from urllib.parse import urlsplit, urlunsplit, quote, urlencode

from .models import Series, Tenant, Video

IFRAME_SRC_PATTERN = re.compile(r'src\s*=\s*["\\\']([^"\\\']+)["\\\']', re.IGNORECASE)


def _extract_iframe_src(value):
    match = IFRAME_SRC_PATTERN.search(value or "")
    return match.group(1) if match else None


class VideoForm(forms.ModelForm):
    source_url = forms.CharField(
        max_length=2048,
        label="URL do vídeo",
        widget=forms.TextInput(
            attrs={"placeholder": "https://.../playlist.m3u8 ou <iframe src=\"...\"></iframe>"}
        ),
    )
    blocked_tenants = forms.ModelMultipleChoiceField(
        queryset=Tenant.objects.filter(is_active=True),
        required=False,
        label="Ocultar para",
        help_text="Escolha as contas que não devem ver este vídeo.",
        widget=forms.CheckboxSelectMultiple,
    )

    series = forms.ModelChoiceField(
        queryset=Series.objects.none(),
        required=False,
        label="Série",
        help_text="Associe este vídeo a uma série existente se for um episódio.",
    )

    season_number = forms.IntegerField(
        required=False,
        min_value=1,
        label="Temporada",
        help_text="Número da temporada (use para organizar episódios).",
    )

    episode_number = forms.IntegerField(
        required=False,
        min_value=1,
        label="Episódio",
        help_text="Número do episódio dentro da temporada.",
    )

    category = forms.ChoiceField(
        choices=Video.CATEGORY_CHOICES,
        label="Categoria",
        initial=Video.CATEGORY_MOVIE,
        help_text="Escolha TV, Filmes ou Séries.",
        required=True,
    )

    genre = forms.ChoiceField(
        choices=Video.VIDEO_GENRE_CHOICES,
        required=False,
        label="Gênero",
        help_text="Especifique o gênero principal (filmes e séries).",
    )

    rotate_180 = forms.BooleanField(
        required=False,
        label="Rotacionar vídeo",
        help_text="Ative para girar o vídeo em 180° durante a reprodução.",
    )

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)
        if self.owner:
            self.fields["series"].queryset = Series.objects.filter(tenant=self.owner, is_active=True)

    class Meta:
        model = Video
        fields = [
            "title",
            "cover_url",
            "source_url",
            "video_type",
            "category",
            "genre",
            "description",
            "series",
            "season_number",
            "episode_number",
            "slug",
            "blocked_tenants",
            "rotate_180",
        ]
        labels = {
            "title": "Título",
            "slug": "Identificador",
            "description": "Descrição",
            "series": "Série",
            "season_number": "Temporada",
            "episode_number": "Episódio",
            "source_url": "URL do vídeo",
            "video_type": "Formato",
            "cover_url": "URL da capa",
        }
        help_texts = {
            "title": "Nome exibido para os espectadores.",
            "slug": "Identificador único, ex: cat-2025.",
            "description": "Frase resumida que acompanha o vídeo.",
            "series": "Selecione a série que este episódio pertence.",
            "category": "Selecione como este conteúdo deve ser exibido no catálogo.",
            "season_number": "Número da temporada (opcional).",
            "episode_number": "Número do episódio (opcional).",
            "source_url": "Link direto para mp4/m3u8 ou iframe embed.",
            "cover_url": "Imagem usada como pôster.",
            "genre": "Se a categoria for filme ou série, escolha um gênero para organizar o catálogo.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("series"):
            cleaned["category"] = Video.CATEGORY_SERIES
        return cleaned

    def clean_slug(self):
        slug = self.cleaned_data.get("slug") or ""
        if self.owner and slug:
            exists = Video.objects.filter(tenant=self.owner, slug=slug)
            if self.instance.pk:
                exists = exists.exclude(pk=self.instance.pk)
            if exists.exists():
                raise ValidationError(
                    "Já existe um vídeo com esse identificador para o proprietário atual."
                )
        return slug

    def clean_source_url(self):
        source_url = (self.cleaned_data.get("source_url") or "").strip()
        iframe_src = _extract_iframe_src(source_url)
        if iframe_src:
            source_url = iframe_src.strip()
        if "#" in source_url:
            parsed = urlsplit(source_url)
            fragment = parsed.fragment
            encoded_fragment = quote(fragment, safe="")
            source_url = urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, parsed.query, encoded_fragment)
            )
        return source_url


class SeriesForm(forms.ModelForm):
    class Meta:
        model = Series
        fields = ["title", "slug", "description", "cover_url", "is_active"]
        labels = {
            "title": "Título da série",
            "slug": "Identificador da série",
            "description": "Breve descrição",
            "cover_url": "URL da capa",
            "is_active": "Disponível",
        }
        help_texts = {
            "cover_url": "Coloque uma capa representativa para a série.",
            "is_active": "Desative se a série não deve aparecer no catálogo.",
        }


class PortalLoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="",
        widget=forms.EmailInput(attrs={"placeholder": "E-mail", "class": "login-input"}),
    )
    password = forms.CharField(
        label="",
        widget=forms.PasswordInput(attrs={"placeholder": "Senha", "class": "login-input"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = ""
        self.fields["password"].label = ""
