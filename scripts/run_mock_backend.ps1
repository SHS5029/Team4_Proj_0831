param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$uvicorn = Join-Path $repoRoot ".venv\Scripts\uvicorn.exe"

if (-not (Test-Path -LiteralPath $uvicorn)) {
    throw "프로젝트 가상환경의 uvicorn을 찾을 수 없습니다: $uvicorn"
}

# 이 스크립트가 관리하는 Backend 포트의 LISTEN 프로세스만 종료한다.
# 다른 포트나 작업 중인 파일은 건드리지 않으며, 포트 충돌을 피하기 위한 목적이다.
$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
$processIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)

foreach ($processId in $processIds) {
    if ($processId -and $processId -ne $PID) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "기존 포트 $Port 프로세스 종료: $($process.ProcessName) (PID $processId)"
            Stop-Process -Id $processId
        }
    }
}

Start-Sleep -Milliseconds 500
$env:BACKEND_DATA_MODE = "mock"
Write-Host "mock Backend를 http://127.0.0.1:$Port 에서 시작합니다. 종료하려면 Ctrl+C를 누르세요."
& $uvicorn "backend.app.main:app" --host "127.0.0.1" --port $Port
