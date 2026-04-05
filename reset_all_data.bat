@echo off
REM ============================================================
REM  YRCARKIT Data Reset Script
REM  Clears all charging cycle data, resets profiles to defaults
REM  Place this file in the YRCARKIT root folder and double-click
REM ============================================================

echo.
echo  ========================================
echo   YRCARKIT FULL DATA RESET
echo  ========================================
echo.
echo  This will:
echo    - Clear ALL charging cycle data (w_data)
echo    - Reset ALL profiles to factory defaults (w_work)
echo    - Reset DIY presets to factory defaults (w_work)
echo.

set /p CONFIRM="Are you sure? Type YES to continue: "
if /i not "%CONFIRM%"=="YES" (
    echo Cancelled. No changes made.
    pause
    exit /b
)

echo.
echo [1/3] Clearing charging cycle data...

REM Keep lxdata000 channel header, clear all others
set "DATADIR=%~dp0w_data"
if exist "%DATADIR%" (
    for /L %%i in (1,1,8) do (
        type nul > "%DATADIR%\lxdata00%%i.txt"
    )
    echo       Cleared lxdata001 through lxdata008
) else (
    echo       WARNING: w_data folder not found!
)

echo [2/3] Resetting all profiles to factory defaults...

set "WORKDIR=%~dp0w_work"
if exist "%WORKDIR%" (
    REM Default profile: mode=02(discharge), wait=0, chargeV=8.4, chargeA=5, dischargeV=5.4, dischargeA=5, step=0.20
    set "DEFAULT_PROFILE=,02,00.000,08.400,05.00,05.400,05.00,00.20"

    REM Reset lxprofession000
    echo ,02,00.000,08.400,05.00,05.400,05.00,00.20> "%WORKDIR%\lxprofession000.txt"

    REM Reset lxprofession001-099
    for /L %%i in (1,1,9) do (
        echo ,02,00.000,08.400,05.00,05.400,05.00,00.20> "%WORKDIR%\lxprofession00%%i.txt"
    )
    for /L %%i in (10,1,99) do (
        echo ,02,00.000,08.400,05.00,05.400,05.00,00.20> "%WORKDIR%\lxprofession0%%i.txt"
    )
    echo       Reset lxprofession000 through lxprofession099
) else (
    echo       WARNING: w_work folder not found!
)

echo [3/3] Resetting DIY presets to factory defaults...

if exist "%WORKDIR%" (
    set "DEFAULT_DIY=,DIY01[4][1][    1][    1][0][ 0.000][12][ 8.400][ 1.50][ 0.20][ 5.400][ 1.50],DIY02[5][1][    1][    1][0][ 0.000][12][11.200][ 1.50][ 0.20][ 7.200][ 1.50],DIY03[6][1][    1][    1][0][ 0.000][12][16.800][ 1.50][ 0.20][10.800][ 1.50]"

    for /L %%i in (0,1,9) do (
        echo ,DIY01[4][1][    1][    1][0][ 0.000][12][ 8.400][ 1.50][ 0.20][ 5.400][ 1.50],DIY02[5][1][    1][    1][0][ 0.000][12][11.200][ 1.50][ 0.20][ 7.200][ 1.50],DIY03[6][1][    1][    1][0][ 0.000][12][16.800][ 1.50][ 0.20][10.800][ 1.50]> "%WORKDIR%\lxdiy0%%i.txt"
    )
    for /L %%i in (10,1,99) do (
        echo ,DIY01[4][1][    1][    1][0][ 0.000][12][ 8.400][ 1.50][ 0.20][ 5.400][ 1.50],DIY02[5][1][    1][    1][0][ 0.000][12][11.200][ 1.50][ 0.20][ 7.200][ 1.50],DIY03[6][1][    1][    1][0][ 0.000][12][16.800][ 1.50][ 0.20][10.800][ 1.50]> "%WORKDIR%\lxdiy%%i.txt"
    )
    echo       Reset lxdiy00 through lxdiy99
) else (
    echo       WARNING: w_work folder not found!
)

echo.
echo  ========================================
echo   RESET COMPLETE!
echo  ========================================
echo.
echo  All charging data cleared.
echo  All profiles reset to factory defaults.
echo  All DIY presets reset to factory defaults.
echo.
echo  NOTE: lxdata000 (channel headers) was preserved.
echo.
pause
