param(
    [int]$Port = 8000
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = Join-Path $repoRoot "..\venv\Scripts\python.exe"
}

if (-not (Test-Path $python)) {
    Write-Error "Python venv no encontrado en: $python"
    exit 1
}

Set-Location -Path $repoRoot
& $python manage.py runserver $Port
