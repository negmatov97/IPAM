"""Ma'lumotlar bazasining zaxira nusxasini olish.

    python manage.py backup_db              # nusxa olish + eskilarini tozalash
    python manage.py backup_db --keep 60    # 60 kundan eski nusxalarni o'chirish
    python manage.py backup_db --list       # mavjud nusxalar ro'yxati

SQLite: ishlab turgan bazadan ham izchil nusxa olinadi (sqlite3 backup API) va gzip bilan siqiladi.
PostgreSQL: pg_dump (custom format, ichida siqilgan) — tiklash: pg_restore.
Fayl nomi: ipam_<sana>_<vaqt>.sqlite3.gz yoki .dump
"""

import gzip
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

PREFIX = "ipam_"
SUFFIXES = (".sqlite3.gz", ".dump")


def backup_files(directory):
    if not directory.exists():
        return []
    files = [p for p in directory.iterdir() if p.name.startswith(PREFIX) and p.name.endswith(SUFFIXES)]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


class Command(BaseCommand):
    help = "Ma'lumotlar bazasining zaxira nusxasini oladi va eski nusxalarni o'chiradi."

    def add_arguments(self, parser):
        parser.add_argument("--dir", help="Nusxalar papkasi (standart: settings.BACKUP_DIR)")
        parser.add_argument("--keep", type=int, help="Necha kunlik nusxalar saqlansin (standart: settings.BACKUP_KEEP_DAYS)")
        parser.add_argument("--list", action="store_true", help="Faqat mavjud nusxalarni ko'rsatish")

    def handle(self, *args, **options):
        directory = Path(options["dir"] or settings.BACKUP_DIR)
        keep_days = options["keep"] if options["keep"] is not None else settings.BACKUP_KEEP_DAYS

        if options["list"]:
            files = backup_files(directory)
            if not files:
                self.stdout.write("Zaxira nusxalar yo'q.")
            for f in files:
                size = f.stat().st_size / 1024 / 1024
                when = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                self.stdout.write(f"{when}  {size:8.2f} MB  {f}")
            return

        directory.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime().strftime("%Y-%m-%d_%H-%M-%S")
        vendor = connection.vendor
        if vendor == "sqlite":
            target = directory / f"{PREFIX}{stamp}.sqlite3.gz"
            self.backup_sqlite(target)
        elif vendor == "postgresql":
            target = directory / f"{PREFIX}{stamp}.dump"
            self.backup_postgres(target)
        else:
            raise CommandError(f"{vendor} bazasi uchun zaxira nusxa qo'llab-quvvatlanmaydi.")

        size = target.stat().st_size / 1024 / 1024
        self.stdout.write(self.style.SUCCESS(f"Zaxira nusxa olindi: {target} ({size:.2f} MB)"))

        removed = self.cleanup(directory, keep_days, current=target)
        if removed:
            self.stdout.write(f"{keep_days} kundan eski {removed} ta nusxa o'chirildi.")

    def backup_sqlite(self, target):
        db_path = str(connection.settings_dict["NAME"])
        source = sqlite3.connect(db_path, uri=db_path.startswith("file:"))
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.sqlite3"
            dest = sqlite3.connect(snapshot)
            try:
                # Baza ishlab turgan bo'lsa ham izchil nusxa
                source.backup(dest)
            finally:
                dest.close()
                source.close()
            with open(snapshot, "rb") as src, gzip.open(target, "wb", compresslevel=6) as out:
                shutil.copyfileobj(src, out)

    def backup_postgres(self, target):
        db = settings.DATABASES["default"]
        pg_dump = shutil.which("pg_dump")
        if not pg_dump:
            raise CommandError("pg_dump topilmadi. PostgreSQL client dasturini o'rnating (apt install postgresql-client).")
        env = {**os.environ, "PGPASSWORD": db.get("PASSWORD") or ""}
        cmd = [
            pg_dump, "--format=custom", "--no-owner", "--file", str(target),
            "--host", db.get("HOST") or "localhost", "--port", str(db.get("PORT") or 5432),
            "--username", db.get("USER") or "", db["NAME"],
        ]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            target.unlink(missing_ok=True)
            raise CommandError(f"pg_dump xatosi: {result.stderr.strip()}")

    def cleanup(self, directory, keep_days, current):
        if keep_days <= 0:
            return 0
        limit = timezone.now().timestamp() - timedelta(days=keep_days).total_seconds()
        removed = 0
        for f in backup_files(directory):
            # Eng oxirgi nusxa har doim qoladi
            if f != current and f.stat().st_mtime < limit:
                f.unlink()
                removed += 1
        return removed
