@echo off
:: =============================================================================
:: Campus Eye — Windows Uninstall Script
:: Removes the virtual environment, downloaded models, generated media,
:: Docker containers/volumes, and optionally the database.
::
:: Usage:
::   uninstall.bat              — interactive (asks before each step)
::   uninstall.bat --all        — remove everything without prompting
::   uninstall.bat --keep-db    — remove everything except the database
::   uninstall.bat --dry-run    — show what WOULD be removed, do nothing
:: =============================================================================
setlocal EnableDelayedExpansion

:: ── Parse arguments ──────────────────────────────────────────────────────────
set "ALL=false"
set "KEEP_DB=false"
set "DRY_RUN=false"

for %%A in (%*) do (
    if /I "%%A"=="--all"      set "ALL=true"
    if /I "%%A"=="--keep-db"  set "KEEP_DB=true"
    if /I "%%A"=="--dry-run"  set "DRY_RUN=true"
)

:: ── Banner ───────────────────────────────────────────────────────────────────
echo.
echo  +==============================================+
echo  ^|    Campus Eye -- Windows Uninstall Script    ^|
echo  +==============================================+
echo.

if "%DRY_RUN%"=="true" (
    echo  [DRY RUN] Nothing will actually be deleted.
    echo.
)

:: ── Helper: confirm ──────────────────────────────────────────────────────────
:: Because batch can't define reusable functions cleanly with return values,
:: we use a goto-based subroutine. Callers set CONFIRM_QUESTION and check
:: CONFIRM_RESULT (YES / NO) after the call.

goto :main

:confirm
    if "%ALL%"=="true" (
        set "CONFIRM_RESULT=YES"
        goto :eof
    )
    set /p "CONFIRM_RESULT=  %CONFIRM_QUESTION% [y/N] "
    if /I "!CONFIRM_RESULT!"=="y"   set "CONFIRM_RESULT=YES" & goto :eof
    if /I "!CONFIRM_RESULT!"=="yes" set "CONFIRM_RESULT=YES" & goto :eof
    set "CONFIRM_RESULT=NO"
    goto :eof

:run_cmd
    :: %RUN_DESC% = description, remaining env CMD_LINE = command to run
    if "%DRY_RUN%"=="true" (
        echo  [dry-run] would run: %CMD_LINE%
        goto :eof
    )
    echo  %RUN_DESC%
    %CMD_LINE%
    if errorlevel 1 (
        echo  [WARNING] Command reported a non-zero exit code, continuing.
    )
    goto :eof

:remove_dir
    :: Uses REM_PATH and REM_DESC
    if "%DRY_RUN%"=="true" (
        echo  [dry-run] would remove directory: %REM_PATH%
        goto :eof
    )
    echo  Removing %REM_DESC%...
    rmdir /s /q "%REM_PATH%" 2>nul
    if errorlevel 1 (
        echo  [WARNING] Could not fully remove %REM_PATH%
    ) else (
        echo  Removed: %REM_PATH%
    )
    goto :eof

:main

:: ── 1. Stop Docker services ──────────────────────────────────────────────────
echo [Step 1/9] Docker containers
where docker >nul 2>&1
if not errorlevel 1 (
    if exist "docker-compose.yml" (
        set "CONFIRM_QUESTION=Stop and remove Docker containers?"
        call :confirm
        if "!CONFIRM_RESULT!"=="YES" (
            if "%DRY_RUN%"=="false" (
                echo  Stopping Docker containers...
                docker compose down
            ) else (
                echo  [dry-run] would run: docker compose down
            )

            if "%KEEP_DB%"=="false" (
                set "CONFIRM_QUESTION=Remove Docker volumes ^(DELETES ALL DATABASE DATA^)?"
                call :confirm
                if "!CONFIRM_RESULT!"=="YES" (
                    if "%DRY_RUN%"=="false" (
                        echo  Removing Docker volumes...
                        docker compose down --volumes --remove-orphans
                    ) else (
                        echo  [dry-run] would run: docker compose down --volumes --remove-orphans
                    )
                )
            ) else (
                echo  Keeping Docker volumes ^(--keep-db specified^).
            )
        )
    ) else (
        echo  No docker-compose.yml found -- skipping.
    )
) else (
    echo  Docker not found on PATH -- skipping.
)

:: ── 2. Drop local PostgreSQL database ───────────────────────────────────────
echo.
echo [Step 2/9] Local PostgreSQL database
if "%KEEP_DB%"=="false" (
    set "CONFIRM_QUESTION=Drop local PostgreSQL database 'campus_eye'? ^(only if running locally, not Docker^)"
    call :confirm
    if "!CONFIRM_RESULT!"=="YES" (
        where psql >nul 2>&1
        if not errorlevel 1 (
            if "%DRY_RUN%"=="false" (
                echo  Dropping database campus_eye...
                psql -U postgres -c "DROP DATABASE IF EXISTS campus_eye;" -c "DROP ROLE IF EXISTS campus_eye;"
                if errorlevel 1 (
                    echo  [WARNING] psql command failed. You may need to run this manually as the postgres user.
                )
            ) else (
                echo  [dry-run] would run: psql DROP DATABASE campus_eye + DROP ROLE campus_eye
            )
        ) else (
            echo  psql not found on PATH -- skipping local DB drop.
        )
    )
) else (
    echo  Skipping database removal ^(--keep-db specified^).
)

:: ── 3. Remove virtual environment ───────────────────────────────────────────
echo.
echo [Step 3/9] Python virtual environment
if exist "venv\" (
    set "CONFIRM_QUESTION=Remove Python virtual environment ^(.\venv^)?"
    call :confirm
    if "!CONFIRM_RESULT!"=="YES" (
        :: Deactivate first if we are inside venv
        if defined VIRTUAL_ENV call venv\Scripts\deactivate.bat 2>nul
        set "REM_PATH=venv"
        set "REM_DESC=virtual environment (venv\)"
        call :remove_dir
    )
) else (
    echo  No venv found -- skipping.
)

:: ── 4. Remove downloaded model weights ──────────────────────────────────────
echo.
echo [Step 4/9] Downloaded model weights
if exist "models\" (
    set "CONFIRM_QUESTION=Remove downloaded model weights ^(.\models^)?"
    call :confirm
    if "!CONFIRM_RESULT!"=="YES" (
        set "REM_PATH=models"
        set "REM_DESC=model weights (models\)"
        call :remove_dir
    )
) else (
    echo  No models directory found -- skipping.
)

:: Also remove any .pt files in the project root (yolov8*.pt etc.)
set "PT_FOUND=false"
for %%F in (*.pt) do set "PT_FOUND=true"
if "!PT_FOUND!"=="true" (
    set "CONFIRM_QUESTION=Remove YOLO .pt weight files in the project root?"
    call :confirm
    if "!CONFIRM_RESULT!"=="YES" (
        if "%DRY_RUN%"=="false" (
            del /q *.pt 2>nul
            echo  Removed .pt files from project root.
        ) else (
            echo  [dry-run] would delete *.pt from project root.
        )
    )
)

:: ── 5. Remove generated media files ─────────────────────────────────────────
echo.
echo [Step 5/9] Generated media files
if exist "media\" (
    set "CONFIRM_QUESTION=Remove generated media files ^(.\media -- snapshots, clips, photos^)?"
    call :confirm
    if "!CONFIRM_RESULT!"=="YES" (
        set "REM_PATH=media"
        set "REM_DESC=media directory (media\)"
        call :remove_dir
    )
) else (
    echo  No media directory found -- skipping.
)

:: ── 6. Remove .env file ──────────────────────────────────────────────────────
echo.
echo [Step 6/9] .env credentials file
if exist ".env" (
    set "CONFIRM_QUESTION=Remove .env file ^(contains credentials^)?"
    call :confirm
    if "!CONFIRM_RESULT!"=="YES" (
        if "%DRY_RUN%"=="false" (
            del /q ".env"
            echo  Removed .env
        ) else (
            echo  [dry-run] would delete .env
        )
    )
) else (
    echo  No .env file found -- skipping.
)

:: ── 7. Remove Python cache files ─────────────────────────────────────────────
echo.
echo [Step 7/9] Python cache files ^(__pycache__, .pyc, .pytest_cache^)
set "CONFIRM_QUESTION=Remove Python __pycache__ and .pyc files?"
call :confirm
if "!CONFIRM_RESULT!"=="YES" (
    if "%DRY_RUN%"=="false" (
        echo  Removing __pycache__ directories...
        for /d /r . %%D in (__pycache__) do (
            set "CACHE_DIR=%%D"
            :: Skip anything inside venv
            echo !CACHE_DIR! | findstr /i "\\venv\\" >nul 2>&1
            if errorlevel 1 rmdir /s /q "%%D" 2>nul
        )
        echo  Removing .pyc files...
        for /r . %%F in (*.pyc) do (
            set "PYC=%%F"
            echo !PYC! | findstr /i "\\venv\\" >nul 2>&1
            if errorlevel 1 del /q "%%F" 2>nul
        )
        if exist ".pytest_cache\" (
            rmdir /s /q ".pytest_cache" 2>nul
            echo  Removed .pytest_cache
        )
        echo  Python cache cleaned.
    ) else (
        echo  [dry-run] would remove all __pycache__ dirs and .pyc files (outside venv^).
    )
)

:: ── 8. Remove Ultralytics / YOLO cache ──────────────────────────────────────
echo.
echo [Step 8/9] Ultralytics / YOLO cache
set "YOLO_CACHE=%APPDATA%\Ultralytics"
if exist "%YOLO_CACHE%\" (
    set "CONFIRM_QUESTION=Remove Ultralytics/YOLO cache ^(%%APPDATA%%\Ultralytics^)?"
    call :confirm
    if "!CONFIRM_RESULT!"=="YES" (
        set "REM_PATH=%YOLO_CACHE%"
        set "REM_DESC=Ultralytics cache (%APPDATA%\Ultralytics)"
        call :remove_dir
    )
) else (
    echo  No Ultralytics cache found -- skipping.
)

:: ── 9. Remove InsightFace cache ──────────────────────────────────────────────
echo.
echo [Step 9/9] InsightFace model cache
set "INSIGHT_CACHE=%USERPROFILE%\.insightface"
if exist "%INSIGHT_CACHE%\" (
    set "CONFIRM_QUESTION=Remove InsightFace model cache ^(%%USERPROFILE%%\.insightface^)?"
    call :confirm
    if "!CONFIRM_RESULT!"=="YES" (
        set "REM_PATH=%INSIGHT_CACHE%"
        set "REM_DESC=InsightFace cache (%USERPROFILE%\.insightface)"
        call :remove_dir
    )
) else (
    echo  No InsightFace cache found -- skipping.
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
if "%DRY_RUN%"=="true" (
    echo  Dry run complete. No files were deleted.
) else (
    echo  +====================================================+
    echo  ^|  Campus Eye uninstall complete.                    ^|
    echo  ^|  Source code and config files have been kept.     ^|
    echo  ^|  To reinstall: setup.bat                          ^|
    echo  +====================================================+
)
echo.

pause
endlocal
