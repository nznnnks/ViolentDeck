# course_skateshop (Flask)

## Запуск (Windows / PowerShell)

1. Перейдите в папку проекта:

```powershell
cd E:\course_task
```

2. Активируйте виртуальное окружение:

```powershell
.\venv\Scripts\Activate.ps1
```

3. Установите зависимости:

```powershell
python -m pip install -r .\course_skateshop\requirements.txt
```

## PostgreSQL

Перед первым запуском создайте в PostgreSQL отдельную базу данных:

```sql
CREATE DATABASE course_skateshop;
```

Приложение само создаст внутри неё таблицу `users` при старте.

Настройки отправки писем лежат в `E:\course_task\course_skateshop\settings.py`.

4. Укажите строку подключения к PostgreSQL:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:ВАШ_ПАРОЛЬ@localhost:5432/course_skateshop"
```

5. При необходимости задайте секрет для сессий:

```powershell
$env:VIOLENTDECK_SECRET = "your-secret"
```

6. Запустите приложение:

```powershell
python .\course_skateshop\app.py
```

7. Откройте в браузере:

- `http://127.0.0.1:5000`

## Что создаётся автоматически

- таблица `users`
- стартовый пользователь `violent`
- поля подтверждения почты для новых аккаунтов

## Данные для входа после первого запуска

- Логин: `violent`
- Пароль: `deck123`
