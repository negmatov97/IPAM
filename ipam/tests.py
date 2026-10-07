from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .formatting import money
from .models import (
    VLAN, AuditLog, Branch, Device, District, IPAddress, Payment, Region, Subnet, Tariff, UserProfile, VLANLease,
    VLANType, add_months,
)


def make_branch(region_name="Samarqand viloyati", district_name="Urgut tumani", name="Urgut filiali"):
    region = Region.objects.get(name=region_name)
    district, _ = District.objects.get_or_create(region=region, name=district_name)
    return Branch.objects.create(district=district, name=name)


class SubnetModelTests(TestCase):
    def test_network_is_validated_and_normalized(self):
        s = Subnet(network=" 10.0.0.0/24 ", name="LAN")
        s.full_clean()
        self.assertEqual(s.network, "10.0.0.0/24")

    def test_invalid_network_rejected(self):
        for bad in ["10.0.0.1/24", "300.0.0.0/24", "salom"]:
            with self.assertRaises(ValidationError):
                Subnet(network=bad, name="x").full_clean()

    def test_overlapping_subnet_rejected(self):
        Subnet.objects.create(network="10.0.0.0/24", name="A")
        with self.assertRaises(ValidationError):
            Subnet(network="10.0.0.128/25", name="B").full_clean()
        Subnet(network="10.0.1.0/24", name="C").full_clean()

    def test_gateway_must_be_inside(self):
        with self.assertRaises(ValidationError):
            Subnet(network="10.0.0.0/24", name="A", gateway="10.0.1.1").full_clean()

    def test_size_and_utilization(self):
        s = Subnet.objects.create(network="192.168.1.0/24", name="A", gateway="192.168.1.1")
        self.assertEqual(s.size, 254)
        IPAddress.objects.create(subnet=s, address="192.168.1.10")
        self.assertEqual(s.used_count, 1)
        self.assertEqual(s.utilization, 0.4)

    def test_first_free_skips_gateway_and_used(self):
        s = Subnet.objects.create(network="192.168.1.0/29", name="A", gateway="192.168.1.1")
        IPAddress.objects.create(subnet=s, address="192.168.1.2")
        self.assertEqual(s.first_free_ip(), "192.168.1.3")

    def test_first_free_none_when_full(self):
        s = Subnet.objects.create(network="192.168.1.0/30", name="A")
        IPAddress.objects.create(subnet=s, address="192.168.1.1")
        IPAddress.objects.create(subnet=s, address="192.168.1.2")
        self.assertIsNone(s.first_free_ip())


class IPAddressModelTests(TestCase):
    def setUp(self):
        self.subnet = Subnet.objects.create(network="192.168.1.0/24", name="A", gateway="192.168.1.1")

    def test_ip_outside_subnet_rejected(self):
        with self.assertRaises(ValidationError):
            IPAddress(subnet=self.subnet, address="10.0.0.5").full_clean()

    def test_network_broadcast_and_gateway_rejected(self):
        for ip in ["192.168.1.0", "192.168.1.255", "192.168.1.1"]:
            with self.assertRaises(ValidationError):
                IPAddress(subnet=self.subnet, address=ip).full_clean()

    def test_duplicate_rejected(self):
        IPAddress.objects.create(subnet=self.subnet, address="192.168.1.5")
        with self.assertRaises(ValidationError):
            IPAddress(subnet=self.subnet, address="192.168.1.5").full_clean()


class LocationTests(TestCase):
    def test_regions_seeded(self):
        self.assertEqual(Region.objects.count(), 14)
        self.assertTrue(Region.objects.filter(name="Toshkent shahri", code="TK").exists())

    def test_ip_takes_branch_from_device(self):
        branch = make_branch()
        device = Device.objects.create(name="urgut-sw1", device_type="switch", branch=branch)
        subnet = Subnet.objects.create(network="10.1.0.0/24", name="Urgut")
        ip = IPAddress(subnet=subnet, address="10.1.0.10", device=device)
        ip.full_clean()
        self.assertEqual(ip.branch, branch)
        self.assertEqual(ip.hostname, "urgut-sw1")
        self.assertEqual(ip.region.name, "Samarqand viloyati")
        self.assertEqual(ip.district.name, "Urgut tumani")

    def test_ip_takes_branch_from_subnet(self):
        branch = make_branch()
        subnet = Subnet.objects.create(network="10.1.0.0/24", name="Urgut", branch=branch)
        ip = IPAddress(subnet=subnet, address="10.1.0.10")
        ip.full_clean()
        self.assertEqual(ip.branch, branch)

    def test_device_from_other_branch_rejected(self):
        b1 = make_branch()
        b2 = make_branch(district_name="Kattaqo'rg'on tumani", name="Kattaqo'rg'on filiali")
        device = Device.objects.create(name="pc-1", branch=b2)
        subnet = Subnet.objects.create(network="10.1.0.0/24", name="Urgut")
        with self.assertRaises(ValidationError):
            IPAddress(subnet=subnet, address="10.1.0.10", branch=b1, device=device).full_clean()


class ViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("admin", password="test-parol-123")
        self.client.force_login(self.user)

    def test_login_required(self):
        self.client.logout()
        resp = self.client.get(reverse("ipam:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_full_flow(self):
        region = Region.objects.get(name="Toshkent shahri")
        resp = self.client.post(reverse("ipam:district_create"), {"region": region.pk, "name": "Chilonzor tumani"})
        self.assertRedirects(resp, region.get_absolute_url())
        district = District.objects.get(name="Chilonzor tumani")

        resp = self.client.post(reverse("ipam:branch_create"), {
            "district": district.pk, "name": "Chilonzor filiali", "code": "F-01",
        })
        branch = Branch.objects.get(code="F-01")
        self.assertRedirects(resp, branch.get_absolute_url())

        resp = self.client.post(reverse("ipam:device_create"), {
            "name": "chil-printer", "device_type": "printer", "branch": branch.pk,
        })
        device = Device.objects.get(name="chil-printer")
        self.assertRedirects(resp, device.get_absolute_url())

        self.client.post(reverse("ipam:vlan_create"), {"vid": 10, "name": "Ofis"})
        resp = self.client.post(reverse("ipam:subnet_create"), {
            "network": "192.168.10.0/24", "name": "Chilonzor LAN", "vlan": VLAN.objects.get().pk,
            "gateway": "192.168.10.1", "branch": branch.pk,
        })
        self.assertEqual(resp.status_code, 302)
        subnet = Subnet.objects.get()

        # Yangi IP formasi birinchi bo'sh manzilni va subnet filialini taklif qiladi
        resp = self.client.get(reverse("ipam:ip_create", args=[subnet.pk]))
        self.assertContains(resp, "192.168.10.2")
        self.assertContains(resp, f'<option value="{branch.pk}" selected data-parent="{district.pk}">')

        resp = self.client.post(reverse("ipam:ip_create", args=[subnet.pk]), {
            "address": "192.168.10.2", "status": "used", "device": device.pk,
        })
        self.assertEqual(resp.status_code, 302)
        ip = IPAddress.objects.get()
        self.assertEqual(ip.branch, branch)
        self.assertEqual(ip.hostname, "chil-printer")

        # Takroriy IP forma xatosini qaytaradi
        resp = self.client.post(reverse("ipam:ip_create", args=[subnet.pk]), {
            "address": "192.168.10.2", "status": "used",
        })
        self.assertContains(resp, "allaqachon")

        for url in [
            reverse("ipam:dashboard"), branch.get_absolute_url(), device.get_absolute_url(),
            subnet.get_absolute_url(),
        ]:
            self.assertContains(self.client.get(url), "192.168.10.2", msg_prefix=url)
        self.assertContains(self.client.get(region.get_absolute_url()), "Chilonzor filiali")

        # Filtrlar
        resp = self.client.get(reverse("ipam:ip_list"), {"region": region.pk})
        self.assertContains(resp, "192.168.10.2")
        other = Region.objects.get(name="Buxoro viloyati")
        resp = self.client.get(reverse("ipam:ip_list"), {"region": other.pk})
        self.assertNotContains(resp, "192.168.10.2")
        resp = self.client.get(reverse("ipam:device_list"), {"device_type": "printer", "q": "192.168.10"})
        self.assertContains(resp, "chil-printer")
        resp = self.client.get(reverse("ipam:branch_list"), {"district": district.pk})
        self.assertContains(resp, "Chilonzor filiali")

        # CSV eksport
        resp = self.client.get(reverse("ipam:ip_list"), {"export": "csv"})
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        content = resp.content.decode("utf-8-sig")
        self.assertIn("192.168.10.2;192.168.10.0/24;Band;Toshkent shahri;Chilonzor tumani;Chilonzor filiali;chil-printer;Printer", content)

    def test_protected_delete_shows_message(self):
        branch = make_branch()
        resp = self.client.post(reverse("ipam:district_delete", args=[branch.district_id]), follow=True)
        self.assertContains(resp, "avval uning filiallarini")
        self.assertTrue(District.objects.filter(pk=branch.district_id).exists())

    def test_pages_render(self):
        Subnet.objects.create(network="10.0.0.0/16", name="Katta")
        names = [
            "dashboard", "region_list", "region_create", "district_create", "branch_list", "branch_create",
            "device_list", "device_create", "subnet_list", "subnet_create", "ip_list", "vlan_list", "vlan_create",
        ]
        for name in names:
            self.assertEqual(self.client.get(reverse(f"ipam:{name}")).status_code, 200, name)
        # Katta subnetda to'r chiqmaydi, lekin sahifa ochiladi
        s = Subnet.objects.get()
        self.assertEqual(self.client.get(s.get_absolute_url()).status_code, 200)


def on_day(d):
    """Testlarda "bugun"ni belgilash."""
    return mock.patch("django.utils.timezone.localdate", return_value=d)


class TariffFormulaTests(TestCase):
    def setUp(self):
        self.l2 = VLANType.objects.create(name="L2 kanal")
        self.sam = Region.objects.get(name="Samarqand viloyati")
        self.bux = Region.objects.get(name="Buxoro viloyati")

    def tariff(self, **kw):
        defaults = {"base_price": 100_000, "valid_from": date(2026, 1, 1)}
        return Tariff.objects.create(**{**defaults, **kw})

    def test_per_mbps_with_distance_steps(self):
        # 50 km gacha 1 Mbit/s 100 000, keyin har 10 km uchun +20 000
        t = self.tariff(included_km=50, step_km=10, step_price=20_000)
        self.assertEqual(t.calculate(10, 50).monthly, 1_000_000)      # qo'shimcha yo'q
        self.assertEqual(t.calculate(10, 51).monthly, 1_200_000)      # 1 km oshdi -> 1 qadam
        self.assertEqual(t.calculate(10, 73).monthly, 1_600_000)      # 23 km -> 3 qadam
        calc = t.calculate(10, 73)
        self.assertEqual(calc.steps, 3)
        self.assertIn("10 Mbit/s", calc.explanation)

    def test_per_km_flat_channel(self):
        # Kanal: 30 km gacha 500 000, undan keyin har km uchun +20 so'm
        t = self.tariff(unit="channel", base_price=500_000, included_km=30, step_km=1, step_price=20)
        self.assertEqual(t.calculate(100, 30).monthly, 500_000)  # tezlik ta'sir qilmaydi
        self.assertEqual(t.calculate(100, 45.5).monthly, 500_000 + 16 * 20)

    def test_fractional_bandwidth_and_yearly_discount(self):
        t = self.tariff(yearly_discount=10)
        calc = t.calculate(Decimal("2.5"), 0)
        self.assertEqual(calc.monthly, 250_000)
        self.assertEqual(calc.yearly, 2_700_000)  # 250 000 × 12 − 10%

    def test_find_prefers_most_specific(self):
        general = self.tariff()
        by_region = self.tariff(region=self.sam, base_price=80_000)
        by_type = self.tariff(vlan_type=self.l2, base_price=120_000)
        exact = self.tariff(vlan_type=self.l2, region=self.sam, base_price=90_000)
        on = date(2026, 5, 1)
        self.assertEqual(Tariff.find(self.l2, self.sam, on), exact)
        self.assertEqual(Tariff.find(self.l2, self.bux, on), by_type)
        self.assertEqual(Tariff.find(None, self.sam, on), by_region)
        self.assertEqual(Tariff.find(None, self.bux, on), general)
        self.assertIsNone(Tariff.find(self.l2, self.sam, date(2025, 12, 31)))

    def test_duplicate_tariff_rejected(self):
        self.tariff(vlan_type=self.l2)
        with self.assertRaises(ValidationError):
            Tariff(vlan_type=self.l2, base_price=1, valid_from=date(2026, 1, 1)).full_clean()
        Tariff(vlan_type=self.l2, region=self.sam, base_price=1, valid_from=date(2026, 1, 1)).full_clean()


class LeaseTests(TestCase):
    def setUp(self):
        self.l2 = VLANType.objects.create(name="L2 kanal")
        self.vlan = VLAN.objects.create(vid=100, name="Mijoz", vlan_type=self.l2)
        self.sam = Region.objects.get(name="Samarqand viloyati")
        Tariff.objects.create(vlan_type=self.l2, region=self.sam, base_price=80_000, included_km=50,
                              step_km=10, step_price=10_000, valid_from=date(2026, 1, 1))

    def lease(self, **kw):
        defaults = {"vlan": self.vlan, "tenant": "MChJ Test", "region": self.sam, "start_date": date(2026, 1, 15),
                    "bandwidth_mbps": 10, "distance_km": 65}
        return VLANLease.objects.create(**{**defaults, **kw})

    def test_add_months(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(add_months(date(2026, 11, 15), 3), date(2027, 2, 15))

    def test_monthly_charges_follow_price_changes(self):
        # 10 Mbit/s × (80 000 + 2 × 10 000) = 1 000 000; martdan 90 000 -> 1 100 000
        Tariff.objects.create(vlan_type=self.l2, region=self.sam, base_price=90_000, included_km=50,
                              step_km=10, step_price=10_000, valid_from=date(2026, 3, 1))
        lease = self.lease()
        with on_day(date(2026, 4, 20)):
            self.assertEqual([c.amount for c in lease.charges()], [1_000_000, 1_000_000, 1_100_000, 1_100_000])
            self.assertEqual(lease.accrued_total, 4_200_000)
            Payment.objects.create(lease=lease, amount=2_000_000, date=date(2026, 2, 1))
            self.assertEqual(lease.balance, 2_200_000)
            self.assertIn("10 Mbit/s", lease.charges()[0].source)

    def test_yearly_lease(self):
        lease = self.lease(billing_period="yearly", start_date=date(2026, 1, 1))
        with on_day(date(2026, 6, 1)):
            self.assertEqual([c.amount for c in lease.charges()], [12_000_000])
            self.assertEqual(lease.monthly_equivalent, 1_000_000)

    def test_custom_price_and_end_date(self):
        lease = self.lease(custom_price=50_000, end_date=date(2026, 3, 1))
        with on_day(date(2026, 12, 1)):
            self.assertEqual(lease.accrued_total, 100_000)
            self.assertFalse(lease.is_active)

    def test_missing_tariff_is_reported(self):
        other = VLAN.objects.create(vid=101, name="Turi yo'q")
        lease = self.lease(vlan=other)
        with on_day(date(2026, 1, 20)):
            (charge,) = lease.charges()
        self.assertIsNone(charge.amount)
        self.assertEqual(charge.source, "tarif topilmadi")

    def test_branch_must_be_in_region(self):
        branch = make_branch(region_name="Buxoro viloyati", district_name="G'ijduvon tumani", name="G'ijduvon")
        with self.assertRaises(ValidationError):
            VLANLease(vlan=self.vlan, tenant="X", region=self.sam, branch=branch, start_date=date(2026, 1, 1)).full_clean()

    def test_money_format(self):
        self.assertEqual(money(Decimal("1250000")), "1\xa0250\xa0000\xa0so'm")
        self.assertEqual(money(Decimal("1250000.5")), "1\xa0250\xa0000,50\xa0so'm")
        self.assertEqual(money(None), "—")


class FinanceViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("admin", password="test-parol-123"))
        self.l2 = VLANType.objects.create(name="L2 kanal")
        self.vlan = VLAN.objects.create(vid=200, name="Bank", vlan_type=self.l2)
        self.sam = Region.objects.get(name="Samarqand viloyati")

    def test_flow_and_exports(self):
        resp = self.client.post(reverse("ipam:tariff_create"), {
            "vlan_type": self.l2.pk, "region": self.sam.pk, "unit": "mbps", "base_price": "80000",
            "included_km": "50", "step_km": "10", "step_price": "10000", "yearly_discount": "0",
            "valid_from": "2026-01-01",
        })
        self.assertRedirects(resp, reverse("ipam:price_list"))

        resp = self.client.get(reverse("ipam:price_list"))
        self.assertContains(resp, "1 Mbit/s: 80\xa0000\xa0so&#x27;m (50 km gacha), +10\xa0000\xa0so&#x27;m har 10 km")

        # Kalkulyator: 10 Mbit/s, 65 km -> 10 × (80 000 + 2 × 10 000)
        resp = self.client.get(reverse("ipam:price_list"), {
            "vlan_type": self.l2.pk, "region": self.sam.pk, "bandwidth_mbps": "10", "distance_km": "65",
        })
        self.assertContains(resp, "1\xa0000\xa0000\xa0so&#x27;m")

        resp = self.client.post(reverse("ipam:lease_create"), {
            "vlan": self.vlan.pk, "tenant": "Agrobank filiali", "contract_number": "15/2026",
            "region": self.sam.pk, "bandwidth_mbps": "10", "distance_km": "65",
            "billing_period": "monthly", "start_date": "2026-01-10",
        })
        lease = VLANLease.objects.get()
        self.assertRedirects(resp, lease.get_absolute_url())
        self.client.post(reverse("ipam:payment_create", args=[lease.pk]), {"date": "2026-01-12", "amount": "500000"})

        with on_day(date(2026, 2, 20)):
            resp = self.client.get(lease.get_absolute_url())
            self.assertContains(resp, "2\xa0000\xa0000\xa0so&#x27;m")  # 2 oy × 1 000 000
            self.assertContains(resp, "1\xa0500\xa0000\xa0so&#x27;m")  # qarz

            for url in [lease.get_absolute_url(), reverse("ipam:lease_list"), reverse("ipam:price_list"),
                        reverse("ipam:ip_list"), reverse("ipam:device_list"), reverse("ipam:subnet_list")]:
                for fmt, magic in [("docx", b"PK"), ("pdf", b"%PDF"), ("csv", b"\xef\xbb\xbf")]:
                    resp = self.client.get(url, {"export": fmt})
                    self.assertTrue(resp.content.startswith(magic), f"{url} {fmt}")

            from io import BytesIO

            from docx import Document

            doc = Document(BytesIO(self.client.get(reverse("ipam:lease_list"), {"export": "docx"}).content))
            cells = [c.text for row in doc.tables[0].rows for c in row.cells]
            self.assertIn("Agrobank filiali", cells)
            self.assertIn("1\xa0500\xa0000\xa0so'm", cells)


class RBACTests(TestCase):
    """Narxlarni ko'rish huquqi rol yoki foydalanuvchi darajasida yoqiladi/o'chiriladi."""

    def setUp(self):
        self.sam = Region.objects.get(name="Samarqand viloyati")
        vlan = VLAN.objects.create(vid=300, name="Pochta")
        Tariff.objects.create(base_price=123_456, unit="channel", valid_from=date(2026, 1, 1))
        self.lease = VLANLease.objects.create(vlan=vlan, tenant="Pochta AJ", region=self.sam, start_date=date(2026, 1, 1))
        self.operator = User.objects.create_user("operator", password="test-parol-123")
        self.operator.groups.add(Group.objects.get(name="Tarmoq operatori"))
        self.finance = User.objects.create_user("buxgalter", password="test-parol-123")
        self.finance.groups.add(Group.objects.get(name="Moliya bo'limi"))
        self.admin = User.objects.create_user("admin2", password="test-parol-123")
        self.admin.groups.add(Group.objects.get(name="Administrator"))
        for u in (self.operator, self.finance, self.admin):
            UserProfile.objects.create(user=u, all_regions=True)

    def test_roles_created(self):
        self.assertTrue(self.finance.has_perm("ipam.view_prices"))
        self.assertTrue(self.admin.has_perm("ipam.view_prices"))
        self.assertFalse(self.operator.has_perm("ipam.view_prices"))
        self.assertTrue(self.operator.has_perm("ipam.add_ipaddress"))
        self.assertFalse(self.finance.has_perm("ipam.add_ipaddress"))

    def test_operator_cannot_see_prices(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse("ipam:price_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("ipam:tariff_create")).status_code, 403)
        # Ijara shartnomasini ko'radi, lekin summalarsiz
        resp = self.client.get(self.lease.get_absolute_url())
        self.assertContains(resp, "Pochta AJ")
        self.assertNotContains(resp, "123\xa0456")
        resp = self.client.get(reverse("ipam:lease_list"))
        self.assertContains(resp, "Pochta AJ")
        self.assertNotContains(resp, "123\xa0456")
        self.assertNotContains(self.client.get(reverse("ipam:dashboard")), "Qarzdorlik")
        csv_text = self.client.get(reverse("ipam:lease_list"), {"export": "csv"}).content.decode("utf-8-sig")
        self.assertIn("Pochta AJ", csv_text)
        self.assertNotIn("Hisoblangan", csv_text)
        self.assertEqual(self.client.get(self.lease.get_absolute_url(), {"export": "pdf"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("ipam:payment_create", args=[self.lease.pk]), {"amount": "1"}).status_code, 403)
        # Operator ijara shartnomasini qo'sha olmaydi (faqat ko'radi)
        self.assertEqual(self.client.get(reverse("ipam:lease_create")).status_code, 403)

    def test_lease_form_hides_custom_price_without_permission(self):
        self.finance.groups.clear()
        self.finance.user_permissions.add(*Permission.objects.filter(codename__in=["add_vlanlease", "view_vlanlease"]))
        self.client.force_login(self.finance)
        form = self.client.get(reverse("ipam:lease_create")).context["form"]
        self.assertNotIn("custom_price", form.fields)

    def test_finance_sees_prices(self):
        self.client.force_login(self.finance)
        self.assertContains(self.client.get(reverse("ipam:price_list")), "123\xa0456")
        self.assertContains(self.client.get(self.lease.get_absolute_url()), "123\xa0456")
        self.assertIn("custom_price", self.client.get(reverse("ipam:lease_create")).context["form"].fields)
        # Moliya xodimi tarmoq ma'lumotini o'zgartira olmaydi
        self.assertEqual(self.client.get(reverse("ipam:subnet_create")).status_code, 403)

    def test_toggle_for_role_and_user(self):
        self.client.force_login(self.admin)
        url = reverse("ipam:access_control")
        self.assertEqual(self.client.get(url).status_code, 200)

        operators = Group.objects.get(name="Tarmoq operatori")
        self.client.post(url, {"action": "group_prices", "group": operators.pk, "enabled": "1"})
        self.assertTrue(User.objects.get(pk=self.operator.pk).has_perm("ipam.view_prices"))
        self.client.post(url, {"action": "group_prices", "group": operators.pk, "enabled": "0"})
        self.assertFalse(User.objects.get(pk=self.operator.pk).has_perm("ipam.view_prices"))

        self.client.post(url, {"action": "user_prices", "user": self.operator.pk, "enabled": "1"})
        self.assertTrue(User.objects.get(pk=self.operator.pk).has_perm("ipam.view_prices"))
        self.client.post(url, {"action": "user_prices", "user": self.operator.pk, "enabled": "0"})
        self.assertFalse(User.objects.get(pk=self.operator.pk).has_perm("ipam.view_prices"))

        finance = Group.objects.get(name="Moliya bo'limi")
        self.client.post(url, {"action": "user_roles", "user": self.operator.pk, "groups": [finance.pk]})
        self.assertEqual(list(User.objects.get(pk=self.operator.pk).groups.all()), [finance])

    def test_access_page_requires_permission(self):
        self.client.force_login(self.finance)
        self.assertEqual(self.client.get(reverse("ipam:access_control")).status_code, 403)
        resp = self.client.post(reverse("ipam:access_control"), {"action": "user_prices", "user": self.finance.pk, "enabled": "1"})
        self.assertEqual(resp.status_code, 403)


class RegionScopeTests(TestCase):
    """Foydalanuvchi faqat o'ziga biriktirilgan viloyat ma'lumotlari bilan ishlaydi."""

    def setUp(self):
        self.sam_branch = make_branch()  # Samarqand / Urgut
        self.bux_branch = make_branch("Buxoro viloyati", "G'ijduvon tumani", "G'ijduvon filiali")
        self.sam = self.sam_branch.district.region
        self.bux = self.bux_branch.district.region
        self.sam_subnet = Subnet.objects.create(network="10.1.0.0/24", name="Urgut LAN", branch=self.sam_branch)
        self.bux_subnet = Subnet.objects.create(network="10.2.0.0/24", name="G'ijduvon LAN", branch=self.bux_branch)
        self.shared = Subnet.objects.create(network="10.9.0.0/24", name="Umumiy")
        self.sam_ip = IPAddress.objects.create(subnet=self.sam_subnet, address="10.1.0.5", branch=self.sam_branch, hostname="urgut-pc")
        self.bux_ip = IPAddress.objects.create(subnet=self.bux_subnet, address="10.2.0.5", branch=self.bux_branch, hostname="gijduvon-pc")
        IPAddress.objects.create(subnet=self.shared, address="10.9.0.10", branch=self.sam_branch, hostname="shared-urgut")
        IPAddress.objects.create(subnet=self.shared, address="10.9.0.20", branch=self.bux_branch, hostname="shared-gijduvon")
        Device.objects.create(name="urgut-sw", branch=self.sam_branch)
        Device.objects.create(name="gijduvon-sw", branch=self.bux_branch)

        self.user = User.objects.create_user("samarqand_op", password="test-parol-123")
        self.user.groups.add(Group.objects.get(name="Tarmoq operatori"))
        profile = UserProfile.objects.create(user=self.user)
        profile.regions.add(self.sam)
        self.client.force_login(self.user)

    def test_lists_show_only_own_region(self):
        resp = self.client.get(reverse("ipam:ip_list"))
        self.assertContains(resp, "urgut-pc")
        self.assertContains(resp, "shared-urgut")
        self.assertNotContains(resp, "gijduvon")
        resp = self.client.get(reverse("ipam:device_list"))
        self.assertContains(resp, "urgut-sw")
        self.assertNotContains(resp, "gijduvon-sw")
        resp = self.client.get(reverse("ipam:branch_list"))
        self.assertContains(resp, "Urgut filiali")
        self.assertNotContains(resp, "G&#x27;ijduvon filiali")
        resp = self.client.get(reverse("ipam:region_list"))
        self.assertContains(resp, "Samarqand viloyati")
        self.assertNotContains(resp, "Buxoro viloyati")
        resp = self.client.get(reverse("ipam:subnet_list"))
        self.assertContains(resp, "10.1.0.0/24")
        self.assertContains(resp, "10.9.0.0/24")  # umumiy subnet ko'rinadi
        self.assertNotContains(resp, "10.2.0.0/24")
        csv_text = self.client.get(reverse("ipam:ip_list"), {"export": "csv"}).content.decode("utf-8-sig")
        self.assertIn("urgut-pc", csv_text)
        self.assertNotIn("gijduvon", csv_text)
        resp = self.client.get(reverse("ipam:dashboard"))
        self.assertContains(resp, "Sizning hududlaringiz")

    def test_other_region_objects_are_not_found(self):
        for url in [
            self.bux_branch.get_absolute_url(), self.bux_subnet.get_absolute_url(), self.bux.get_absolute_url(),
            reverse("ipam:ip_update", args=[self.bux_subnet.pk, self.bux_ip.pk]),
            reverse("ipam:ip_delete", args=[self.bux_subnet.pk, self.bux_ip.pk]),
            reverse("ipam:ip_create", args=[self.bux_subnet.pk]),
            reverse("ipam:branch_update", args=[self.bux_branch.pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.get(reverse("ipam:ip_update", args=[self.sam_subnet.pk, self.sam_ip.pk])).status_code, 200)

    def test_shared_subnet_hides_foreign_ips(self):
        resp = self.client.get(self.shared.get_absolute_url())
        self.assertContains(resp, "shared-urgut")
        self.assertNotContains(resp, "shared-gijduvon")
        self.assertContains(resp, "cell-foreign")
        self.assertContains(resp, "yana 1 ta IP")
        # Umumiy subnetni o'zgartirib bo'lmaydi
        self.assertEqual(self.client.get(reverse("ipam:subnet_update", args=[self.shared.pk])).status_code, 404)

    def test_add_ip_only_into_own_region(self):
        url = reverse("ipam:ip_create", args=[self.shared.pk])
        resp = self.client.post(url, {"address": "10.9.0.30", "status": "used", "branch": self.bux_branch.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["form"].errors["branch"])
        resp = self.client.post(url, {"address": "10.9.0.30", "status": "used"})
        self.assertTrue(resp.context["form"].errors["branch"])  # filial majburiy
        resp = self.client.post(url, {"address": "10.9.0.30", "status": "used", "branch": self.sam_branch.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(IPAddress.objects.get(address="10.9.0.30").branch, self.sam_branch)
        # O'z IP'sini o'zgartira oladi
        resp = self.client.post(reverse("ipam:ip_update", args=[self.sam_subnet.pk, self.sam_ip.pk]), {
            "address": "10.1.0.5", "status": "reserved", "branch": self.sam_branch.pk,
        })
        self.assertEqual(resp.status_code, 302)
        self.sam_ip.refresh_from_db()
        self.assertEqual(self.sam_ip.status, "reserved")

    def test_form_choices_limited(self):
        form = self.client.get(reverse("ipam:ip_create", args=[self.shared.pk])).context["form"]
        self.assertEqual(list(form.fields["region"].queryset), [self.sam])
        self.assertEqual(list(form.fields["branch"].queryset), [self.sam_branch])
        resp = self.client.post(reverse("ipam:subnet_create"), {"network": "10.50.0.0/24", "name": "X"})
        self.assertTrue(resp.context["form"].errors["branch"])
        self.assertEqual(self.client.get(reverse("ipam:region_create")).status_code, 403)

    def test_user_without_regions_sees_nothing(self):
        self.user.profile.regions.clear()
        resp = self.client.get(reverse("ipam:ip_list"))
        self.assertNotContains(resp, "urgut-pc")
        self.assertContains(self.client.get(reverse("ipam:dashboard")), "birorta viloyat biriktirilmagan")

    def test_all_regions_flag(self):
        self.user.profile.all_regions = True
        self.user.profile.save()
        resp = self.client.get(reverse("ipam:ip_list"))
        self.assertContains(resp, "urgut-pc")
        self.assertContains(resp, "gijduvon-pc")

    def test_admin_assigns_regions(self):
        admin = User.objects.create_superuser("boss", password="test-parol-123")
        self.client.force_login(admin)
        resp = self.client.post(reverse("ipam:user_access", args=[self.user.pk]), {
            "groups": [Group.objects.get(name="Tarmoq operatori").pk],
            "regions": [self.sam.pk, self.bux.pk], "is_active": "on",
        })
        self.assertRedirects(resp, reverse("ipam:access_control"))
        self.assertEqual(set(self.user.profile.regions.all()), {self.sam, self.bux})
        log = AuditLog.objects.filter(action="access").latest("pk")
        self.assertEqual(log.object_repr, "samarqand_op")
        self.assertEqual(log.changes["Viloyatlar"], ["Samarqand viloyati", "Buxoro viloyati, Samarqand viloyati"])


class AuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="test-parol-123")
        self.client.force_login(self.admin)
        self.subnet = Subnet.objects.create(network="192.168.5.0/24", name="LAN")

    def test_create_update_delete_are_logged(self):
        self.client.post(reverse("ipam:ip_create", args=[self.subnet.pk]), {"address": "192.168.5.10", "status": "used", "hostname": "pc-1"})
        ip = IPAddress.objects.get()
        log = AuditLog.objects.get(action="create", model_name="IP manzil")
        self.assertEqual(log.user, self.admin)
        self.assertEqual(log.object_repr, "192.168.5.10")
        self.assertEqual(log.changes["Hostname"], ["", "pc-1"])
        self.assertEqual(log.ip_address, "127.0.0.1")

        self.client.post(reverse("ipam:ip_update", args=[self.subnet.pk, ip.pk]), {"address": "192.168.5.10", "status": "reserved", "hostname": "pc-2"})
        log = AuditLog.objects.get(action="update")
        self.assertEqual(log.changes["Holati"], ["Band", "Zaxirada"])
        self.assertEqual(log.changes["Hostname"], ["pc-1", "pc-2"])
        self.assertNotIn("Yangilangan", log.changes)

        self.client.post(reverse("ipam:ip_delete", args=[self.subnet.pk, ip.pk]))
        log = AuditLog.objects.get(action="delete")
        self.assertEqual(log.object_repr, "192.168.5.10")

        resp = self.client.get(reverse("ipam:audit_list"))
        self.assertContains(resp, "O&#x27;chirdi")
        self.assertContains(resp, "pc-2")
        resp = self.client.get(reverse("ipam:audit_list"), {"action": "update"})
        self.assertContains(resp, "Zaxirada")
        self.assertNotContains(resp, "O&#x27;chirdi</span>")

    def test_login_logout_and_failed_login(self):
        self.client.logout()
        self.client.post(reverse("login"), {"username": "admin", "password": "noto'g'ri"})
        self.assertTrue(AuditLog.objects.filter(action="login_failed", username="admin").exists())
        self.client.post(reverse("login"), {"username": "admin", "password": "test-parol-123"})
        self.assertTrue(AuditLog.objects.filter(action="login", user=self.admin).exists())
        # last_login yangilanishi "o'zgartirdi" sifatida yozilmaydi
        self.assertFalse(AuditLog.objects.filter(action="update", model_name="Foydalanuvchi").exists())
        self.client.post(reverse("logout"))
        self.assertTrue(AuditLog.objects.filter(action="logout", user=self.admin).exists())

    def test_export_is_logged(self):
        self.client.get(reverse("ipam:ip_list"), {"export": "pdf"})
        log = AuditLog.objects.get(action="export")
        self.assertEqual(log.object_repr, "IP manzillar ro'yxati")
        self.assertEqual(log.changes["Format"], ["", "PDF"])

    def test_audit_page_only_for_admins(self):
        op = User.objects.create_user("op", password="test-parol-123")
        op.groups.add(Group.objects.get(name="Tarmoq operatori"))
        self.client.force_login(op)
        self.assertEqual(self.client.get(reverse("ipam:audit_list")).status_code, 403)
        adm = User.objects.create_user("adm", password="test-parol-123")
        adm.groups.add(Group.objects.get(name="Administrator"))
        self.client.force_login(adm)
        self.assertEqual(self.client.get(reverse("ipam:audit_list")).status_code, 200)


class OnlineStatusTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="test-parol-123")
        self.op = User.objects.create_user("operator", password="test-parol-123")

    def test_online_after_activity_offline_after_logout(self):
        self.client.post(reverse("login"), {"username": "operator", "password": "test-parol-123"})
        self.client.get(reverse("ipam:dashboard"))
        self.op.refresh_from_db()
        self.assertTrue(self.op.profile.is_online)
        self.client.post(reverse("logout"))
        self.op.profile.refresh_from_db()
        self.assertFalse(self.op.profile.is_online)

    def test_inactive_for_long_is_offline(self):
        UserProfile.objects.create(user=self.op, is_logged_in=True,
                                   last_seen=timezone.now() - timedelta(minutes=10))
        self.assertFalse(self.op.profile.is_online)

    def test_access_page_shows_status(self):
        UserProfile.objects.create(user=self.op, is_logged_in=True, last_seen=timezone.now())
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("ipam:access_control"))
        self.assertContains(resp, "Onlayn")
        self.assertEqual(resp.context["online_count"], 2)  # admin (hozir) va operator
        resp = self.client.get(reverse("ipam:dashboard"))
        self.assertContains(resp, "Hozir onlayn")


class BackupTests(TransactionTestCase):
    # Zaxira nusxa alohida ulanish orqali o'qiydi — TestCase'ning ochiq tranzaksiyasi uni bloklab qo'yadi.
    # serialized_rollback: test tugagach migratsiyada qo'shilgan viloyat va rollarni qayta tiklaydi.
    serialized_rollback = True

    def test_backup_creates_valid_gzip_and_cleans_old(self):
        import gzip
        import os
        import sqlite3
        import tempfile
        from io import StringIO
        from pathlib import Path

        from django.core.management import call_command

        Subnet.objects.create(network="172.16.0.0/24", name="Zaxira testi")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            old = tmp / "ipam_2020-01-01_00-00-00.sqlite3.gz"
            old.write_bytes(b"eski")
            os.utime(old, (0, 0))  # 1970-yil — albatta eski
            unrelated = tmp / "boshqa-fayl.txt"
            unrelated.write_text("tegilmasin")

            out = StringIO()
            call_command("backup_db", dir=str(tmp), keep=30, stdout=out)
            self.assertIn("Zaxira nusxa olindi", out.getvalue())
            backups = list(tmp.glob("ipam_*.sqlite3.gz"))
            self.assertEqual(len(backups), 1)  # eskisi o'chirildi
            self.assertTrue(unrelated.exists())

            # Nusxa haqiqiy SQLite bazasi va unda ma'lumot bor
            restored = tmp / "check.sqlite3"
            restored.write_bytes(gzip.decompress(backups[0].read_bytes()))
            db = sqlite3.connect(restored)
            names = [r[0] for r in db.execute("SELECT name FROM ipam_subnet")]
            db.close()
            self.assertIn("Zaxira testi", names)

            out = StringIO()
            call_command("backup_db", dir=str(tmp), list=True, stdout=out)
            self.assertIn(backups[0].name, out.getvalue())


class SettingsTests(TestCase):
    def test_env_helpers(self):
        from config import settings as s

        with mock.patch.dict("os.environ", {"X_BOOL": "Ha", "X_LIST": "a.uz, b.uz ,"}):
            self.assertTrue(s.env_bool("X_BOOL"))
            self.assertFalse(s.env_bool("X_MISSING"))
            self.assertEqual(s.env_list("X_LIST"), ["a.uz", "b.uz"])

    def test_secret_key_required_in_production(self):
        import subprocess
        import sys
        from pathlib import Path

        from django.conf import settings

        env = {k: v for k, v in __import__("os").environ.items() if not k.startswith(("DJANGO_", "DB_"))}
        env.update(DJANGO_DEBUG="False", DJANGO_SECRET_KEY="", DJANGO_SETTINGS_MODULE="config.settings")
        code = "import django; django.setup()"
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(settings.BASE_DIR), env=env,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)


