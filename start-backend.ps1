Set-Location "$PSScriptRoot\backend"
& ".\venv\Scripts\python.exe" -m uvicorn main:app --reload
