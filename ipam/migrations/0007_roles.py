from django.db import migrations

NETWORK_MODELS = ["region", "district", "branch", "device", "subnet", "ipaddress", "vlan"]
FINANCE_MODELS = ["vlantype", "tariff", "vlanlease", "payment"]
ALL_ACTIONS = ["view", "add", "change", "delete"]

ROLES = {
    "Administrator": {
        "ipam": [f"{a}_{m}" for m in NETWORK_MODELS + FINANCE_MODELS for a in ALL_ACTIONS] + ["view_prices"],
        "auth": ["view_user", "add_user", "change_user", "view_group", "change_group"],
    },
    "Moliya bo'limi": {
        "ipam": [f"{a}_{m}" for m in FINANCE_MODELS for a in ALL_ACTIONS]
        + [f"view_{m}" for m in NETWORK_MODELS]
        + ["view_prices"],
    },
    "Tarmoq operatori": {
        "ipam": [f"{a}_{m}" for m in NETWORK_MODELS for a in ALL_ACTIONS] + ["view_vlantype", "view_vlanlease"],
    },
}


def create_roles(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    # Ruxsatlar odatda migratsiyadan keyin yaratiladi — bu yerda oldindan yaratib olamiz
    for label in ("auth", "ipam"):
        app_config = apps.get_app_config(label)
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for role, perms in ROLES.items():
        group, _ = Group.objects.get_or_create(name=role)
        for app_label, codenames in perms.items():
            group.permissions.add(
                *Permission.objects.filter(content_type__app_label=app_label, codename__in=codenames)
            )


def remove_roles(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("ipam", "0006_pricing_field_details"),
    ]

    operations = [
        migrations.RunPython(create_roles, remove_roles),
    ]
