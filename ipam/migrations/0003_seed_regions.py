from django.db import migrations

# O'zbekiston hududlari (kodlar — ISO 3166-2:UZ)
REGIONS = [
    ("Toshkent shahri", "TK"),
    ("Qoraqalpog'iston Respublikasi", "QR"),
    ("Andijon viloyati", "AN"),
    ("Buxoro viloyati", "BU"),
    ("Farg'ona viloyati", "FA"),
    ("Jizzax viloyati", "JI"),
    ("Xorazm viloyati", "XO"),
    ("Namangan viloyati", "NG"),
    ("Navoiy viloyati", "NW"),
    ("Qashqadaryo viloyati", "QA"),
    ("Samarqand viloyati", "SA"),
    ("Sirdaryo viloyati", "SI"),
    ("Surxondaryo viloyati", "SU"),
    ("Toshkent viloyati", "TO"),
]


def seed_regions(apps, schema_editor):
    Region = apps.get_model("ipam", "Region")
    for name, code in REGIONS:
        Region.objects.get_or_create(name=name, defaults={"code": code})


def unseed_regions(apps, schema_editor):
    Region = apps.get_model("ipam", "Region")
    Region.objects.filter(name__in=[name for name, _ in REGIONS], districts__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ipam", "0002_locations_devices"),
    ]

    operations = [
        migrations.RunPython(seed_regions, unseed_regions),
    ]
