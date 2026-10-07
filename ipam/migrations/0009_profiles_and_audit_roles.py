from django.conf import settings
from django.db import migrations


def setup(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    app_config = apps.get_app_config("ipam")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)

    # Mavjud foydalanuvchilar avvalgidek barcha hududlarni ko'rishda davom etadi.
    # Yangi foydalanuvchilarga esa viloyat aniq biriktirilishi kerak.
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    UserProfile = apps.get_model("ipam", "UserProfile")
    for user in User.objects.all():
        UserProfile.objects.get_or_create(user=user, defaults={"all_regions": True})

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    admin_group = Group.objects.filter(name="Administrator").first()
    if admin_group:
        admin_group.permissions.add(*Permission.objects.filter(
            content_type__app_label="ipam",
            codename__in=["view_auditlog", "view_userprofile", "change_userprofile"],
        ))


class Migration(migrations.Migration):

    dependencies = [
        ("ipam", "0008_users_audit"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(setup, migrations.RunPython.noop),
    ]
