# course_skateshop (Flask)

## Запуск (Windows / PowerShell)

1) Перейдите в папку проекта:

```powershell
cd e:\course_task
```

2) Активируйте виртуальное окружение:

```powershell
.\venv\Scripts\Activate.ps1
```

3) Установите зависимости:

```powershell
python -m pip install -r .\course_skateshop\requirements.txt
```

4) Запустите приложение:

```powershell
python .\course_skateshop\app.py
```

5) Откройте в браузере:

- `http://127.0.0.1:5000`

## Данные для входа

- Логин: `violent`
- Пароль: `deck123`

## Опционально

- Секрет для сессий (если нужно заменить дефолтный):

```powershell
$env:VIOLENTDECK_SECRET = "your-secret"
python .\course_skateshop\app.py
```

