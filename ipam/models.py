import calendar
import ipaddress
import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .formatting import money, num


class Region(models.Model):
    name = models.CharField("Nomi", max_length=100, unique=True)
    code = models.CharField("Kodi", max_length=10, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Viloyat"
        verbose_name_plural = "Viloyatlar"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("ipam:region_detail", args=[self.pk])


class District(models.Model):
    region = models.ForeignKey(
        Region, verbose_name="Viloyat", on_delete=models.PROTECT, related_name="districts"
    )
    name = models.CharField("Nomi", max_length=100)

    class Meta:
        ordering = ["region__name", "name"]
        verbose_name = "Tuman"
        verbose_name_plural = "Tumanlar"
        constraints = [
            models.UniqueConstraint(fields=["region", "name"], name="unique_district_per_region"),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("ipam:region_detail", args=[self.region_id])


class Branch(models.Model):
    district = models.ForeignKey(
        District, verbose_name="Tuman", on_delete=models.PROTECT, related_name="branches"
    )
    name = models.CharField("Nomi", max_length=150)
    code = models.CharField("Filial kodi", max_length=20, blank=True)
    address = models.CharField("Manzil", max_length=255, blank=True)
    phone = models.CharField("Telefon", max_length=50, blank=True)
    contact_person = models.CharField("Mas'ul shaxs", max_length=150, blank=True)
    description = models.TextField("Tavsif", blank=True)

    class Meta:
        ordering = ["district__region__name", "district__name", "name"]
        verbose_name = "Filial"
        verbose_name_plural = "Filiallar"

    def __str__(self):
        return f"{self.name} ({self.district.name})"

    def get_absolute_url(self):
        return reverse("ipam:branch_detail", args=[self.pk])

    @property
    def region(self):
        return self.district.region


class Device(models.Model):
    TYPE_CHOICES = [
        ("router", "Router"),
        ("switch", "Kommutator (switch)"),
        ("firewall", "Firewall"),
        ("server", "Server"),
        ("pc", "Kompyuter"),
        ("laptop", "Noutbuk"),
        ("printer", "Printer"),
        ("camera", "IP kamera"),
        ("ap", "Wi-Fi nuqta (AP)"),
        ("phone", "IP telefon"),
        ("ups", "UPS"),
        ("other", "Boshqa"),
    ]

    name = models.CharField("Nomi (hostname)", max_length=150)
    device_type = models.CharField("Turi", max_length=20, choices=TYPE_CHOICES, default="pc")
    branch = models.ForeignKey(
        Branch,
        verbose_name="Filial",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="devices",
    )
    vendor = models.CharField("Ishlab chiqaruvchi", max_length=100, blank=True)
    model = models.CharField("Modeli", max_length=100, blank=True)
    serial_number = models.CharField("Seriya raqami", max_length=100, blank=True)
    inventory_number = models.CharField("Inventar raqami", max_length=100, blank=True)
    location = models.CharField("Joylashuvi", max_length=150, blank=True, help_text="Masalan: 2-qavat, server xonasi, 3-shkaf")
    description = models.TextField("Tavsif", blank=True)
    updated_at = models.DateTimeField("Yangilangan", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Qurilma"
        verbose_name_plural = "Qurilmalar"

    def __str__(self):
        return f"{self.name} ({self.get_device_type_display()})"

    def get_absolute_url(self):
        return reverse("ipam:device_detail", args=[self.pk])


class VLANType(models.Model):
    """VLAN xizmat turi (masalan, "L2 kanal", "Internet", "Videokuzatuv").
    Narxlar tur va viloyat kesimida belgilanadi."""

    name = models.CharField("Nomi", max_length=100, unique=True)
    description = models.TextField("Tavsif", blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "VLAN turi"
        verbose_name_plural = "VLAN turlari"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("ipam:vlantype_list")


class VLAN(models.Model):
    vid = models.PositiveSmallIntegerField(
        "VLAN ID",
        unique=True,
        validators=[MinValueValidator(1), MaxValueValidator(4094)],
    )
    name = models.CharField("Nomi", max_length=100)
    vlan_type = models.ForeignKey(
        VLANType, verbose_name="VLAN turi", on_delete=models.PROTECT, null=True, blank=True,
        related_name="vlans", help_text="Ijara narxi shu tur tarifi bo'yicha hisoblanadi.",
    )
    description = models.TextField("Tavsif", blank=True)

    class Meta:
        ordering = ["vid"]
        verbose_name = "VLAN"
        verbose_name_plural = "VLAN'lar"

    def __str__(self):
        return f"{self.vid} — {self.name}"

    def get_absolute_url(self):
        return reverse("ipam:vlan_list")


class Subnet(models.Model):
    network = models.CharField(
        "Tarmoq (CIDR)",
        max_length=50,
        unique=True,
        help_text="Masalan: 192.168.1.0/24",
    )
    name = models.CharField("Nomi", max_length=100)
    vlan = models.ForeignKey(
        VLAN,
        verbose_name="VLAN",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subnets",
    )
    branch = models.ForeignKey(
        Branch,
        verbose_name="Filial",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subnets",
        help_text="Subnet bitta filialga tegishli bo'lsa, undagi yangi IP'lar ham shu filialga yoziladi.",
    )
    gateway = models.GenericIPAddressField("Shlyuz (gateway)", null=True, blank=True)
    description = models.TextField("Tavsif", blank=True)

    class Meta:
        verbose_name = "Subnet"
        verbose_name_plural = "Subnetlar"

    def __str__(self):
        return f"{self.network} ({self.name})"

    def get_absolute_url(self):
        return reverse("ipam:subnet_detail", args=[self.pk])

    @property
    def ip_network(self):
        return ipaddress.ip_network(self.network)

    def usable_hosts(self):
        """Ishlatish mumkin bo'lgan manzillar (tarmoq va broadcast manzilisiz)."""
        net = self.ip_network
        if net.version == 4 and net.prefixlen < 31:
            return net.hosts()
        return iter(net)

    @property
    def size(self):
        net = self.ip_network
        if net.version == 4 and net.prefixlen < 31:
            return net.num_addresses - 2
        return net.num_addresses

    @property
    def used_count(self):
        return self.addresses.count()

    @property
    def utilization(self):
        if not self.size:
            return 0
        return round(self.used_count * 100 / self.size, 1)

    def first_free_ip(self):
        taken = set(self.addresses.values_list("address", flat=True))
        if self.gateway:
            taken.add(self.gateway)
        for ip in self.usable_hosts():
            if str(ip) not in taken:
                return str(ip)
        return None

    def clean(self):
        try:
            net = ipaddress.ip_network(self.network.strip(), strict=True)
        except ValueError:
            raise ValidationError(
                {"network": "Noto'g'ri tarmoq. To'g'ri format: 192.168.1.0/24"}
            )
        self.network = str(net)

        for other in Subnet.objects.exclude(pk=self.pk):
            other_net = other.ip_network
            if other_net.version == net.version and other_net.overlaps(net):
                raise ValidationError(
                    {"network": f"Bu tarmoq mavjud subnet bilan ustma-ust tushadi: {other.network}"}
                )

        if self.gateway and ipaddress.ip_address(self.gateway) not in net:
            raise ValidationError({"gateway": "Shlyuz shu subnet ichida bo'lishi kerak."})


class IPAddress(models.Model):
    STATUS_USED = "used"
    STATUS_RESERVED = "reserved"
    STATUS_DHCP = "dhcp"
    STATUS_CHOICES = [
        (STATUS_USED, "Band"),
        (STATUS_RESERVED, "Zaxirada"),
        (STATUS_DHCP, "DHCP"),
    ]

    subnet = models.ForeignKey(
        Subnet,
        verbose_name="Subnet",
        on_delete=models.CASCADE,
        related_name="addresses",
    )
    address = models.GenericIPAddressField("IP manzil")
    status = models.CharField("Holati", max_length=20, choices=STATUS_CHOICES, default=STATUS_USED)
    branch = models.ForeignKey(
        Branch,
        verbose_name="Filial",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ip_addresses",
    )
    device = models.ForeignKey(
        Device,
        verbose_name="Qurilma",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ip_addresses",
    )
    hostname = models.CharField("Hostname", max_length=255, blank=True)
    mac_address = models.CharField("MAC manzil", max_length=17, blank=True)
    description = models.CharField("Tavsif", max_length=255, blank=True)
    updated_at = models.DateTimeField("Yangilangan", auto_now=True)

    class Meta:
        verbose_name = "IP manzil"
        verbose_name_plural = "IP manzillar"
        constraints = [
            models.UniqueConstraint(fields=["subnet", "address"], name="unique_ip_per_subnet"),
        ]

    def __str__(self):
        return self.address

    def get_absolute_url(self):
        return reverse("ipam:subnet_detail", args=[self.subnet_id])

    def clean(self):
        if not self.address or not self.subnet_id:
            return
        ip = ipaddress.ip_address(self.address)
        net = self.subnet.ip_network
        if ip not in net:
            raise ValidationError({"address": f"Bu IP {net} subnet ichida emas."})
        if net.version == 4 and net.prefixlen < 31 and ip in (net.network_address, net.broadcast_address):
            raise ValidationError({"address": "Tarmoq yoki broadcast manzilini band qilib bo'lmaydi."})
        if self.subnet.gateway and str(ip) == self.subnet.gateway:
            raise ValidationError({"address": "Bu manzil subnetning shlyuzi (gateway)."})
        if IPAddress.objects.filter(subnet=self.subnet, address=self.address).exclude(pk=self.pk).exists():
            raise ValidationError({"address": "Bu IP allaqachon ro'yxatda bor."})

        # Filial ko'rsatilmagan bo'lsa, qurilma yoki subnetning filiali olinadi
        if self.device and self.device.branch_id:
            if self.branch_id and self.branch_id != self.device.branch_id:
                raise ValidationError(
                    {"device": f"Bu qurilma boshqa filialga tegishli: {self.device.branch}"}
                )
            self.branch = self.device.branch
        if not self.branch_id and self.subnet.branch_id:
            self.branch = self.subnet.branch
        if self.device and not self.hostname:
            self.hostname = self.device.name

    @property
    def region(self):
        return self.branch.district.region if self.branch else None

    @property
    def district(self):
        return self.branch.district if self.branch else None


# ---------- Moliya: narxlar va VLAN ijarasi ----------

def add_months(d, months):
    """Sanaga oy qo'shish (31-yanvar + 1 oy = 28/29-fevral)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@dataclass
class PriceCalc:
    """Tarif formulasi bo'yicha hisob natijasi va uning izohi."""

    monthly: Decimal
    yearly: Decimal
    units: Decimal       # Mbit/s soni (yoki kanal narxida 1)
    per_unit: Decimal    # 1 birlik uchun oylik narx (masofa qo'shimchasi bilan)
    steps: int           # masofa bo'yicha qo'shimcha qadamlar soni
    explanation: str


class Tariff(models.Model):
    """VLAN ijarasi tarifi.

    Oylik narx = birliklar × (asosiy narx + qadamlar × qadam narxi), bunda
      birliklar = tezlik (Mbit/s) yoki 1 (kanal uchun qat'iy narx),
      qadamlar  = ⌈(masofa − asosiy narxga kiradigan masofa) / qadam uzunligi⌉.
    Misol: "50 km gacha 1 Mbit/s 100 000 so'm, keyin har 10 km uchun +20 000 so'm".

    Tur yoki viloyat bo'sh bo'lsa — barchasiga amal qiladi. Narx o'zgarganda eski yozuv
    o'chirilmaydi: yangi sana bilan yangisi qo'shiladi va o'tgan davrlar eski narxda qoladi.
    """

    UNIT_MBPS = "mbps"
    UNIT_CHANNEL = "channel"
    UNIT_CHOICES = [
        (UNIT_MBPS, "1 Mbit/s uchun"),
        (UNIT_CHANNEL, "Kanal uchun (tezlikdan qat'i nazar)"),
    ]

    vlan_type = models.ForeignKey(
        VLANType, verbose_name="VLAN turi", on_delete=models.PROTECT, null=True, blank=True,
        related_name="tariffs", help_text="Bo'sh qolsa — barcha turlar uchun.",
    )
    region = models.ForeignKey(
        Region, verbose_name="Viloyat", on_delete=models.PROTECT, null=True, blank=True,
        related_name="tariffs", help_text="Bo'sh qolsa — barcha hududlar uchun.",
    )
    unit = models.CharField("Narx birligi", max_length=10, choices=UNIT_CHOICES, default=UNIT_MBPS)
    base_price = models.DecimalField(
        "Asosiy oylik narx (so'm)", max_digits=14, decimal_places=2, validators=[MinValueValidator(0)],
        help_text="Bir birlik (1 Mbit/s yoki kanal) uchun, asosiy masofa ichida.",
    )
    included_km = models.DecimalField(
        "Asosiy masofa (km gacha)", max_digits=8, decimal_places=2, default=0,
        validators=[MinValueValidator(0)], help_text="Shu masofagacha faqat asosiy narx olinadi.",
    )
    step_km = models.DecimalField(
        "Qadam (har necha km)", max_digits=8, decimal_places=2, default=1,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Asosiy masofadan oshgan har shuncha km (to'liq bo'lmasa ham) uchun qo'shimcha olinadi.",
    )
    step_price = models.DecimalField(
        "Qadam narxi (so'm)", max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="Har bir qadam uchun bir birlikka qo'shiladigan summa.",
    )
    yearly_discount = models.DecimalField(
        "Yillik to'lovda chegirma (%)", max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    valid_from = models.DateField("Amal qilish sanasi", default=timezone.localdate)
    note = models.CharField("Izoh", max_length=255, blank=True)

    class Meta:
        ordering = ["-valid_from"]
        verbose_name = "Tarif"
        verbose_name_plural = "Narxlar (tariflar)"
        permissions = [("view_prices", "VLAN ijara narxlarini ko'rish")]

    def __str__(self):
        return f"{self.vlan_type or 'Barcha turlar'} / {self.region or 'Barcha hududlar'} — {self.valid_from:%d.%m.%Y}"

    def get_absolute_url(self):
        return reverse("ipam:price_list")

    def clean(self):
        clash = Tariff.objects.filter(
            vlan_type=self.vlan_type_id, region=self.region_id, valid_from=self.valid_from
        ).exclude(pk=self.pk)
        if self.valid_from and clash.exists():
            raise ValidationError({"valid_from": "Shu tur va hudud uchun bu sanadan amal qiladigan narx allaqachon bor."})

    @property
    def rule_text(self):
        """Inson o'qiy oladigan qoida: "1 Mbit/s: 100 000 so'm (50 km gacha), +20 000 so'm har 10 km"."""
        unit = "1 Mbit/s" if self.unit == self.UNIT_MBPS else "Kanal"
        text = f"{unit}: {money(self.base_price)}"
        if self.step_price:
            if self.included_km:
                text += f" ({num(self.included_km)} km gacha)"
            text += f", +{money(self.step_price)} har {num(self.step_km)} km"
        return text

    def calculate(self, bandwidth_mbps, distance_km):
        bandwidth = Decimal(bandwidth_mbps or 0)
        distance = Decimal(distance_km or 0)
        units = bandwidth if self.unit == self.UNIT_MBPS else Decimal(1)
        extra_km = max(Decimal(0), distance - self.included_km)
        steps = math.ceil(extra_km / self.step_km) if self.step_price and extra_km else 0
        per_unit = self.base_price + steps * self.step_price
        monthly = (units * per_unit).quantize(Decimal("0.01"))
        yearly = (monthly * 12 * (100 - self.yearly_discount) / 100).quantize(Decimal("0.01"))

        inner = money(self.base_price)
        if steps:
            inner = f"{inner} + {steps} × {money(self.step_price)}"
        if self.unit == self.UNIT_MBPS:
            explanation = f"{num(units)} Mbit/s × ({inner}) = {money(monthly)}"
        else:
            explanation = f"Kanal: {inner} = {money(monthly)}"
        if steps:
            explanation += f"; {num(distance)} km"
        return PriceCalc(monthly, yearly, units, per_unit, steps, explanation)

    @classmethod
    def find(cls, vlan_type, region, on_date):
        """Shu sanada amal qiladigan eng aniq tarif. Tartib:
        tur+viloyat → tur (barcha hududlar) → viloyat (barcha turlar) → umumiy tarif."""
        qs = cls.objects.filter(valid_from__lte=on_date).order_by("-valid_from")
        candidates = []
        for t in ([vlan_type, None] if vlan_type is not None else [None]):
            for r in ([region, None] if region is not None else [None]):
                candidates.append((t, r))
        for t, r in candidates:
            tariff = qs.filter(
                **({"vlan_type": t} if t is not None else {"vlan_type__isnull": True}),
                **({"region": r} if r is not None else {"region__isnull": True}),
            ).first()
            if tariff:
                return tariff
        return None


@dataclass
class Charge:
    """Bitta to'lov davri uchun hisoblangan summa."""

    start: date
    end: date
    amount: Decimal | None
    source: str


class VLANLease(models.Model):
    PERIOD_MONTHLY = "monthly"
    PERIOD_YEARLY = "yearly"
    PERIOD_CHOICES = [
        (PERIOD_MONTHLY, "Oylik"),
        (PERIOD_YEARLY, "Yillik"),
    ]

    vlan = models.ForeignKey(VLAN, verbose_name="VLAN", on_delete=models.PROTECT, related_name="leases")
    tenant = models.CharField("Ijarachi", max_length=200)
    contract_number = models.CharField("Shartnoma raqami", max_length=100, blank=True)
    region = models.ForeignKey(
        Region, verbose_name="Viloyat", on_delete=models.PROTECT, related_name="leases",
        help_text="Narx shu viloyat tarifi bo'yicha hisoblanadi.",
    )
    branch = models.ForeignKey(
        Branch, verbose_name="Filial", on_delete=models.SET_NULL, null=True, blank=True, related_name="leases",
    )
    bandwidth_mbps = models.DecimalField(
        "Tezlik (Mbit/s)", max_digits=10, decimal_places=2, default=1,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    distance_km = models.DecimalField(
        "Masofa (km)", max_digits=8, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    billing_period = models.CharField(
        "To'lov davri", max_length=10, choices=PERIOD_CHOICES, default=PERIOD_MONTHLY
    )
    start_date = models.DateField("Boshlanish sanasi", default=timezone.localdate)
    end_date = models.DateField("Tugash sanasi", null=True, blank=True, help_text="Bo'sh qolsa — muddatsiz.")
    custom_price = models.DecimalField(
        "Maxsus narx (so'm)", max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Bitta to'lov davri uchun. Bo'sh qolsa — tarif bo'yicha hisoblanadi.",
    )
    note = models.TextField("Izoh", blank=True)
    created_at = models.DateTimeField("Kiritilgan", auto_now_add=True)

    @property
    def vlan_type(self):
        return self.vlan.vlan_type

    class Meta:
        ordering = ["-start_date", "tenant"]
        verbose_name = "VLAN ijarasi"
        verbose_name_plural = "VLAN ijaralari"

    def __str__(self):
        return f"VLAN {self.vlan.vid} — {self.tenant}"

    def get_absolute_url(self):
        return reverse("ipam:lease_detail", args=[self.pk])

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Tugash sanasi boshlanish sanasidan oldin bo'lishi mumkin emas."})
        if self.branch_id and self.region_id and self.branch.district.region_id != self.region_id:
            raise ValidationError({"branch": "Filial tanlangan viloyatda emas."})

    @property
    def months_per_period(self):
        return 1 if self.billing_period == self.PERIOD_MONTHLY else 12

    @property
    def is_active(self):
        today = timezone.localdate()
        return self.start_date <= today and (self.end_date is None or self.end_date >= today)

    def tariff_on(self, on_date):
        return Tariff.find(self.vlan.vlan_type, self.region, on_date)

    def calc_on(self, on_date):
        """Shu sanadagi tarif va formula bo'yicha hisob (maxsus narxda — None)."""
        tariff = self.tariff_on(on_date)
        if tariff is None:
            return None, None
        return tariff, tariff.calculate(self.bandwidth_mbps, self.distance_km)

    def price_on(self, on_date):
        """Shu sanada bitta to'lov davri narxi va uning izohi."""
        if self.custom_price is not None:
            return self.custom_price, "maxsus narx"
        tariff, calc = self.calc_on(on_date)
        if tariff is None:
            return None, "tarif topilmadi"
        price = calc.monthly if self.billing_period == self.PERIOD_MONTHLY else calc.yearly
        scope = " / ".join([
            tariff.vlan_type.name if tariff.vlan_type_id else "barcha turlar",
            tariff.region.name if tariff.region_id else "barcha hududlar",
        ])
        source = f"{scope}, {tariff.valid_from:%d.%m.%Y} dan: {calc.explanation}"
        if self.billing_period == self.PERIOD_YEARLY:
            source += " × 12" + (f" − {num(tariff.yearly_discount)}%" if tariff.yearly_discount else "")
        return price, source

    @property
    def current_price(self):
        on_date = min(timezone.localdate(), self.end_date or date.max)
        return self.price_on(max(on_date, self.start_date))[0]

    @property
    def monthly_equivalent(self):
        price = self.current_price
        if price is None:
            return None
        return (price / self.months_per_period).quantize(Decimal("0.01"))

    def charges(self, until=None):
        """Boshlanish sanasidan `until` gacha (standart — bugun) boshlangan barcha to'lov
        davrlari. Har bir davr boshidagi narx bo'yicha hisoblanadi (oldindan to'lov)."""
        until = until or timezone.localdate()
        if self.end_date:
            until = min(until, self.end_date)
        result = []
        n = 0
        while True:
            start = add_months(self.start_date, n * self.months_per_period)
            if start > until:
                break
            end = add_months(self.start_date, (n + 1) * self.months_per_period) - timedelta(days=1)
            if self.end_date:
                end = min(end, self.end_date)
            amount, source = self.price_on(start)
            result.append(Charge(start, end, amount, source))
            n += 1
        return result

    @property
    def accrued_total(self):
        return sum((c.amount for c in self.charges() if c.amount is not None), Decimal("0"))

    @property
    def paid_total(self):
        return self.payments.aggregate(s=models.Sum("amount"))["s"] or Decimal("0")

    @property
    def balance(self):
        """Musbat — qarzdorlik, manfiy — oldindan to'langan."""
        return self.accrued_total - self.paid_total


class Payment(models.Model):
    lease = models.ForeignKey(VLANLease, verbose_name="Ijara", on_delete=models.CASCADE, related_name="payments")
    date = models.DateField("Sana", default=timezone.localdate)
    amount = models.DecimalField(
        "Summa (so'm)", max_digits=14, decimal_places=2, validators=[MinValueValidator(0)]
    )
    note = models.CharField("Izoh", max_length=255, blank=True)

    class Meta:
        ordering = ["-date", "-pk"]
        verbose_name = "To'lov"
        verbose_name_plural = "To'lovlar"

    def __str__(self):
        return f"{self.date:%d.%m.%Y} — {self.amount} so'm"

    def get_absolute_url(self):
        return self.lease.get_absolute_url()


# ---------- Foydalanuvchilar: hududlar, faollik, harakatlar qaydi ----------

ONLINE_WINDOW = timedelta(minutes=5)


class UserProfile(models.Model):
    """Foydalanuvchiga biriktirilgan hududlar va oxirgi faollik vaqti."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name="Foydalanuvchi", on_delete=models.CASCADE, related_name="profile"
    )
    all_regions = models.BooleanField(
        "Barcha hududlar", default=False,
        help_text="Belgilansa, foydalanuvchi barcha viloyatlar ma'lumotlari bilan ishlaydi.",
    )
    regions = models.ManyToManyField(
        Region, verbose_name="Viloyatlar", blank=True, related_name="users",
        help_text="Foydalanuvchi faqat shu viloyatlarga tegishli ma'lumotlarni ko'radi va o'zgartiradi.",
    )
    last_seen = models.DateTimeField("Oxirgi faollik", null=True, blank=True)
    last_ip = models.GenericIPAddressField("Oxirgi IP", null=True, blank=True)
    is_logged_in = models.BooleanField("Tizimda", default=False)

    class Meta:
        verbose_name = "Foydalanuvchi profili"
        verbose_name_plural = "Foydalanuvchi profillari"

    def __str__(self):
        return str(self.user)

    @property
    def is_online(self):
        return bool(
            self.is_logged_in and self.last_seen and timezone.now() - self.last_seen <= ONLINE_WINDOW
        )


class AuditLog(models.Model):
    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"
    ACTION_LOGIN = "login"
    ACTION_LOGOUT = "logout"
    ACTION_LOGIN_FAILED = "login_failed"
    ACTION_EXPORT = "export"
    ACTION_ACCESS = "access"
    ACTION_CHOICES = [
        (ACTION_CREATE, "Qo'shdi"),
        (ACTION_UPDATE, "O'zgartirdi"),
        (ACTION_DELETE, "O'chirdi"),
        (ACTION_LOGIN, "Tizimga kirdi"),
        (ACTION_LOGOUT, "Tizimdan chiqdi"),
        (ACTION_LOGIN_FAILED, "Kirish urinishi muvaffaqiyatsiz"),
        (ACTION_EXPORT, "Hisobot yukladi"),
        (ACTION_ACCESS, "Huquqlarni o'zgartirdi"),
    ]

    timestamp = models.DateTimeField("Vaqt", auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Foydalanuvchi", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audit_logs",
    )
    username = models.CharField("Login", max_length=150, blank=True)
    action = models.CharField("Harakat", max_length=20, choices=ACTION_CHOICES, db_index=True)
    model_name = models.CharField("Bo'lim", max_length=100, blank=True)
    object_id = models.CharField("Obyekt ID", max_length=64, blank=True)
    object_repr = models.CharField("Obyekt", max_length=255, blank=True)
    changes = models.JSONField("O'zgarishlar", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("IP manzil", null=True, blank=True)

    class Meta:
        ordering = ["-timestamp", "-pk"]
        verbose_name = "Harakat qaydi"
        verbose_name_plural = "Harakatlar qaydlari"

    def __str__(self):
        return f"{self.timestamp:%d.%m.%Y %H:%M} {self.username} {self.get_action_display()} {self.object_repr}"
