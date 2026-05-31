@echo off
echo ==============================================
echo  CSSA Setup — first time only
echo ==============================================

python -m venv .venv
if errorlevel 1 ( echo ERROR: python not found. Install Python 3.11. & pause & exit /b 1 )

call .venv\Scripts\activate.bat

pip install -r requirements.txt
if errorlevel 1 ( echo ERROR: pip install failed. & pause & exit /b 1 )

echo.
echo Creating database and seeding demo data...
python -m app.seed
if errorlevel 1 ( echo ERROR: seed failed. & pause & exit /b 1 )

echo.
echo ==============================================
echo  Setup complete. Run  run.bat  to start.
echo ==============================================
pause
