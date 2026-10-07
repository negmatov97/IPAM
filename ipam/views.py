import ipaddress
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import PermissionDenied
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView, DeleteView, DetailView, FormView, ListView, TemplateView, UpdateView,
)

from .audit import log_event
from .exports import EXPORT_FORMATS, ExportMixin, Report, export_response
from .scoping import allowed_region_ids, can_access_region, is_restricted, restrict_form, scope_queryset
from .formatting import fmt_date, money, num
from .forms import (
    AuditFilterForm, BranchForm, DeviceFilterForm, DeviceForm, DistrictForm, IPAddressForm, IPFilterForm,
    LeaseFilterForm, LeaseForm, LocationFilterForm, PaymentForm, PriceCalculatorForm, RegionForm, SubnetForm,
    TariffForm, UserAccessForm, VLANForm, VLANTypeForm,
)
from .models import (
    ONLINE_WINDOW, VLAN, AuditLog, Branch, Device, District, IPAddress, Payment, Region, Subnet, Tariff, UserProfile,
    VLANLease, VLANType,
)

# /24 dan katta bo'lmagan subnetlar uchun barcha manzillar to'r ko'rinishida chiqariladi
GRID_MAX_SIZE = 256

IP_RELATED = ("subnet", "branch__district__region", "device")


def sort_by_ip(addresses):
    return sorted(addresses, key=lambda ip: ipaddress.ip_address(ip.address))


# ---------- Umumiy mixinlar ----------

PRICE_PERM = "ipam.view_prices"


class ScopedMixin:
    """Foydalanuvchi faqat o'z viloyatlari ma'lumotlarini ko'radi (scoping.py).

    get_queryset'ni o'zi yozgan ko'rinishlar natijani self.scope() orqali o'tkazadi."""

    scope_for_write = False

    def scope(self, qs, for_write=None):
        for_write = self.scope_for_write if for_write is None else for_write
        return scope_queryset(qs, self.request.user, for_write=for_write)

    def get_queryset(self):
        return self.scope(super().get_queryset())


class ModelPermissionMixin(ScopedMixin, PermissionRequiredMixin):
    """Rolga asoslangan kirish (RBAC): yaratish/tahrirlash/o'chirish uchun foydalanuvchida
    modelning add_/change_/delete_ ruxsati bo'lishi kerak. Ruxsat yo'q bo'lsa — 403 sahifa,
    tizimga kirmagan bo'lsa — kirish sahifasi. Boshqa viloyat yozuvi — 404."""

    action = None  # "add", "change", "delete"
    extra_permissions = ()
    scope_for_write = True
    unrestricted_only = False  # True — faqat "barcha hududlar" huquqi borlar uchun

    def get_permission_required(self):
        opts = self.model._meta
        return [f"{opts.app_label}.{self.action}_{opts.model_name}", *self.extra_permissions]

    def has_permission(self):
        if self.unrestricted_only and is_restricted(self.request.user):
            return False
        return super().has_permission()


class FormPageMixin(ModelPermissionMixin):
    """Yaratish/tahrirlash sahifalari: umumiy shablon, sarlavha, xabar va
    URL'dagi parametrlardan boshlang'ich qiymatlar (?branch=5 kabi)."""

    template_name = "ipam/form.html"
    title = ""
    success_message = "Saqlandi."

    def get_permission_required(self):
        self.action = "add" if isinstance(self, CreateView) else "change"
        return super().get_permission_required()

    def get_initial(self):
        initial = super().get_initial()
        form_fields = self.get_form_class().base_fields
        initial.update({k: v for k, v in self.request.GET.items() if k in form_fields})
        return initial

    def get_form(self, form_class=None):
        # Viloyat/tuman/filial/qurilma tanlovlari foydalanuvchi hududlari bilan cheklanadi
        return restrict_form(super().get_form(form_class), self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("title", self.title)
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return response


class SafeDeleteView(ModelPermissionMixin, DeleteView):
    """Bog'langan ma'lumoti bor yozuvni o'chirishga urinilsa, xato o'rniga xabar chiqaradi."""

    action = "delete"
    template_name = "ipam/confirm_delete.html"
    protected_message = "Bu yozuvni o'chirib bo'lmaydi: unga bog'langan ma'lumotlar bor."

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, self.protected_message)
            return redirect(self.object.get_absolute_url())
        messages.success(self.request, "O'chirildi.")
        return response


# ---------- Bosh sahifa ----------

class DashboardView(LoginRequiredMixin, ScopedMixin, TemplateView):
    template_name = "ipam/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        s = self.scope
        ctx["counts"] = {
            "regions": s(Region.objects.all()).count(),
            "districts": s(District.objects.all()).count(),
            "branches": s(Branch.objects.all()).count(),
            "devices": s(Device.objects.all()).count(),
            "subnets": s(Subnet.objects.all()).count(),
            "ips": s(IPAddress.objects.all()).count(),
        }
        ctx["regions"] = s(Region.objects.all()).annotate(
            n_districts=Count("districts", distinct=True),
            n_branches=Count("districts__branches", distinct=True),
            n_devices=Count("districts__branches__devices", distinct=True),
            n_ips=Count("districts__branches__ip_addresses", distinct=True),
        ).order_by("-n_ips", "-n_branches", "name")
        if self.request.user.has_perm(PRICE_PERM):
            leases = list(s(VLANLease.objects.select_related("vlan__vlan_type", "region")))
            ctx["finance"] = lease_totals(leases)
            ctx["active_leases"] = sum(1 for x in leases if x.is_active)
            ctx["debtors"] = sorted((x for x in leases if x.balance > 0), key=lambda x: x.balance, reverse=True)[:5]
        if not is_restricted(self.request.user):
            ctx["unassigned_ips"] = IPAddress.objects.filter(branch__isnull=True).count()
        ctx["recent_ips"] = s(IPAddress.objects.select_related(*IP_RELATED)).order_by("-updated_at")[:10]
        ctx["restricted_regions"] = self.restricted_region_names()
        if self.request.user.has_perms(ACCESS_PERMS):
            profiles = UserProfile.objects.select_related("user").filter(
                is_logged_in=True, last_seen__gte=timezone.now() - ONLINE_WINDOW
            ).order_by("user__username")
            ctx["online_users"] = [p.user for p in profiles]
        subnets = list(s(Subnet.objects.all()).annotate(num_ips=Count("addresses")))
        ctx["busy_subnets"] = sorted(
            (s for s in subnets if s.size and s.num_ips * 100 / s.size >= 70),
            key=lambda s: s.num_ips / s.size,
            reverse=True,
        )[:5]
        return ctx

    def restricted_region_names(self):
        ids = allowed_region_ids(self.request.user)
        if ids is None:
            return None
        return list(Region.objects.filter(pk__in=ids).values_list("name", flat=True))


# ---------- Viloyat va tumanlar ----------

class RegionListView(LoginRequiredMixin, ScopedMixin, ListView):
    model = Region
    template_name = "ipam/region_list.html"
    context_object_name = "regions"

    def get_queryset(self):
        return self.scope(Region.objects.all()).annotate(
            n_districts=Count("districts", distinct=True),
            n_branches=Count("districts__branches", distinct=True),
            n_ips=Count("districts__branches__ip_addresses", distinct=True),
        )


class RegionDetailView(LoginRequiredMixin, ScopedMixin, DetailView):
    model = Region
    template_name = "ipam/region_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["districts"] = self.object.districts.prefetch_related("branches").annotate(
            n_ips=Count("branches__ip_addresses", distinct=True),
            n_devices=Count("branches__devices", distinct=True),
        )
        return ctx


class RegionCreateView(FormPageMixin, CreateView):
    model = Region
    form_class = RegionForm
    title = "Yangi viloyat"
    unrestricted_only = True


class RegionUpdateView(FormPageMixin, UpdateView):
    model = Region
    form_class = RegionForm
    title = "Viloyatni tahrirlash"


class RegionDeleteView(SafeDeleteView):
    model = Region
    success_url = reverse_lazy("ipam:region_list")
    unrestricted_only = True
    protected_message = "Viloyatni o'chirib bo'lmaydi: avval uning tumanlarini o'chiring."


class DistrictCreateView(FormPageMixin, CreateView):
    model = District
    form_class = DistrictForm
    title = "Yangi tuman"
    success_message = "Tuman qo'shildi."


class DistrictUpdateView(FormPageMixin, UpdateView):
    model = District
    form_class = DistrictForm
    title = "Tumanni tahrirlash"


class DistrictDeleteView(SafeDeleteView):
    model = District
    protected_message = "Tumanni o'chirib bo'lmaydi: avval uning filiallarini o'chiring."

    def get_success_url(self):
        return self.object.region.get_absolute_url()


# ---------- Filiallar ----------

class BranchListView(LoginRequiredMixin, ScopedMixin, ExportMixin, ListView):
    template_name = "ipam/branch_list.html"
    context_object_name = "branches"
    paginate_by = 50

    def get_queryset(self):
        self.filter_form = restrict_form(LocationFilterForm(self.request.GET or None), self.request.user)
        qs = self.scope(Branch.objects.all()).select_related("district__region").annotate(
            n_devices=Count("devices", distinct=True),
            n_ips=Count("ip_addresses", distinct=True),
            n_subnets=Count("subnets", distinct=True),
        ).order_by(*Branch._meta.ordering)
        if self.filter_form.is_valid():
            qs = self.filter_form.filter_location(qs, path="")
            q = self.filter_form.cleaned_data["q"]
            if q:
                qs = qs.filter(
                    Q(name__icontains=q) | Q(code__icontains=q) | Q(address__icontains=q)
                    | Q(contact_person__icontains=q)
                )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        return ctx

    def build_report(self, branches):
        rows = [
            [
                b.name, b.code, b.district.region.name, b.district.name, b.address,
                b.contact_person, b.phone, b.n_subnets, b.n_devices, b.n_ips,
            ]
            for b in branches
        ]
        return Report(
            title="Filiallar ro'yxati",
            filename="filiallar",
            info=self.filter_info(),
            headers=[
                "Filial", "Kodi", "Viloyat", "Tuman", "Manzil", "Mas'ul shaxs", "Telefon",
                "Subnetlar", "Qurilmalar", "IP manzillar",
            ],
            rows=rows,
            totals=[f"Jami: {len(rows)}", "", "", "", "", "", "",
                    sum(r[7] for r in rows), sum(r[8] for r in rows), sum(r[9] for r in rows)],
        )


class BranchDetailView(LoginRequiredMixin, ScopedMixin, DetailView):
    template_name = "ipam/branch_detail.html"

    def get_queryset(self):
        return self.scope(Branch.objects.select_related("district__region"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        branch = self.object
        ctx["subnets"] = branch.subnets.select_related("vlan").annotate(num_ips=Count("addresses"))
        ctx["devices"] = branch.devices.prefetch_related("ip_addresses")
        ctx["addresses"] = sort_by_ip(branch.ip_addresses.select_related("subnet", "device"))
        return ctx


class BranchCreateView(FormPageMixin, CreateView):
    model = Branch
    form_class = BranchForm
    title = "Yangi filial"
    success_message = "Filial qo'shildi."


class BranchUpdateView(FormPageMixin, UpdateView):
    model = Branch
    form_class = BranchForm
    title = "Filialni tahrirlash"


class BranchDeleteView(SafeDeleteView):
    model = Branch
    success_url = reverse_lazy("ipam:branch_list")
    protected_message = "Filialni o'chirib bo'lmaydi: avval uning qurilmalarini o'chiring yoki boshqa filialga o'tkazing."


# ---------- Qurilmalar ----------

class DeviceListView(LoginRequiredMixin, ScopedMixin, ExportMixin, ListView):
    template_name = "ipam/device_list.html"
    context_object_name = "devices"
    paginate_by = 50

    def get_queryset(self):
        self.filter_form = restrict_form(DeviceFilterForm(self.request.GET or None), self.request.user)
        qs = self.scope(Device.objects.select_related("branch__district__region").prefetch_related("ip_addresses"))
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            qs = self.filter_form.filter_location(qs)
            if data["device_type"]:
                qs = qs.filter(device_type=data["device_type"])
            if data["q"]:
                q = data["q"]
                qs = qs.filter(
                    Q(name__icontains=q) | Q(model__icontains=q) | Q(vendor__icontains=q)
                    | Q(serial_number__icontains=q) | Q(inventory_number__icontains=q)
                    | Q(ip_addresses__address__icontains=q)
                ).distinct()
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        return ctx

    def build_report(self, devices):
        rows = []
        for d in devices:
            b = d.branch
            rows.append([
                d.name, d.get_device_type_display(),
                b.district.region.name if b else "", b.district.name if b else "", b.name if b else "",
                f"{d.vendor} {d.model}".strip(), d.serial_number, d.inventory_number, d.location,
                ", ".join(ip.address for ip in d.ip_addresses.all()),
            ])
        return Report(
            title="Qurilmalar ro'yxati",
            filename="qurilmalar",
            info=self.filter_info(),
            headers=[
                "Nomi", "Turi", "Viloyat", "Tuman", "Filial", "Model", "Seriya raqami",
                "Inventar raqami", "Joylashuvi", "IP manzillar",
            ],
            rows=rows,
            totals=[f"Jami: {len(rows)}"] + [""] * 9,
        )


class DeviceDetailView(LoginRequiredMixin, ScopedMixin, DetailView):
    template_name = "ipam/device_detail.html"

    def get_queryset(self):
        return self.scope(Device.objects.select_related("branch__district__region"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["addresses"] = sort_by_ip(self.object.ip_addresses.select_related("subnet"))
        return ctx


class DeviceCreateView(FormPageMixin, CreateView):
    model = Device
    form_class = DeviceForm
    title = "Yangi qurilma"
    success_message = "Qurilma qo'shildi."


class DeviceUpdateView(FormPageMixin, UpdateView):
    model = Device
    form_class = DeviceForm
    title = "Qurilmani tahrirlash"


class DeviceDeleteView(SafeDeleteView):
    model = Device
    success_url = reverse_lazy("ipam:device_list")


# ---------- Subnetlar ----------

class SubnetListView(LoginRequiredMixin, ScopedMixin, ExportMixin, ListView):
    template_name = "ipam/subnet_list.html"
    context_object_name = "subnets"

    def get_queryset(self):
        self.filter_form = restrict_form(LocationFilterForm(self.request.GET or None), self.request.user)
        qs = self.scope(Subnet.objects.all()).select_related("vlan", "branch__district__region").annotate(
            num_ips=Count("addresses", distinct=True)
        )
        if self.filter_form.is_valid():
            qs = self.filter_form.filter_location(qs)
            q = self.filter_form.cleaned_data["q"]
            if q:
                qs = qs.filter(
                    Q(network__icontains=q) | Q(name__icontains=q)
                    | Q(addresses__address__icontains=q) | Q(addresses__hostname__icontains=q)
                ).distinct()
        # IP tartibida saralash (matn bo'yicha emas)
        return sorted(qs, key=lambda s: (s.ip_network.version, s.ip_network))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        return ctx

    def build_report(self, subnets):
        rows = []
        for s in subnets:
            b = s.branch
            rows.append([
                s.network, s.name, b.district.region.name if b else "", b.name if b else "",
                s.vlan.vid if s.vlan else "", s.gateway or "", f"{s.num_ips} / {s.size}", f"{s.utilization}%",
            ])
        return Report(
            title="Subnetlar ro'yxati",
            filename="subnetlar",
            info=self.filter_info(),
            headers=["Tarmoq", "Nomi", "Viloyat", "Filial", "VLAN", "Shlyuz", "Band / jami", "Bandlik"],
            rows=rows,
            totals=[f"Jami: {len(rows)}"] + [""] * 7,
        )


class SubnetDetailView(LoginRequiredMixin, ScopedMixin, DetailView):
    template_name = "ipam/subnet_detail.html"

    def get_queryset(self):
        return self.scope(Subnet.objects.select_related("vlan", "branch__district__region"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        subnet = self.object
        all_addresses = subnet.addresses.select_related("branch", "device")
        # Umumiy subnetda boshqa viloyat IP'lari faqat "band" deb ko'rsatiladi, tafsilotlarsiz
        visible = {ip.pk for ip in self.scope(all_addresses)}
        addresses = {ip.address: ip for ip in all_addresses}
        ctx["addresses"] = sort_by_ip(ip for ip in addresses.values() if ip.pk in visible)
        ctx["hidden_count"] = len(addresses) - len(visible)
        # Umumiy (filialsiz) subnetni faqat cheklanmagan foydalanuvchi o'zgartiradi
        ctx["can_edit_subnet"] = bool(subnet.branch_id) or not is_restricted(self.request.user)
        ctx["first_free"] = subnet.first_free_ip()

        if subnet.size <= GRID_MAX_SIZE:
            grid = []
            sep = "." if subnet.ip_network.version == 4 else ":"
            for ip in subnet.usable_hosts():
                ip = str(ip)
                cell = {"ip": ip, "label": ip.rsplit(sep, 1)[-1] or "0", "state": "free", "obj": None}
                if ip == subnet.gateway:
                    cell["state"] = "gateway"
                elif ip in addresses:
                    if addresses[ip].pk in visible:
                        cell["state"] = addresses[ip].status
                        cell["obj"] = addresses[ip]
                    else:
                        cell["state"] = "foreign"
                grid.append(cell)
            ctx["grid"] = grid
        return ctx


class SubnetCreateView(FormPageMixin, CreateView):
    model = Subnet
    form_class = SubnetForm
    title = "Yangi subnet"
    success_message = "Subnet qo'shildi."


class SubnetUpdateView(FormPageMixin, UpdateView):
    model = Subnet
    form_class = SubnetForm
    title = "Subnetni tahrirlash"


class SubnetDeleteView(SafeDeleteView):
    model = Subnet
    success_url = reverse_lazy("ipam:subnet_list")


# ---------- IP manzillar ----------

class IPAddressListView(LoginRequiredMixin, ScopedMixin, ExportMixin, ListView):
    template_name = "ipam/ip_list.html"
    context_object_name = "addresses"
    paginate_by = 100

    def get_queryset(self):
        self.filter_form = restrict_form(IPFilterForm(self.request.GET or None), self.request.user)
        qs = self.scope(IPAddress.objects.select_related(*IP_RELATED))
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            qs = self.filter_form.filter_location(qs)
            if data["device_type"]:
                qs = qs.filter(device__device_type=data["device_type"])
            if data["status"]:
                qs = qs.filter(status=data["status"])
            if data["q"]:
                q = data["q"]
                qs = qs.filter(
                    Q(address__icontains=q) | Q(hostname__icontains=q) | Q(mac_address__icontains=q)
                    | Q(description__icontains=q) | Q(device__name__icontains=q)
                )
        return sort_by_ip(qs)

    def build_report(self, addresses):
        return Report(
            title="IP manzillar ro'yxati",
            filename="ip-manzillar",
            info=self.filter_info(),
            headers=[
                "IP manzil", "Subnet", "Holati", "Viloyat", "Tuman", "Filial", "Qurilma",
                "Qurilma turi", "Hostname", "MAC manzil", "Tavsif",
            ],
            rows=[
                [
                    ip.address, ip.subnet.network, ip.get_status_display(),
                    ip.region, ip.district, ip.branch.name if ip.branch else "",
                    ip.device.name if ip.device else "",
                    ip.device.get_device_type_display() if ip.device else "",
                    ip.hostname, ip.mac_address, ip.description,
                ]
                for ip in addresses
            ],
            totals=[f"Jami: {len(addresses)}"] + [""] * 10,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        return ctx


class IPAddressFormMixin(FormPageMixin):
    model = IPAddress
    form_class = IPAddressForm

    def get_subnet(self):
        # Ko'rinadigan subnet: o'z viloyatiniki yoki umumiy (filialsiz) subnet
        return get_object_or_404(self.scope(Subnet.objects.all(), for_write=False), pk=self.kwargs["subnet_pk"])

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # model.clean() subnetni bilishi uchun uni oldindan biriktiramiz
        form.instance.subnet = self.get_subnet()
        return form


class IPAddressCreateView(IPAddressFormMixin, CreateView):
    success_message = "IP manzil qo'shildi."

    def get_initial(self):
        initial = super().get_initial()
        subnet = self.get_subnet()
        initial["address"] = self.request.GET.get("ip") or subnet.first_free_ip()
        if subnet.branch_id:
            initial.setdefault("branch", subnet.branch_id)
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = f"Yangi IP — {self.get_subnet().network}"
        return ctx


class IPAddressUpdateView(IPAddressFormMixin, UpdateView):
    success_message = "IP manzil saqlandi."

    def get_queryset(self):
        return self.scope(IPAddress.objects.filter(subnet_id=self.kwargs["subnet_pk"]))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = f"IP tahrirlash — {self.object.address}"
        return ctx


class IPAddressDeleteView(SafeDeleteView):
    model = IPAddress

    def get_queryset(self):
        return self.scope(IPAddress.objects.filter(subnet_id=self.kwargs["subnet_pk"]))

    def get_success_url(self):
        return reverse("ipam:subnet_detail", args=[self.kwargs["subnet_pk"]])


# ---------- VLAN'lar ----------

class VLANListView(LoginRequiredMixin, ListView):
    template_name = "ipam/vlan_list.html"
    context_object_name = "vlans"

    def get_queryset(self):
        return VLAN.objects.select_related("vlan_type").prefetch_related("subnets", "leases")


class VLANCreateView(FormPageMixin, CreateView):
    model = VLAN
    form_class = VLANForm
    title = "Yangi VLAN"
    success_message = "VLAN qo'shildi."


class VLANUpdateView(FormPageMixin, UpdateView):
    model = VLAN
    form_class = VLANForm
    title = "VLAN tahrirlash"


class VLANDeleteView(SafeDeleteView):
    model = VLAN
    success_url = reverse_lazy("ipam:vlan_list")
    protected_message = "VLAN'ni o'chirib bo'lmaydi: unga bog'langan ijara shartnomalari bor."


# ---------- VLAN turlari ----------

class VLANTypeListView(LoginRequiredMixin, ListView):
    template_name = "ipam/vlantype_list.html"
    context_object_name = "types"

    def get_queryset(self):
        return VLANType.objects.annotate(n_vlans=Count("vlans", distinct=True), n_tariffs=Count("tariffs", distinct=True))


class VLANTypeCreateView(FormPageMixin, CreateView):
    model = VLANType
    form_class = VLANTypeForm
    title = "Yangi VLAN turi"
    success_message = "VLAN turi qo'shildi."


class VLANTypeUpdateView(FormPageMixin, UpdateView):
    model = VLANType
    form_class = VLANTypeForm
    title = "VLAN turini tahrirlash"


class VLANTypeDeleteView(SafeDeleteView):
    model = VLANType
    success_url = reverse_lazy("ipam:vlantype_list")
    protected_message = "Bu turni o'chirib bo'lmaydi: unga VLAN'lar yoki narxlar bog'langan."


# ---------- Moliya: narxlar ----------

class PriceListView(PermissionRequiredMixin, ScopedMixin, TemplateView):
    """Prays-list: viloyat × VLAN turi jadvali, narxlar tarixi va narx kalkulyatori."""

    permission_required = PRICE_PERM
    template_name = "ipam/price_list.html"

    def get_columns(self):
        """Jadval ustunlari: VLAN turlari (+ turi ko'rsatilmagan VLAN'lar bo'lsa, None)."""
        columns = list(VLANType.objects.all())
        if not columns or VLAN.objects.filter(vlan_type__isnull=True).exists():
            columns.append(None)
        return columns

    def get_matrix(self, on_date):
        columns = self.get_columns()
        rows = []
        for region in self.scope(Region.objects.all()):
            cells = []
            for vlan_type in columns:
                tariff = Tariff.find(vlan_type, region, on_date)
                cells.append({"tariff": tariff, "own": tariff is not None and tariff.region_id == region.pk})
            rows.append({"region": region, "cells": cells})
        return columns, rows

    def get(self, request, *args, **kwargs):
        fmt = request.GET.get("export")
        if fmt in EXPORT_FORMATS:
            return export_response(self.build_report(), fmt)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        ctx["columns"], ctx["rows"] = self.get_matrix(today)
        ctx["tariffs"] = self.scope(Tariff.objects.select_related("vlan_type", "region")).order_by(
            "vlan_type__name", "region__name", "-valid_from"
        )
        ctx["today"] = today
        ctx["calc_form"], ctx["calc"] = self.calculate()
        return ctx

    def calculate(self):
        """Kalkulyator: tanlangan tur, viloyat, tezlik va masofa bo'yicha narx."""
        if "region" not in self.request.GET:
            return restrict_form(PriceCalculatorForm(), self.request.user), None
        form = restrict_form(PriceCalculatorForm(self.request.GET), self.request.user)
        if not form.is_valid():
            return form, None
        data = form.cleaned_data
        on_date = data["on_date"] or timezone.localdate()
        tariff = Tariff.find(data["vlan_type"], data["region"], on_date)
        if tariff is None:
            return form, {"tariff": None}
        return form, {"tariff": tariff, "result": tariff.calculate(data["bandwidth_mbps"], data["distance_km"])}

    def build_report(self):
        columns, rows = self.get_matrix(timezone.localdate())
        report_rows = []
        for row in rows:
            for vlan_type, cell in zip(columns, row["cells"]):
                t = cell["tariff"]
                type_name = vlan_type.name if vlan_type else "Turi ko'rsatilmagan"
                if t is None:
                    report_rows.append([row["region"].name, type_name, "Narx belgilanmagan", "", "", "", "", "", ""])
                    continue
                report_rows.append([
                    row["region"].name, type_name, t.get_unit_display(), money(t.base_price),
                    f"{num(t.included_km)} km" if t.included_km else "—",
                    f"+{money(t.step_price)} / {num(t.step_km)} km" if t.step_price else "—",
                    f"{num(t.yearly_discount)}%" if t.yearly_discount else "—",
                    fmt_date(t.valid_from),
                    "Viloyat narxi" if cell["own"] else "Umumiy narx",
                ])
        return Report(
            title="VLAN ijarasi narxlari (prays-list)",
            filename="prays-list",
            info=[
                ("Sana holatiga", fmt_date(timezone.localdate())),
                ("Formula", "oylik narx = tezlik (Mbit/s) × (asosiy narx + qo'shimcha qadamlar × qadam narxi)"),
            ],
            headers=[
                "Viloyat", "VLAN turi", "Narx birligi", "Asosiy oylik narx", "Asosiy masofa",
                "Masofa qo'shimchasi", "Yillik chegirma", "Amal qilish sanasi", "Manba",
            ],
            rows=report_rows,
        )


class TariffCreateView(FormPageMixin, CreateView):
    model = Tariff
    form_class = TariffForm
    title = "Yangi narx"
    success_message = "Narx qo'shildi."
    extra_permissions = (PRICE_PERM,)


class TariffUpdateView(FormPageMixin, UpdateView):
    model = Tariff
    form_class = TariffForm
    title = "Narxni tahrirlash"
    extra_permissions = (PRICE_PERM,)


class TariffDeleteView(SafeDeleteView):
    model = Tariff
    success_url = reverse_lazy("ipam:price_list")
    extra_permissions = (PRICE_PERM,)


# ---------- Moliya: VLAN ijaralari ----------

def lease_totals(leases):
    totals = {"accrued": Decimal("0"), "paid": Decimal("0"), "balance": Decimal("0"), "monthly": Decimal("0")}
    for x in leases:
        totals["accrued"] += x.accrued_total
        totals["paid"] += x.paid_total
        totals["balance"] += x.balance
        if x.is_active and x.monthly_equivalent is not None:
            totals["monthly"] += x.monthly_equivalent
    return totals


class LeaseListView(PermissionRequiredMixin, ExportMixin, ListView):
    """Ijaralar ro'yxati. Narx ustunlari faqat `view_prices` ruxsati borlarga ko'rinadi."""

    permission_required = "ipam.view_vlanlease"
    template_name = "ipam/lease_list.html"
    context_object_name = "leases"

    @property
    def show_prices(self):
        return self.request.user.has_perm(PRICE_PERM)

    def get_queryset(self):
        self.filter_form = restrict_form(LeaseFilterForm(self.request.GET or None), self.request.user)
        qs = scope_queryset(VLANLease.objects.select_related("vlan__vlan_type", "region", "branch"), self.request.user)
        status = ""
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if data["region"]:
                qs = qs.filter(region=data["region"])
            if data["vlan"]:
                qs = qs.filter(vlan=data["vlan"])
            if data["q"]:
                q = data["q"]
                qs = qs.filter(Q(tenant__icontains=q) | Q(contract_number__icontains=q) | Q(note__icontains=q))
            status = data["status"]
        leases = list(qs)
        today = timezone.localdate()
        if status == "active":
            leases = [x for x in leases if x.is_active]
        elif status == "ended":
            leases = [x for x in leases if x.end_date and x.end_date < today]
        elif status == "debt" and self.show_prices:
            leases = [x for x in leases if x.balance > 0]
        return leases

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        if self.show_prices:
            ctx["totals"] = lease_totals(self.object_list)
        return ctx

    def build_report(self, leases):
        headers = [
            "VLAN", "VLAN turi", "Ijarachi", "Shartnoma", "Viloyat", "Filial", "Tezlik", "Masofa",
            "Davr", "Boshlanishi", "Tugashi",
        ]
        rows = [
            [
                f"VLAN {x.vlan.vid} ({x.vlan.name})", x.vlan_type or "", x.tenant, x.contract_number,
                x.region.name, x.branch.name if x.branch else "", f"{num(x.bandwidth_mbps)} Mbit/s",
                f"{num(x.distance_km)} km", x.get_billing_period_display(), fmt_date(x.start_date), fmt_date(x.end_date),
            ]
            for x in leases
        ]
        totals = [f"Jami: {len(rows)}"] + [""] * (len(headers) - 1)
        if self.show_prices:
            headers += ["Narx (davr uchun)", "Hisoblangan", "To'langan", "Qoldiq (qarz)"]
            for row, x in zip(rows, leases):
                row += [money(x.current_price), money(x.accrued_total), money(x.paid_total), money(x.balance)]
            t = lease_totals(leases)
            totals += ["", money(t["accrued"]), money(t["paid"]), money(t["balance"])]
        return Report(
            title="VLAN ijaralari bo'yicha hisobot",
            filename="vlan-ijaralari",
            info=self.filter_info() + [("Sana holatiga", fmt_date(timezone.localdate()))],
            headers=headers,
            rows=rows,
            totals=totals,
        )


class LeaseDetailView(PermissionRequiredMixin, DetailView):
    permission_required = "ipam.view_vlanlease"
    template_name = "ipam/lease_detail.html"

    def get_queryset(self):
        return scope_queryset(VLANLease.objects.select_related("vlan__vlan_type", "region", "branch__district"), self.request.user)

    def get(self, request, *args, **kwargs):
        fmt = request.GET.get("export")
        if fmt in EXPORT_FORMATS:
            # Hisob-kitob hujjati — moliyaviy ma'lumot
            if not request.user.has_perm(PRICE_PERM):
                raise PermissionDenied
            self.object = self.get_object()
            return export_response(self.build_report(), fmt)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.user.has_perm(PRICE_PERM):
            today = timezone.localdate()
            ctx["tariff"], ctx["calc"] = self.object.calc_on(max(self.object.start_date, today))
            ctx["charges"] = list(reversed(self.object.charges()))
            ctx["payments"] = self.object.payments.all()
            ctx["payment_form"] = PaymentForm()
        return ctx

    def build_report(self):
        lease = self.object
        term_end = fmt_date(lease.end_date) if lease.end_date else "muddatsiz"
        rows = [
            [i, fmt_date(c.start), fmt_date(c.end), money(c.amount), c.source]
            for i, c in enumerate(lease.charges(), start=1)
        ]
        rows += [
            ["", fmt_date(p.date), "To'lov", "−" + money(p.amount), p.note]
            for p in lease.payments.order_by("date")
        ]
        return Report(
            title=f"Hisob-kitob: VLAN {lease.vlan.vid} — {lease.tenant}",
            filename=f"ijara-{lease.pk}",
            info=[
                ("Ijarachi", lease.tenant),
                ("Shartnoma raqami", lease.contract_number or "—"),
                ("VLAN", f"{lease.vlan.vid} ({lease.vlan.name})"),
                ("VLAN turi", lease.vlan_type or "—"),
                ("Viloyat", lease.region.name),
                ("Filial", lease.branch.name if lease.branch else "—"),
                ("Tezlik / masofa", f"{num(lease.bandwidth_mbps)} Mbit/s, {num(lease.distance_km)} km"),
                ("To'lov davri", lease.get_billing_period_display()),
                ("Muddat", f"{fmt_date(lease.start_date)} — {term_end}"),
                ("Hisoblangan", money(lease.accrued_total)),
                ("To'langan", money(lease.paid_total)),
                ("Qoldiq (qarz)", money(lease.balance)),
            ],
            headers=["№", "Davr boshi / sana", "Davr oxiri", "Summa", "Hisob"],
            rows=rows,
            landscape=False,
        )


class LeaseFormMixin(FormPageMixin):
    model = VLANLease
    form_class = LeaseForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["show_prices"] = self.request.user.has_perm(PRICE_PERM)
        return kwargs


class LeaseCreateView(LeaseFormMixin, CreateView):
    title = "Yangi VLAN ijarasi"
    success_message = "Ijara qo'shildi."


class LeaseUpdateView(LeaseFormMixin, UpdateView):
    title = "Ijarani tahrirlash"


class LeaseDeleteView(SafeDeleteView):
    model = VLANLease
    success_url = reverse_lazy("ipam:lease_list")


class PaymentCreateView(FormPageMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    success_message = "To'lov qo'shildi."
    extra_permissions = (PRICE_PERM,)

    def get_lease(self):
        return get_object_or_404(self.scope(VLANLease.objects.all()), pk=self.kwargs["lease_pk"])

    def form_valid(self, form):
        form.instance.lease = self.get_lease()
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = f"To'lov — {self.get_lease()}"
        return ctx


class PaymentDeleteView(SafeDeleteView):
    model = Payment
    extra_permissions = (PRICE_PERM,)

    def get_queryset(self):
        return self.scope(Payment.objects.filter(lease_id=self.kwargs["lease_pk"]))

    def get_success_url(self):
        return reverse("ipam:lease_detail", args=[self.kwargs["lease_pk"]])


# ---------- Kirish huquqlari (RBAC) ----------

ACCESS_PERMS = ("auth.change_user", "auth.change_group")


def price_permission():
    return Permission.objects.get(content_type__app_label="ipam", codename="view_prices")


def describe_access(user, price_groups, perm):
    """Foydalanuvchi obyektiga ro'yxatda kerak bo'ladigan maydonlarni qo'shadi."""
    profile = getattr(user, "profile", None)
    user.group_ids = {g.pk for g in user.groups.all()}
    user.direct_price = perm in user.user_permissions.all()
    user.price_via_group = bool(user.group_ids & price_groups)
    user.can_view_prices = user.is_superuser or user.direct_price or user.price_via_group
    user.is_online = bool(profile and profile.is_online)
    user.last_seen = profile.last_seen if profile else None
    user.all_regions = user.is_superuser or bool(profile and profile.all_regions)
    user.region_names = [r.name for r in profile.regions.all()] if profile else []
    return user


class AccessControlView(PermissionRequiredMixin, TemplateView):
    """Rollar va foydalanuvchilar: narxlarni ko'rishni rol yoki foydalanuvchi darajasida
    yoqish/o'chirish, onlayn holat va biriktirilgan viloyatlar."""

    permission_required = ACCESS_PERMS
    template_name = "ipam/access_control.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        perm = price_permission()
        groups = list(Group.objects.prefetch_related("permissions", "user_set").order_by("name"))
        for g in groups:
            g.can_view_prices = perm in g.permissions.all()
        price_groups = {g.pk for g in groups if g.can_view_prices}

        users = User.objects.select_related("profile").prefetch_related(
            "groups", "user_permissions", "profile__regions"
        )
        users = [describe_access(u, price_groups, perm) for u in users]
        # Avval onlayn foydalanuvchilar, keyin oxirgi faollik bo'yicha
        users.sort(key=lambda u: (not u.is_online, -(u.last_seen.timestamp() if u.last_seen else 0), u.username))
        ctx.update(groups=groups, users=users, online_count=sum(u.is_online for u in users))
        return ctx

    def post(self, request, *args, **kwargs):
        perm = price_permission()
        action = request.POST.get("action")
        enabled = request.POST.get("enabled") == "1"
        state = ["o'chirilgan", "yoqilgan"] if enabled else ["yoqilgan", "o'chirilgan"]
        if action == "group_prices":
            group = get_object_or_404(Group, pk=request.POST.get("group"))
            (group.permissions.add if enabled else group.permissions.remove)(perm)
            log_event(AuditLog.ACTION_ACCESS, object_repr=f"Rol: {group.name}", model_name="Rol",
                      changes={"Narxlarni ko'rish": state})
            result = "ko'rinadigan qilindi" if enabled else "yashirildi"
            messages.success(request, f"«{group.name}» roli uchun narxlar {result}.")
        elif action == "user_prices":
            user = get_object_or_404(User, pk=request.POST.get("user"))
            (user.user_permissions.add if enabled else user.user_permissions.remove)(perm)
            log_event(AuditLog.ACTION_ACCESS, user.profile if hasattr(user, "profile") else None,
                      object_repr=user.username, model_name="Foydalanuvchi",
                      changes={"Narxlarni ko'rish (shaxsan)": state})
            messages.success(request, f"{user.username}: narxlarni ko'rish {state[1]}.")
        elif action == "user_roles":
            user = get_object_or_404(User, pk=request.POST.get("user"))
            old = ", ".join(user.groups.order_by("name").values_list("name", flat=True))
            user.groups.set(Group.objects.filter(pk__in=request.POST.getlist("groups")))
            new = ", ".join(user.groups.order_by("name").values_list("name", flat=True))
            log_event(AuditLog.ACTION_ACCESS, object_repr=user.username, model_name="Foydalanuvchi",
                      changes={"Rollar": [old, new]})
            messages.success(request, f"{user.username} rollari saqlandi.")
        return redirect("ipam:access_control")


class UserAccessView(PermissionRequiredMixin, FormView):
    """Bitta foydalanuvchining rollari, viloyatlari va narx huquqini sozlash."""

    permission_required = ACCESS_PERMS
    template_name = "ipam/user_access.html"
    form_class = UserAccessForm

    def dispatch(self, request, *args, **kwargs):
        self.target = get_object_or_404(User, pk=kwargs["pk"])
        self.profile, _ = UserProfile.objects.get_or_create(user=self.target)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {
            "groups": self.target.groups.all(),
            "all_regions": self.profile.all_regions,
            "regions": self.profile.regions.all(),
            "can_view_prices": self.target.user_permissions.filter(codename="view_prices").exists(),
            "is_active": self.target.is_active,
        }

    def snapshot(self):
        return {
            "Rollar": ", ".join(self.target.groups.order_by("name").values_list("name", flat=True)),
            "Barcha hududlar": "Ha" if self.profile.all_regions else "Yo'q",
            "Viloyatlar": ", ".join(self.profile.regions.order_by("name").values_list("name", flat=True)),
            "Narxlarni ko'rish (shaxsan)": "Ha" if self.target.user_permissions.filter(codename="view_prices").exists() else "Yo'q",
            "Faol": "Ha" if self.target.is_active else "Yo'q",
        }

    def form_valid(self, form):
        data = form.cleaned_data
        if self.target == self.request.user and not data["is_active"]:
            form.add_error("is_active", "O'zingizni faolsizlantira olmaysiz.")
            return self.form_invalid(form)
        before = self.snapshot()
        self.target.groups.set(data["groups"])
        self.profile.all_regions = data["all_regions"]
        self.profile.save(update_fields=["all_regions"])
        self.profile.regions.set(data["regions"])
        perm = price_permission()
        (self.target.user_permissions.add if data["can_view_prices"] else self.target.user_permissions.remove)(perm)
        if self.target.is_active != data["is_active"]:
            self.target.is_active = data["is_active"]
            self.target.save(update_fields=["is_active"])
        after = self.snapshot()
        changes = {k: [before[k], after[k]] for k in after if before[k] != after[k]}
        if changes:
            log_event(AuditLog.ACTION_ACCESS, object_repr=self.target.username, model_name="Foydalanuvchi", changes=changes)
        messages.success(self.request, f"{self.target.username} huquqlari saqlandi.")
        return redirect("ipam:access_control")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["target"] = self.target
        ctx["profile"] = self.profile
        ctx["recent_logs"] = AuditLog.objects.filter(user=self.target)[:10]
        return ctx


# ---------- Harakatlar qaydlari ----------

class AuditLogListView(PermissionRequiredMixin, ExportMixin, ListView):
    permission_required = "ipam.view_auditlog"
    template_name = "ipam/audit_list.html"
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        self.filter_form = AuditFilterForm(self.request.GET or None)
        qs = AuditLog.objects.select_related("user")
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if data["user"]:
                qs = qs.filter(user=data["user"])
            if data["action"]:
                qs = qs.filter(action=data["action"])
            if data["model_name"]:
                qs = qs.filter(model_name=data["model_name"])
            if data["date_from"]:
                qs = qs.filter(timestamp__date__gte=data["date_from"])
            if data["date_to"]:
                qs = qs.filter(timestamp__date__lte=data["date_to"])
            if data["q"]:
                q = data["q"]
                qs = qs.filter(Q(object_repr__icontains=q) | Q(username__icontains=q) | Q(ip_address__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        return ctx

    def build_report(self, logs):
        logs = list(logs[:5000])
        rows = []
        for log in logs:
            details = "; ".join(f"{k}: {v[0] or '—'} → {v[1] or '—'}" if isinstance(v, list) else f"{k}: {v}"
                                for k, v in log.changes.items())
            rows.append([
                timezone.localtime(log.timestamp).strftime("%d.%m.%Y %H:%M:%S"), log.username or "—",
                log.get_action_display(), log.model_name, log.object_repr, details, log.ip_address or "",
            ])
        return Report(
            title="Foydalanuvchilar harakatlari qaydlari",
            filename="harakatlar-qaydi",
            info=self.filter_info(),
            headers=["Vaqt", "Foydalanuvchi", "Harakat", "Bo'lim", "Obyekt", "O'zgarishlar", "IP"],
            rows=rows,
        )

