"""Foydalanuvchi harakatlari qaydlari va onlayn holat.

- Middleware har bir so'rovda joriy foydalanuvchini eslab qoladi va uning oxirgi
  faollik vaqtini yangilaydi (bazaga daqiqada bir martadan ko'p yozilmaydi).
- Signal'lar IPAM modellaridagi har bir qo'shish/o'zgartirish/o'chirishni eski va
  yangi qiymatlari bilan, shuningdek tizimga kirish/chiqishni yozib boradi.
"""

import contextvars
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import (
    VLAN, AuditLog, Branch, Device, District, IPAddress, Payment, Region, Subnet, Tariff, UserProfile,
    VLANLease, VLANType,
)

_current_request = contextvars.ContextVar("ipam_current_request", default=None)

AUDITED_MODELS = (Region, District, Branch, Device, Subnet, IPAddress, VLAN, VLANType, Tariff, VLANLease, Payment)
USER_IGNORED_FIELDS = {"last_login", "password"}
LAST_SEEN_THROTTLE = timedelta(seconds=60)


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _title(text):
    """Faqat birinchi harfni katta qilish ("IP manzil" -> "IP manzil", "subnet" -> "Subnet")."""
    text = str(text)
    return text[:1].upper() + text[1:]


def log_event(action, obj=None, changes=None, user=None, request=None, object_repr=None, model_name=None):
    request = request or _current_request.get()
    if user is None and request is not None and getattr(request, "user", None) is not None:
        user = request.user if request.user.is_authenticated else None
    return AuditLog.objects.create(
        user=user,
        username=user.get_username() if user else "",
        action=action,
        model_name=model_name or (_title(obj._meta.verbose_name) if obj is not None else ""),
        object_id=str(obj.pk) if obj is not None and obj.pk is not None else "",
        object_repr=(object_repr or (str(obj) if obj is not None else ""))[:255],
        changes=changes or {},
        ip_address=client_ip(request),
    )


class AuditMiddleware:
    """AuthenticationMiddleware'dan keyin ulanadi."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_request.set(request)
        try:
            self.touch(request)
            return self.get_response(request)
        finally:
            _current_request.reset(token)

    @staticmethod
    def touch(request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return
        now = timezone.now()
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if profile.last_seen and now - profile.last_seen < LAST_SEEN_THROTTLE and profile.is_logged_in:
            return
        UserProfile.objects.filter(pk=profile.pk).update(last_seen=now, last_ip=client_ip(request), is_logged_in=True)


# ---------- O'zgarishlarni aniqlash ----------

def _display(instance, field):
    value = getattr(instance, field.name, None)
    if value is None or value == "":
        return ""
    if field.choices:
        return str(getattr(instance, f"get_{field.name}_display")())
    if isinstance(value, bool):
        return "Ha" if value else "Yo'q"
    return str(value)


def _snapshot(instance, ignored=()):
    data = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key or field.name in ignored or getattr(field, "auto_now", False):
            continue
        data[field.name] = (str(field.verbose_name), _display(instance, field))
    return data


def _diff(old, new):
    changes = {}
    for name, (label, new_value) in new.items():
        old_value = old.get(name, (label, ""))[1]
        if old_value != new_value:
            changes[label] = [old_value, new_value]
    return changes


def _audited(sender):
    return sender in AUDITED_MODELS or sender is get_user_model()


@receiver(pre_save)
def _remember_old(sender, instance, **kwargs):
    if not _audited(sender) or instance.pk is None or kwargs.get("raw"):
        return
    ignored = USER_IGNORED_FIELDS if sender is get_user_model() else ()
    old = sender._default_manager.filter(pk=instance.pk).first()
    instance._audit_old = _snapshot(old, ignored) if old else None
    if sender is get_user_model() and old is not None:
        instance._audit_password_changed = old.password != instance.password


@receiver(post_save)
def _log_save(sender, instance, created, **kwargs):
    if not _audited(sender) or kwargs.get("raw"):
        return
    ignored = USER_IGNORED_FIELDS if sender is get_user_model() else ()
    new = _snapshot(instance, ignored)
    old = getattr(instance, "_audit_old", None)
    if created or old is None:
        changes = {label: ["", value] for label, value in new.values() if value != ""}
        log_event(AuditLog.ACTION_CREATE, instance, changes)
        return
    changes = _diff(old, new)
    if getattr(instance, "_audit_password_changed", False):
        changes["Parol"] = ["", "o'zgartirildi"]
    if changes:  # masalan, faqat last_login yangilansa — qayd yozilmaydi
        log_event(AuditLog.ACTION_UPDATE, instance, changes)


@receiver(post_delete)
def _log_delete(sender, instance, **kwargs):
    if not _audited(sender):
        return
    ignored = USER_IGNORED_FIELDS if sender is get_user_model() else ()
    changes = {label: [value, ""] for label, value in _snapshot(instance, ignored).values() if value != ""}
    log_event(AuditLog.ACTION_DELETE, instance, changes)


# ---------- Kirish / chiqish ----------

@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    UserProfile.objects.get_or_create(user=user)
    UserProfile.objects.filter(user=user).update(last_seen=timezone.now(), last_ip=client_ip(request), is_logged_in=True)
    log_event(AuditLog.ACTION_LOGIN, user=user, request=request, object_repr=user.get_username(), model_name="Tizim")


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    if user is None:
        return
    UserProfile.objects.filter(user=user).update(is_logged_in=False)
    log_event(AuditLog.ACTION_LOGOUT, user=user, request=request, object_repr=user.get_username(), model_name="Tizim")


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    username = str(credentials.get("username", ""))[:150]
    AuditLog.objects.create(
        action=AuditLog.ACTION_LOGIN_FAILED, username=username, model_name="Tizim",
        object_repr=username, ip_address=client_ip(request),
    )
