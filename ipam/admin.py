from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import (
    VLAN, AuditLog, Branch, Device, District, IPAddress, Payment, Region, Subnet, Tariff, UserProfile, VLANLease,
    VLANType,
)


@admin.register(Tariff)
class TariffAdmin(admin.ModelAdmin):
    list_display = ["__str__", "unit", "base_price", "included_km", "step_km", "step_price", "valid_from"]
    list_filter = ["vlan_type", "region"]


@admin.register(VLANType)
class VLANTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(VLANLease)
class VLANLeaseAdmin(admin.ModelAdmin):
    list_display = ["vlan", "tenant", "contract_number", "region", "billing_period", "start_date", "end_date"]
    list_filter = ["region", "billing_period", "vlan"]
    search_fields = ["tenant", "contract_number"]
    inlines = [PaymentInline]


class DistrictInline(admin.TabularInline):
    model = District
    extra = 0


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ["name", "code"]
    search_fields = ["name"]
    inlines = [DistrictInline]


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ["name", "region"]
    list_filter = ["region"]
    search_fields = ["name"]


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "district", "region", "phone", "contact_person"]
    list_filter = ["district__region"]
    search_fields = ["name", "code", "address", "contact_person"]
    autocomplete_fields = ["district"]


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "device_type", "branch", "vendor", "model", "serial_number", "inventory_number"]
    list_filter = ["device_type", "branch__district__region"]
    search_fields = ["name", "model", "serial_number", "inventory_number"]
    autocomplete_fields = ["branch"]


@admin.register(VLAN)
class VLANAdmin(admin.ModelAdmin):
    list_display = ["vid", "name", "vlan_type", "description"]
    search_fields = ["name", "description"]


class IPAddressInline(admin.TabularInline):
    model = IPAddress
    extra = 0
    autocomplete_fields = ["branch", "device"]


@admin.register(Subnet)
class SubnetAdmin(admin.ModelAdmin):
    list_display = ["network", "name", "vlan", "branch", "gateway", "utilization"]
    list_filter = ["vlan", "branch__district__region"]
    search_fields = ["network", "name", "description"]
    autocomplete_fields = ["branch"]
    inlines = [IPAddressInline]


@admin.register(IPAddress)
class IPAddressAdmin(admin.ModelAdmin):
    list_display = ["address", "subnet", "status", "branch", "device", "hostname", "mac_address", "updated_at"]
    list_filter = ["status", "branch__district__region", "subnet"]
    search_fields = ["address", "hostname", "mac_address", "description"]
    autocomplete_fields = ["branch", "device"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Qaydlar faqat o'qish uchun — ularni o'zgartirib yoki o'chirib bo'lmaydi."""

    list_display = ["timestamp", "username", "action", "model_name", "object_repr", "ip_address"]
    list_filter = ["action", "model_name"]
    search_fields = ["username", "object_repr", "ip_address"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    filter_horizontal = ["regions"]
    readonly_fields = ["last_seen", "last_ip", "is_logged_in"]
    verbose_name_plural = "Hududlar va faollik"


admin.site.unregister(User)


@admin.register(User)
class UserWithProfileAdmin(UserAdmin):
    inlines = [UserProfileInline]
