"""Zaxira nusxadan bazani tiklash.

    python manage.py restore_db backups/ipam_2026-10-07_02-00-00.sqlite3.gz
    python manage.py restore_db /var/backups/ipam/ipam_2026-10-07_02-00-00.dump

Tiklashdan oldin joriy baza avtomatik ravishda yana bir marta zaxiralanadi.
Muhim: tiklash vaqtida sayt to'xtatilgan bo'lishi kerak (systemctl stop ipam).
"""

import gzip
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Zaxira nusxadan ma'lumotlar bazasini tiklaydi."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Zaxira nusxa fayli (.sqlite3.gz yoki .dump)")
        parser.add_argument("--yes", action="store_true", help="Tasdiqlashni so'ramaslik")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"Fayl topilmadi: {path}")
        if not options["yes"]:
            answer = input(f"Joriy baza {path.name} nusxasi bilan ALMASHTIRILADI. Davom etilsinmi? [ha/yo'q]: ")
            if answer.strip().lower() not in ("ha", "h", "yes", "y"):
                self.stdout.write("Bekor qilindi.")
                return

        self.stdout.write("Avval joriy bazaning nusxasi olinmoqda...")
        call_command("backup_db", keep=0)

        vendor = connection.vendor
        connection.close()
        if vendor == "sqlite":
            if not path.name.endswith(".sqlite3.gz"):
                raise CommandError("SQLite uchun .sqlite3.gz fayl kerak.")
            self.restore_sqlite(path)
        elif vendor == "postgresql":
            if not path.name.endswith(".dump"):
                raise CommandError("PostgreSQL uchun .dump fayl kerak.")
            self.restore_postgres(path)
        else:
            raise CommandError(f"{vendor} bazasi qo'llab-quvvatlanmaydi.")
        self.stdout.write(self.style.SUCCESS(f"Baza tiklandi: {path.name}"))

    def restore_sqlite(self, path):
        db_path = str(connection.settings_dict["NAME"])
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "restore.sqlite3"
            with gzip.open(path, "rb") as src, open(snapshot, "wb") as out:
                shutil.copyfileobj(src, out)
            source = sqlite3.connect(snapshot)
            dest = sqlite3.connect(db_path, uri=db_path.startswith("file:"))
            try:
                if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise CommandError("Zaxira nusxa shikastlangan (integrity_check).")
                source.backup(dest)
            finally:
                source.close()
                dest.close()

    def restore_postgres(self, path):
        db = settings.DATABASES["default"]
        pg_restore = shutil.which("pg_restore")
        if not pg_restore:
            raise CommandError("pg_restore topilmadi. PostgreSQL client dasturini o'rnating.")
        env = {**os.environ, "PGPASSWORD": db.get("PASSWORD") or ""}
        cmd = [
            pg_restore, "--clean", "--if-exists", "--no-owner", "--single-transaction",
            "--host", db.get("HOST") or "localhost", "--port", str(db.get("PORT") or 5432),
            "--username", db.get("USER") or "", "--dbname", db["NAME"], str(path),
        ]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise CommandError(f"pg_restore xatosi: {result.stderr.strip()}")
