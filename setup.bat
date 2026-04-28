@echo off
:: =============================================================================
:: Campus Eye — Windows Setup Script
:: Run once after cloning to prepare the development environment.
::
:: Usage:
::   setup.bat          — CPU mode (default)
::   setup.bat --gpu    — GPU mode (installs onnxruntime-gpu instead of CPU)
::
:: Requirements (must be pre-installed and on PATH):
::   • Python 3.10 – 3.11  (https://www.python.org/downloads/)
::   • Git                  (https://git-scm.com/)
::   • Docker Desktop       (https://www.docker.com/products/docker-desktop/)
::     OR a local PostgreSQL + Redis installation
:: =============================================================================
setlocal EnableDelayedExpansion

:: ── Parse arguments ──────────────────────────────────────────────────────────
set "GPU_MODE=false"
for %%A in (%*) do (
    if /I "%%A"=="--gpu" set "GPU_MODE=true"
)

:: ── Banner ───────────────────────────────────────────────────────────────────
echo.
echo  +===========================================+
echo  ^|      Campus Eye -- Windows Setup          ^|
echo  +===========================================+
echo.

:: ── 1. Python version check ──────────────────────────────────────────────────
echo [1/8] Checking Python version...

where python >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found on PATH.
    echo         Download it from https://www.python.org/downloads/
    echo         Make sure "Add Python to PATH" is checked during install.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do set "PY_VER=%%V"
echo  Using Python %PY_VER%

:: Extract major.minor
for /f "tokens=1,2 delims=." %%A in ("%PY_VER%") do (
    set "PY_MAJOR=%%A"
    set "PY_MINOR=%%B"
)

if %PY_MAJOR% LSS 3 (
    echo  [ERROR] Python 3.10 or higher is required.
    pause
    exit /b 1
)
if %PY_MINOR% LSS 10 (
    echo  [ERROR] Python 3.10 or higher is required. Found: %PY_VER%
    pause
    exit /b 1
)
if %PY_MINOR% GEQ 12 (
    echo  [INFO]  Python 3.12 detected -- using compatible package versions.
)

:: ── 2. Virtual environment ───────────────────────────────────────────────────
echo.
echo [2/8] Setting up virtual environment...

if not exist "venv\" (
    echo  Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo  Virtual environment already exists, skipping creation.
)

echo  Activating venv...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo  [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)
echo  Active Python: %VIRTUAL_ENV%

:: ── 3. Upgrade pip ───────────────────────────────────────────────────────────
echo.
echo [3/8] Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo  [WARNING] pip upgrade failed, continuing with existing version.
)

:: ── 4. Install Python dependencies ───────────────────────────────────────────
echo.
echo [4/8] Installing Python dependencies (this may take several minutes)...

if "%GPU_MODE%"=="true" (
    echo  GPU mode: substituting onnxruntime-gpu for onnxruntime...
    :: Build a temporary requirements file with onnxruntime-gpu
    set "TMP_REQ=%TEMP%\campus_eye_req_gpu.txt"
    type nul > "!TMP_REQ!"
    for /f "usebackq delims=" %%L in ("requirements.txt") do (
        set "LINE=%%L"
        if /I "!LINE!"=="onnxruntime" (
            echo onnxruntime-gpu>> "!TMP_REQ!"
        ) else (
            echo !LINE!>> "!TMP_REQ!"
        )
    )
    pip install --no-cache-dir --timeout 120 -r "!TMP_REQ!"
) else (
    echo  CPU mode (default).
    pip install --no-cache-dir --timeout 120 -r requirements.txt
)

if errorlevel 1 (
    echo.
    echo  [ERROR] Dependency installation failed.
    echo         Check error messages above and ensure you have a working
    echo         internet connection. Some packages (e.g. insightface,
    echo         mediapipe) require Visual C++ Build Tools on Windows:
    echo         https://visualstudio.microsoft.com/visual-cpp-build-tools/
    pause
    exit /b 1
)
echo  Dependencies installed successfully.

:: ── 5. Environment file ──────────────────────────────────────────────────────
echo.
echo [5/8] Configuring environment file...

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo  Copied .env.example -> .env
        echo  [ACTION REQUIRED] Edit .env with your credentials before running.
    ) else (
        echo  [WARNING] .env.example not found. Create a .env file manually.
    )
) else (
    echo  .env already exists, skipping.
)

:: ── 6. Create media directories ──────────────────────────────────────────────
echo.
echo [6/8] Creating media directories...

if not exist "media\snapshots\" mkdir "media\snapshots"
if not exist "media\clips\"     mkdir "media\clips"
if not exist "media\photos\"    mkdir "media\photos"
if not exist "models\"          mkdir "models"
echo  Directories ready: media\snapshots, media\clips, media\photos, models

:: ── 7. Download YOLO models ──────────────────────────────────────────────────
echo.
echo [7/8] Downloading detection models...

python scripts\download_models.py
if errorlevel 1 (
    echo  [WARNING] Model download failed. You can retry later with:
    echo            python scripts\download_models.py
)

:: ── 8. Database migrations ───────────────────────────────────────────────────
echo.
echo [8/8] Running database migrations...
echo  Make sure PostgreSQL is running and DATABASE_URL in .env is correct.

if exist ".env" (
    :: Load .env variables into the current session
    for /f "usebackq tokens=1,* delims==" %%K in (".env") do (
        set "LINE=%%K"
        if not "!LINE:~0,1!"=="#" if not "!LINE!"=="" (
            set "%%K=%%L"
        )
    )
)

alembic upgrade head
if errorlevel 1 (
    echo  [WARNING] Migration failed -- is PostgreSQL running?
    echo           You can retry later with: alembic upgrade head
) else (
    echo  Migrations applied successfully.
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo  +============================================================+
echo  ^|  Setup complete!                                           ^|
echo  ^|                                                            ^|
echo  ^|  Next steps:                                               ^|
echo  ^|  1. Edit .env with your DB / Redis / SMTP / Discord creds  ^|
echo  ^|  2. Start Redis + PostgreSQL:                              ^|
echo  ^|        docker compose up -d                                ^|
echo  ^|  3. Run the API server:                                    ^|
echo  ^|        venv\Scripts\uvicorn app.main:app --reload          ^|
echo  ^|  4. Run the Celery worker (new terminal):                  ^|
echo  ^|        venv\Scripts\celery -A app.alerts.celery_app        ^|
echo  ^|               worker --loglevel=info --pool=solo           ^|
echo  ^|     (--pool=solo is recommended on Windows)                ^|
echo  ^|  5. Open browser: http://localhost:9000                    ^|
echo  +============================================================+
echo.

pause
endlocal
