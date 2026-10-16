param([ValidateSet('api','worker','maintenance','web')][string]$Service = 'api')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONPATH = 'services/api'
switch ($Service) {
  'api' { & .venv/Scripts/python.exe -m uvicorn sentinel.api:app --host 127.0.0.1 --port 8010 }
  'worker' { & .venv/Scripts/python.exe -m sentinel.worker }
  'maintenance' { & .venv/Scripts/python.exe -m sentinel.maintenance }
  'web' { & npm run dev --prefix apps/web }
}
