from django.apps import AppConfig


class StreamConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stream'

    def ready(self):
        from django.test.client import ContextList, store_rendered_templates as original_store
        import django.test.client as test_client
        from django.template.context import BaseContext

        if getattr(BaseContext, "_copy_patch_applied", False):
            return

        def _patched_copy(self):
            duplicate = object.__new__(type(self))
            duplicate.__dict__.update(getattr(self, "__dict__", {}))
            duplicate.dicts = [d.copy() for d in self.dicts]
            return duplicate

        BaseContext.__copy__ = _patched_copy
        BaseContext._copy_patch_applied = True

        def _safe_store_rendered_templates(store, signal, sender, template, context, **kwargs):
            try:
                return original_store(store, signal, sender, template, context, **kwargs)
            except Exception:
                store.setdefault("templates", []).append(template)
                if "context" not in store:
                    store["context"] = ContextList()
                store["context"].append(context)

        test_client.store_rendered_templates = _safe_store_rendered_templates
