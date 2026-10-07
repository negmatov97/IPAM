# IPAM

Django'da yozilgan IP manzillarni boshqarish tizimi.

Tuzilma: **Viloyat → Tuman → Filial → Qurilma → IP manzil**. Bundan tashqari subnetlar va VLAN'lar.
O'zbekistonning 14 ta hududi migratsiya orqali avtomatik qo'shiladi.

Imkoniyatlar:
- viloyatlar kesimidagi bosh sahifa (dashboard)
- har bir filial va qurilma uchun alohida sahifa
- barcha IP'lar ro'yxati: viloyat, tuman, filial, qurilma turi va holat bo'yicha filtr
- ro'yxatlarni Word (.docx), PDF va Excel (CSV) formatida yuklab olish (tanlangan filtrlar bilan)
- subnetdagi IP'larni rangli to'r ko'rinishida ko'rish
- **Narxlar (prays-list):** VLAN turi × viloyat kesimida tariflar, formula:
  `oylik = tezlik (Mbit/s) × (asosiy narx + ⌈(masofa − asosiy masofa) / qadam⌉ × qadam narxi)`;
  "kanal uchun" qat'iy narx, yillik chegirma, narx kalkulyatori; narx o'zgarishlari tarixi bilan saqlanadi
- **Rollar (RBAC):** Administrator, Moliya bo'limi, Tarmoq operatori; narxlarni ko'rishni rol yoki
  foydalanuvchi darajasida yoqish/o'chirish ("Rollar va huquqlar" sahifasi)
- **Hudud bo'yicha cheklash:** foydalanuvchiga viloyat(lar) biriktiriladi — u faqat shu viloyat IP manzillari,
  filiallari, qurilmalari va ijaralarini ko'radi, qo'shadi va o'zgartiradi (`ipam/scoping.py`).
  Viloyat biriktirilmagan yangi foydalanuvchi hech narsani ko'rmaydi
- **Harakatlar qaydi:** har bir qo'shish/o'zgartirish/o'chirish (eski → yangi qiymat), kirish/chiqish,
  muvaffaqiyatsiz kirish urinishlari, hisobot yuklashlar va huquq o'zgarishlari (`ipam/audit.py`)
- **Onlayn holat:** oxirgi 5 daqiqada faol bo'lgan foydalanuvchilar onlayn ko'rinadi
- **VLAN ijaralari:** shartnoma, oylik yoki yillik to'lov davri, maxsus narx, to'lovlar,
  hisoblangan summa va qarzdorlik avtomatik hisoblanadi; har bir ijara bo'yicha hisob-kitob hujjati

## Ishga tushirish

```powershell
.\.venv\Scripts\activate
python manage.py runserver
```

So'ng brauzerda http://127.0.0.1:8000 ni oching.

## Birinchi marta sozlash

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
```

## Testlar

```powershell
python manage.py test ipam
```

## Tuzilishi

- `ipam/models.py` — VLAN, Subnet, IPAddress modellari va tekshiruvlar
- `ipam/views.py` — sahifalar
- `ipam/templates/` — HTML shablonlar
- `/admin/` — Django admin panel
# IPAM
