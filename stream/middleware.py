from django.shortcuts import redirect


class SubscriptionCheckMiddleware:
    allowed_paths = {"/login/", "/logout/", "/support/", "/subscription-expired/"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_block(request):
            return redirect("stream:subscription-expired")
        return self.get_response(request)

    def _should_block(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        tenant = getattr(user, "tenant_profile", None)
        if tenant is None or tenant.is_subscription_active:
            return False
        if request.path_info in self.allowed_paths:
            return False
        return True
