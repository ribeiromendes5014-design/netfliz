import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from urllib.parse import urlsplit, urlunsplit, quote, urlencode

from .models import Tenant, Video

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

    rotate_180 = forms.BooleanField(
        required=False,
        label="Rotacionar vídeo",
        help_text="Ative para girar o vídeo em 180° durante a reprodução.",
    )

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)

    class Meta:
        model = Video
        fields = [
            "title",
            "slug",
            "description",
            "source_url",
            "video_type",
            "cover_url",
            "blocked_tenants",
            "rotate_180",
        ]
        labels = {
            "title": "Título",
            "slug": "Identificador",
            "description": "Descrição",
            "source_url": "URL do vídeo",
            "video_type": "Formato",
            "cover_url": "URL da capa",
        }
        help_texts = {
            "title": "Nome exibido para os espectadores.",
            "slug": "Identificador único, ex: cat-2025.",
            "description": "Frase resumida que acompanha o vídeo.",
            "source_url": "Link direto para mp4/m3u8 ou iframe embed.",
            "cover_url": "Imagem usada como pôster.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

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
