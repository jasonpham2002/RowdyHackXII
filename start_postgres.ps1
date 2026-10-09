# Start the local PostgreSQL used by the room server.
# Docker is the other option: docker compose up -d
$root = Join-Path $env:LOCALAPPDATA "blinkchilling-postgres"
$pgCtl = Join-Path $root "pgsql\bin\pg_ctl.exe"
$data = Join-Path $root "data"
$log = Join-Path $root "postgres.log"

if (-not (Test-Path $pgCtl) -or -not (Test-Path (Join-Path $data "PG_VERSION"))) {
    Write-Error "Local PostgreSQL is not initialized. When Docker is available, run: docker compose up -d"
    exit 1
}

& $pgCtl -D $data status | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Output "PostgreSQL is already running."
    exit 0
}

& $pgCtl -D $data -l $log start
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
Write-Output "PostgreSQL is running."
