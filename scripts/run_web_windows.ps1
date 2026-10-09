$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
Start-Process "http://127.0.0.1:8765"
& .\.venv\Scripts\urt.exe web --host 127.0.0.1 --port 8765
