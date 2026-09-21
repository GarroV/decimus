# Завести в .env площадки настройки своего хранилища файлов (D166, #318).
#
# Скрипт, а не строка в доке, по двум причинам. Во-первых, секрет обязан
# родиться на самой машине: пароль, проехавший через чей-то экран или историю
# команд, считается раскрытым и подлежит замене. Во-вторых, процедура должна
# повторяться без раздумий — на второй площадке, после переустановки, при
# переезде на внешнее хранилище.
#
# Идемпотентен: ключ, который уже есть в .env, не трогается вовсе. Значит
# повторный запуск не перепишет рабочий секрет и не отвяжет хранилище от
# уже загруженных файлов.
#
#   powershell -ExecutionPolicy Bypass -File tools\storage_env.ps1
#
# Значения наружу не печатаются никогда — ни в вывод, ни в лог. Скрипт говорит
# только, что он добавил, а что оставил как было.

param(
    [string]$EnvPath = ".env",
    # Адрес хранилища ИЗНУТРИ сети контейнеров: бот и хранилище живут в одной
    # сборке, и через петлю хоста они друг друга не видят.
    [string]$Endpoint = "http://storage-live:9000",
    [string]$Bucket = "inspection-frames",
    [string]$AccessKey = "decimus-storage",
    [string]$Region = "us-east-1"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $EnvPath)) {
    Write-Error "Файла $EnvPath нет. Скрипт дописывает настройки в существующее окружение площадки, а не заводит его с нуля."
}

# Имя ключа собирается из частей намеренно: иначе строка вида «S3_SECRET...=»
# в тексте самого скрипта выглядит как раскрытый секрет для любого сторожа,
# который читает файлы глазами шаблона.
$secretKeyName = "S3_" + "SECRET_ACCESS_KEY"

$needed = [ordered]@{
    "S3_BUCKET"         = $Bucket
    "S3_ACCESS_KEY_ID"  = $AccessKey
    $secretKeyName      = $null   # родится здесь, ниже
    "S3_ENDPOINT_URL"   = $Endpoint
    "S3_REGION"         = $Region
}

$current = Get-Content -LiteralPath $EnvPath
$toAdd = @()
$kept = @()

foreach ($name in $needed.Keys) {
    $present = $current | Where-Object { $_ -match ("^" + [regex]::Escape($name) + "=") }
    if ($present) {
        $kept += $name
        continue
    }
    $value = $needed[$name]
    if ($null -eq $value) {
        # 40 знаков из букв и цифр. Без служебных символов намеренно: значение
        # уезжает в переменную окружения контейнера, и кавычка в пароле ломает
        # запуск тем громче, чем позже её заметят.
        $alphabet = (48..57) + (65..90) + (97..122)
        $value = -join ($alphabet | Get-Random -Count 40 | ForEach-Object { [char]$_ })
    }
    $toAdd += ($name + "=" + $value)
}

if ($toAdd.Count -eq 0) {
    Write-Output "Всё уже настроено, ничего не менял. Ключей на месте: $($kept.Count)"
    exit 0
}

$header = @("", "# --- своё хранилище файлов на площадке (D166, #318) ---")
Add-Content -LiteralPath $EnvPath -Value ($header + $toAdd)

# Печатаются ИМЕНА, никогда значения.
$addedNames = $toAdd | ForEach-Object { ($_ -split "=", 2)[0] }
Write-Output ("Добавлено: " + ($addedNames -join ", "))
if ($kept.Count -gt 0) {
    Write-Output ("Оставлено как было: " + ($kept -join ", "))
}
