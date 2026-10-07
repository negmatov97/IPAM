# IPAM'ni serverga o'rnatish (Ubuntu 22.04 / 24.04)

Tuzilma: **Nginx (HTTPS) → Gunicorn → Django → PostgreSQL**, har kuni avtomatik zaxira nusxa.
Barcha buyruqlar server terminalida, `sudo` huquqi bilan bajariladi.

## 1. Kerakli dasturlar

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx postgresql postgresql-client certbot python3-certbot-nginx
```

## 2. PostgreSQL bazasi

```bash
sudo -u postgres psql -c "CREATE USER ipam WITH PASSWORD 'KUCHLI-PAROL';"
sudo -u postgres psql -c "CREATE DATABASE ipam OWNER ipam ENCODING 'UTF8';"
```

## 3. Ilova foydalanuvchisi va kod

```bash
sudo useradd --system --create-home --home-dir /opt/ipam --shell /bin/bash ipam
sudo mkdir -p /var/log/ipam /var/backups/ipam
sudo chown ipam:ipam /var/log/ipam /var/backups/ipam
sudo chmod 750 /var/backups/ipam

sudo -u ipam git clone <REPOZITORIY_MANZILI> /opt/ipam
cd /opt/ipam
sudo -u ipam python3 -m venv .venv
sudo -u ipam .venv/bin/pip install -r requirements.txt
```

## 4. Sozlamalar (`.env`)

```bash
sudo -u ipam cp .env.example .env
sudo -u ipam chmod 600 .env
# Yangi maxfiy kalit:
.venv/bin/python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
sudo -u ipam nano .env
```

`.env` da albatta o'zgartiring: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS`, `DB_PASSWORD`. `DJANGO_DEBUG=False` bo'lishi shart.

## 5. Bazani tayyorlash

```bash
sudo -u ipam .venv/bin/python manage.py migrate
sudo -u ipam .venv/bin/python manage.py collectstatic --noinput
sudo -u ipam .venv/bin/python manage.py check --deploy
```

**Yangi o'rnatish bo'lsa** — administrator yarating:

```bash
sudo -u ipam .venv/bin/python manage.py createsuperuser
```

**Noutbukdagi ma'lumotlarni ko'chirish bo'lsa** (SQLite → PostgreSQL):

```bash
# 1) Noutbukda (loyiha papkasida):
python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.permission -e admin.logentry -e sessions --indent 2 -o ipam-data.json
# 2) Faylni serverga ko'chiring (scp yoki fleshka), so'ng serverda:
sudo -u ipam .venv/bin/python manage.py loaddata ipam-data.json
```

## 6. Gunicorn xizmati

```bash
sudo cp deploy/ipam.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ipam
sudo systemctl status ipam
```

## 7. Nginx va HTTPS

```bash
sudo cp deploy/nginx-ipam.conf /etc/nginx/sites-available/ipam
sudo nano /etc/nginx/sites-available/ipam      # ipam.example.uz -> o'z domeningiz
sudo ln -s /etc/nginx/sites-available/ipam /etc/nginx/sites-enabled/
sudo certbot --nginx -d ipam.example.uz         # bepul SSL sertifikat (internetdan ochiq domen uchun)
sudo nginx -t && sudo systemctl reload nginx
```

Agar server faqat ichki tarmoqda bo'lsa va Let's Encrypt ishlamasa — tashkilot IT bo'limidan
sertifikat oling va `ssl_certificate` yo'llarini o'zgartiring.

## 8. Har kunlik zaxira nusxa

```bash
sudo cp deploy/ipam-backup.service deploy/ipam-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ipam-backup.timer
sudo systemctl start ipam-backup.service        # hoziroq bir marta sinab ko'rish
sudo -u ipam .venv/bin/python manage.py backup_db --list
```

Nusxalar `/var/backups/ipam` da, 30 kun saqlanadi (`IPAM_BACKUP_KEEP_DAYS`).
**Tavsiya:** nusxalarni boshqa serverga yoki tarmoq diskiga ham ko'chirib turing (rsync) —
server diski ishdan chiqsa, nusxalar ham yo'qolmasin.

## Yangilash (yangi versiyani o'rnatish)

```bash
cd /opt/ipam
sudo -u ipam .venv/bin/python manage.py backup_db
sudo -u ipam git pull
sudo -u ipam .venv/bin/pip install -r requirements.txt
sudo -u ipam .venv/bin/python manage.py migrate
sudo -u ipam .venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart ipam
```

## Zaxira nusxadan tiklash

```bash
sudo systemctl stop ipam
sudo -u ipam .venv/bin/python manage.py restore_db /var/backups/ipam/ipam_YYYY-MM-DD_HH-MM-SS.dump
sudo systemctl start ipam
```

Tiklashdan oldin joriy baza avtomatik yana bir marta zaxiralanadi.

## Muammolarni aniqlash

| Qayerda | Buyruq |
|---|---|
| Ilova loglari | `tail -f /var/log/ipam/ipam.log` |
| Gunicorn | `sudo journalctl -u ipam -f` |
| Nginx | `tail -f /var/log/nginx/ipam.error.log` |
| Zaxira nusxa | `sudo journalctl -u ipam-backup` |
