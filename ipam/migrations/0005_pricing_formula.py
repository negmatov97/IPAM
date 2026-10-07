from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def convert_old_tariffs(apps, schema_editor):
    """Eski tariflar qat'iy oylik narx edi: ularni "kanal uchun" narxga o'tkazamiz,
    yillik narxni esa chegirma foiziga aylantiramiz."""
    Tariff = apps.get_model("ipam", "Tariff")
    for t in Tariff.objects.all():
        t.unit = "channel"
        if t.yearly_price is not None and t.base_price:
            discount = (1 - Decimal(t.yearly_price) / (t.base_price * 12)) * 100
            t.yearly_discount = max(Decimal(0), min(Decimal(100), discount)).quantize(Decimal("0.01"))
        t.save()


class Migration(migrations.Migration):

    dependencies = [
        ("ipam", "0004_finance"),
    ]

    operations = [
        migrations.CreateModel(
            name="VLANType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True, verbose_name="Nomi")),
                ("description", models.TextField(blank=True, verbose_name="Tavsif")),
            ],
            options={"verbose_name": "VLAN turi", "verbose_name_plural": "VLAN turlari", "ordering": ["name"]},
        ),
        migrations.AddField(
            model_name="vlan",
            name="vlan_type",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="vlans",
                to="ipam.vlantype", verbose_name="VLAN turi",
                help_text="Ijara narxi shu tur tarifi bo'yicha hisoblanadi.",
            ),
        ),
        migrations.RemoveConstraint(model_name="tariff", name="unique_tariff_per_region_date"),
        migrations.RemoveConstraint(model_name="tariff", name="unique_default_tariff_date"),
        migrations.RenameField(model_name="tariff", old_name="monthly_price", new_name="base_price"),
        migrations.AddField(
            model_name="tariff",
            name="vlan_type",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="tariffs",
                to="ipam.vlantype", verbose_name="VLAN turi", help_text="Bo'sh qolsa — barcha turlar uchun.",
            ),
        ),
        migrations.AddField(
            model_name="tariff",
            name="unit",
            field=models.CharField(
                choices=[("mbps", "1 Mbit/s uchun"), ("channel", "Kanal uchun (tezlikdan qat'i nazar)")],
                default="mbps", max_length=10, verbose_name="Narx birligi",
            ),
        ),
        migrations.AddField(
            model_name="tariff",
            name="included_km",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Asosiy masofa (km gacha)"),
        ),
        migrations.AddField(
            model_name="tariff",
            name="step_km",
            field=models.DecimalField(decimal_places=2, default=1, max_digits=8, verbose_name="Qadam (har necha km)"),
        ),
        migrations.AddField(
            model_name="tariff",
            name="step_price",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="Qadam narxi (so'm)"),
        ),
        migrations.AddField(
            model_name="tariff",
            name="yearly_discount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name="Yillik to'lovda chegirma (%)"),
        ),
        migrations.RunPython(convert_old_tariffs, migrations.RunPython.noop),
        migrations.RemoveField(model_name="tariff", name="yearly_price"),
        migrations.AlterModelOptions(
            name="tariff",
            options={
                "ordering": ["-valid_from"],
                "permissions": [("view_prices", "VLAN ijara narxlarini ko'rish")],
                "verbose_name": "Tarif",
                "verbose_name_plural": "Narxlar (tariflar)",
            },
        ),
        migrations.AddField(
            model_name="vlanlease",
            name="bandwidth_mbps",
            field=models.DecimalField(decimal_places=2, default=1, max_digits=10, verbose_name="Tezlik (Mbit/s)"),
        ),
        migrations.AddField(
            model_name="vlanlease",
            name="distance_km",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Masofa (km)"),
        ),
    ]
