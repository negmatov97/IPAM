"""Hudud bo'yicha cheklash: foydalanuvchi faqat o'ziga biriktirilgan viloyatlar
ma'lumotlarini ko'radi, qo'shadi va o'zgartiradi.

Superadmin va "Barcha hududlar" belgilangan foydalanuvchilar cheklanmaydi.
Profili yo'q yoki hech qanday viloyat biriktirilmagan foydalanuvchi hech narsani ko'rmaydi.
"""

from django import forms
from django.db.models import Q, QuerySet

from .models import Branch, Device, District, IPAddress, Payment, Region, Subnet, Tariff, VLANLease

# Modeldan viloyatgacha yo'l
REGION_PATHS = {
    Region: "pk",
    District: "region",
    Branch: "district__region",
    Device: "branch__district__region",
    IPAddress: "branch__district__region",
    Subnet: "branch__district__region",
    VLANLease: "region",
    Payment: "lease__region",
    Tariff: "region",
}

# Bu modellarda hudud bo'sh bo'lishi "umumiy" degani: ko'rish mumkin, o'zgartirish — yo'q
SHARED_WHEN_EMPTY = {
    Subnet: "branch__isnull",
    Tariff: "region__isnull",
}


def allowed_region_ids(user):
    """None — cheklov yo'q; aks holda ruxsat etilgan viloyat ID'lari to'plami."""
    if not user.is_authenticated:
        return set()
    if user.is_superuser:
        return None
    cache = getattr(user, "_ipam_region_ids", "unset")
    if cache != "unset":
        return cache
    profile = getattr(user, "profile", None)
    if profile is None:
        ids = set()
    elif profile.all_regions:
        ids = None
    else:
        ids = set(profile.regions.values_list("pk", flat=True))
    user._ipam_region_ids = ids
    return ids


def is_restricted(user):
    return allowed_region_ids(user) is not None


def scope_queryset(qs, user, for_write=False):
    """QuerySet'ni foydalanuvchi hududlari bilan cheklash.

    for_write=True bo'lsa, "umumiy" yozuvlar (masalan, filialga biriktirilmagan subnet)
    chiqarib tashlanadi — ularni faqat cheklanmagan foydalanuvchilar o'zgartiradi."""
    if not isinstance(qs, QuerySet):
        return qs
    ids = allowed_region_ids(user)
    if ids is None:
        return qs
    path = REGION_PATHS.get(qs.model)
    if path is None:
        return qs
    condition = Q(**{f"{path}__in": ids})
    shared = SHARED_WHEN_EMPTY.get(qs.model)
    if shared and not for_write:
        condition |= Q(**{shared: True})
    return qs.filter(condition)


def can_access_region(user, region_id):
    ids = allowed_region_ids(user)
    return ids is None or region_id in ids


def restrict_form(form, user):
    """Formadagi viloyat/tuman/filial/qurilma tanlovlarini foydalanuvchi hududlari bilan cheklash.

    Ma'lumot kiritish formalarida (ModelForm) cheklangan foydalanuvchi filial/viloyatni
    bo'sh qoldira olmaydi — aks holda yozuv uning hududidan "chiqib ketadi"."""
    ids = allowed_region_ids(user)
    if ids is None:
        return form
    fields = form.fields
    lookups = {
        "region": "pk__in",
        "district": "region__in",
        "branch": "district__region__in",
        "device": "branch__district__region__in",
    }
    for name, lookup in lookups.items():
        field = fields.get(name)
        if field is None or not hasattr(field, "queryset"):
            continue
        field.queryset = field.queryset.filter(**{lookup: ids})
    if isinstance(form, forms.ModelForm):
        model_fields = {f.name for f in form._meta.model._meta.get_fields()}
        for name in ("branch", "region"):
            if name in fields and name in model_fields:
                fields[name].required = True
    return form
