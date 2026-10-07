from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from .models import (
    VLAN, AuditLog, Branch, Device, District, IPAddress, Payment, Region, Subnet, Tariff, VLANLease, VLANType,
)

DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ChainedSelect(forms.Select):
    """Variantlari boshqa select qiymatiga qarab filtrlanadigan select.

    Har bir variantga `data-parent` (masalan, tumanning viloyat ID'si) yoziladi,
    filtrlashni esa static/ipam/app.js bajaradi.
    """

    def __init__(self, parent_field, parent_attr, attrs=None):
        attrs = {**(attrs or {}), "data-chain-parent": f"id_{parent_field}"}
        super().__init__(attrs)
        self.parent_attr = parent_attr

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            # parent_attr nuqtali yo'l bo'lishi mumkin: "district.region_id"
            parent_id = instance
            for attr in self.parent_attr.split("."):
                parent_id = getattr(parent_id, attr) if parent_id is not None else None
            if parent_id is not None:
                option["attrs"]["data-parent"] = str(parent_id)
        return option


class LocationFieldsForm(forms.ModelForm):
    """Viloyat va tuman yordamchi maydonlari — filialni tez topish uchun.

    Bu maydonlar bazaga saqlanmaydi, faqat ro'yxatlarni filtrlaydi.
    """

    region = forms.ModelChoiceField(Region.objects.all(), required=False, label="Viloyat")
    district = forms.ModelChoiceField(
        District.objects.all(),
        required=False,
        label="Tuman",
        widget=ChainedSelect("region", "region_id"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        branch = getattr(self.instance, "branch", None) if self.instance.pk else None
        if branch is None and self.initial.get("branch"):
            branch = Branch.objects.filter(pk=self.initial["branch"]).first()
        if branch:
            self.initial.setdefault("district", branch.district_id)
            self.initial.setdefault("region", branch.district.region_id)


class VLANForm(forms.ModelForm):
    class Meta:
        model = VLAN
        fields = ["vid", "name", "vlan_type", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class RegionForm(forms.ModelForm):
    class Meta:
        model = Region
        fields = ["name", "code"]


class DistrictForm(forms.ModelForm):
    class Meta:
        model = District
        fields = ["region", "name"]


class BranchForm(forms.ModelForm):
    region = forms.ModelChoiceField(Region.objects.all(), required=False, label="Viloyat")
    field_order = ["region", "district", "name", "code", "address", "phone", "contact_person", "description"]

    class Meta:
        model = Branch
        fields = ["district", "name", "code", "address", "phone", "contact_person", "description"]
        widgets = {
            "district": ChainedSelect("region", "region_id"),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        district = self.instance.district if self.instance.pk else None
        if district is None and self.initial.get("district"):
            district = District.objects.filter(pk=self.initial["district"]).first()
        if district:
            self.initial.setdefault("region", district.region_id)


class DeviceForm(LocationFieldsForm):
    field_order = ["name", "device_type", "region", "district", "branch"]

    class Meta:
        model = Device
        fields = [
            "name", "device_type", "branch", "vendor", "model",
            "serial_number", "inventory_number", "location", "description",
        ]
        widgets = {
            "branch": ChainedSelect("district", "district_id"),
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class SubnetForm(LocationFieldsForm):
    field_order = ["network", "name", "vlan", "gateway", "region", "district", "branch"]

    class Meta:
        model = Subnet
        fields = ["network", "name", "vlan", "gateway", "branch", "description"]
        widgets = {
            "network": forms.TextInput(attrs={"placeholder": "192.168.1.0/24"}),
            "branch": ChainedSelect("district", "district_id"),
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class IPAddressForm(LocationFieldsForm):
    field_order = ["address", "status", "region", "district", "branch", "device"]

    class Meta:
        model = IPAddress
        fields = ["address", "status", "branch", "device", "hostname", "mac_address", "description"]
        widgets = {
            "branch": ChainedSelect("district", "district_id"),
            "device": ChainedSelect("branch", "branch_id"),
        }
        help_texts = {
            "branch": "Bo'sh qolsa, qurilma yoki subnetning filiali olinadi.",
            "hostname": "Bo'sh qolsa, qurilma nomi yoziladi.",
        }


# ---------- Ro'yxatlar uchun filtrlar ----------

class LocationFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Qidirish")
    region = forms.ModelChoiceField(Region.objects.all(), required=False, label="Viloyat", empty_label="Barcha viloyatlar")
    district = forms.ModelChoiceField(
        District.objects.all(), required=False, label="Tuman", empty_label="Barcha tumanlar",
        widget=ChainedSelect("region", "region_id"),
    )
    branch = forms.ModelChoiceField(
        Branch.objects.select_related("district"), required=False, label="Filial", empty_label="Barcha filiallar",
        widget=ChainedSelect("district", "district_id"),
    )

    def filter_location(self, qs, path="branch"):
        """Hudud bo'yicha filtrlash. `path` — modeldan filialgacha yo'l
        (filiallarning o'zi uchun bo'sh satr)."""
        data = self.cleaned_data
        lookup = f"{path}__" if path else ""
        if data.get("branch"):
            return qs.filter(**{path or "pk": data["branch"]})
        if data.get("district"):
            return qs.filter(**{f"{lookup}district": data["district"]})
        if data.get("region"):
            return qs.filter(**{f"{lookup}district__region": data["region"]})
        return qs


class DeviceFilterForm(LocationFilterForm):
    device_type = forms.ChoiceField(
        choices=[("", "Barcha turlar")] + Device.TYPE_CHOICES, required=False, label="Turi"
    )


class IPFilterForm(DeviceFilterForm):
    status = forms.ChoiceField(
        choices=[("", "Barcha holatlar")] + IPAddress.STATUS_CHOICES, required=False, label="Holati"
    )


# ---------- Moliya ----------

class VLANTypeForm(forms.ModelForm):
    class Meta:
        model = VLANType
        fields = ["name", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class TariffForm(forms.ModelForm):
    class Meta:
        model = Tariff
        fields = [
            "vlan_type", "region", "unit", "base_price", "included_km", "step_km", "step_price",
            "yearly_discount", "valid_from", "note",
        ]
        widgets = {"valid_from": DATE_WIDGET}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vlan_type"].empty_label = "Barcha turlar"
        self.fields["region"].empty_label = "Barcha hududlar"


class LeaseForm(forms.ModelForm):
    class Meta:
        model = VLANLease
        fields = [
            "vlan", "tenant", "contract_number", "region", "branch", "bandwidth_mbps", "distance_km",
            "billing_period", "start_date", "end_date", "custom_price", "note",
        ]
        widgets = {
            "branch": ChainedSelect("region", "district.region_id"),
            "start_date": DATE_WIDGET,
            "end_date": DATE_WIDGET,
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, show_prices=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.select_related("district")
        self.fields["vlan"].queryset = VLAN.objects.select_related("vlan_type")
        if not show_prices:
            # Narxlarni ko'rish huquqi bo'lmasa, maxsus narxni ham o'zgartira olmaydi
            del self.fields["custom_price"]


class PriceCalculatorForm(forms.Form):
    vlan_type = forms.ModelChoiceField(VLANType.objects.all(), required=False, label="VLAN turi", empty_label="Turi ko'rsatilmagan")
    region = forms.ModelChoiceField(Region.objects.all(), label="Viloyat")
    bandwidth_mbps = forms.DecimalField(label="Tezlik (Mbit/s)", min_value=Decimal("0.01"), initial=10)
    distance_km = forms.DecimalField(label="Masofa (km)", min_value=0, initial=0)
    on_date = forms.DateField(label="Sana", widget=DATE_WIDGET, required=False)


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["date", "amount", "note"]
        widgets = {
            "date": DATE_WIDGET,
            "amount": forms.NumberInput(attrs={"placeholder": "Summa (so'm)", "min": "0", "step": "0.01"}),
        }


class LeaseFilterForm(forms.Form):
    STATUS_CHOICES = [("", "Barchasi"), ("active", "Amaldagi"), ("ended", "Tugagan"), ("debt", "Qarzdorlar")]

    q = forms.CharField(required=False, label="Qidirish")
    region = forms.ModelChoiceField(Region.objects.all(), required=False, label="Viloyat", empty_label="Barcha viloyatlar")
    vlan = forms.ModelChoiceField(VLAN.objects.all(), required=False, label="VLAN", empty_label="Barcha VLAN'lar")
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False, label="Holati")


# ---------- Foydalanuvchilar va harakatlar qaydi ----------

class UserAccessForm(forms.Form):
    groups = forms.ModelMultipleChoiceField(
        Group.objects.order_by("name"), required=False, label="Rollar", widget=forms.CheckboxSelectMultiple,
    )
    all_regions = forms.BooleanField(
        required=False, label="Barcha hududlar",
        help_text="Belgilansa, viloyatlar ro'yxatidan qat'i nazar barcha ma'lumotlar ochiq bo'ladi.",
    )
    regions = forms.ModelMultipleChoiceField(
        Region.objects.all(), required=False, label="Biriktirilgan viloyatlar", widget=forms.CheckboxSelectMultiple,
        help_text="Foydalanuvchi faqat shu viloyatlar IP manzillari, filiallari va qurilmalarini ko'radi va o'zgartiradi.",
    )
    can_view_prices = forms.BooleanField(required=False, label="Narxlarni ko'rish (shaxsan)")
    is_active = forms.BooleanField(required=False, label="Faol (tizimga kira oladi)")


class AuditFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Qidirish")
    user = forms.ModelChoiceField(
        get_user_model().objects.order_by("username"), required=False, label="Foydalanuvchi",
        empty_label="Barcha foydalanuvchilar",
    )
    action = forms.ChoiceField(choices=[("", "Barcha harakatlar")] + AuditLog.ACTION_CHOICES, required=False, label="Harakat")
    model_name = forms.ChoiceField(required=False, label="Bo'lim")
    date_from = forms.DateField(required=False, label="Sanadan", widget=DATE_WIDGET)
    date_to = forms.DateField(required=False, label="Sanagacha", widget=DATE_WIDGET)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        names = AuditLog.objects.exclude(model_name="").values_list("model_name", flat=True).distinct().order_by("model_name")
        self.fields["model_name"].choices = [("", "Barcha bo'limlar")] + [(n, n) for n in names]
