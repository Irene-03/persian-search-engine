# دستورالعمل Push به GitHub

## مرحله 1: ساخت Repository در GitHub

1. به https://github.com بروید
2. با این اطلاعات وارد شوید:
   - Email: arefeh.za1382@gmail.com
   - Password: az.ma.1382

3. روی دکمه "+" در گوشه بالا سمت راست کلیک کنید
4. "New repository" را انتخاب کنید
5. اطلاعات زیر را وارد کنید:
   - Repository name: `search-engine-project`
   - Description: `Multi-phase search engine implementation - Phase 1: Web Crawler`
   - Public یا Private (به انتخاب شما)
   - **DON'T** initialize with README (چون قبلاً داریم)
6. روی "Create repository" کلیک کنید

## مرحله 2: Push کردن پروژه

پس از ساخت repository، این دستورات را در PowerShell اجرا کنید:

```powershell
cd "d:\B - University\7-search engine\EX1-crawler"

# اضافه کردن remote
git remote add origin https://github.com/[USERNAME]/search-engine-project.git

# Push کردن
git push -u origin master
```

زمانی که از شما username و password خواست:
- Username: arefeh.za1382@gmail.com
- Password: توکن GitHub (باید از GitHub ساخته شود)

## نکته مهم: ساخت Personal Access Token

از آنجایی که GitHub دیگر password مستقیم را قبول نمی‌کند، باید یک توکن بسازید:

1. Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate new token
3. انتخاب scope: `repo` (تمام دسترسی‌های repository)
4. این توکن را کپی کنید و به جای password استفاده کنید

## ساختار پیشنهادی برای فاز دوم

برای اضافه کردن فاز دوم در آینده، دو گزینه دارید:

### گزینه 1: Branch Strategy (پیشنهاد من)
```
master/main branch: فاز 1 (crawler)
phase2 branch: فاز 2 (search engine)
```

مزایا:
- تاریخچه واضح
- هر فاز مستقل
- merge آسان در صورت نیاز

### گزینه 2: Directory Structure
```
search-engine-project/
├── phase1-crawler/     (کد فعلی)
├── phase2-indexer/     (آینده)
└── phase2-searcher/    (آینده)
```

## دستورات مفید Git برای آینده

```bash
# برای شروع فاز دوم در branch جدید:
git checkout -b phase2

# برای merge فاز دوم به master:
git checkout master
git merge phase2

# برای ساخت tag برای هر فاز:
git tag -a v1.0-phase1 -m "Phase 1: Web Crawler Complete"
git push origin v1.0-phase1
```
