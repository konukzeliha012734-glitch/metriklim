@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Metriklim calisma ortami bulunamadi.
  echo Lutfen kurulum adimlarini tamamlayin.
  pause
  exit /b 1
)
start "" "http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py --server.port 8501

