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
echo Creating database tables...
python -m app.seed
if errorlevel 1 ( echo ERROR: database setup failed. & pause & exit /b 1 )

echo.
echo ==============================================
echo  Setup complete. Run  run.bat  to start,
echo  then open http://localhost:8000 and sign up.
echo  The first account you create becomes the admin.
echo ==============================================
pause
