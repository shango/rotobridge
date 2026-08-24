@echo off
rem RotoBridge - Nuke installer.
rem
rem Copies this folder's payload into your .nuke folder and adds one line to
rem init.py so Nuke finds it. Nothing outside your own user folder is touched,
rem so this never needs administrator rights.

setlocal

set "SRC=%~dp0rotobridge"
set "DEST=%USERPROFILE%\.nuke\rotobridge"
set "INIT=%USERPROFILE%\.nuke\init.py"

if not exist "%SRC%" (
    echo.
    echo Could not find the files to install next to this script.
    echo Unzip the whole download first, then run this from the unzipped copy
    echo - Windows will not let it work from inside the .zip.
    echo.
    pause
    exit /b 1
)

echo Installing RotoBridge to %DEST%
echo.

rem /MIR so reinstalling an older build leaves nothing of the newer one behind.
robocopy "%SRC%" "%DEST%" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo.
    echo Copy failed. Is Nuke open? Close it and run this again.
    echo.
    pause
    exit /b 1
)

rem Forward slashes so the path needs no escaping inside the Python string.
set "PLUGIN=%DEST:\=/%/nuke"

findstr /C:"rotobridge" "%INIT%" >nul 2>&1
if errorlevel 1 (
    echo Adding RotoBridge to %INIT%
    >>"%INIT%" echo.
    >>"%INIT%" echo # RotoBridge
    >>"%INIT%" echo import nuke
    >>"%INIT%" echo nuke.pluginAddPath^("%PLUGIN%"^)
) else (
    echo %INIT% already mentions RotoBridge, leaving it alone.
)

echo.
echo Done. Start Nuke - there will be a RotoBridge menu in the menu bar.
echo If you had Nuke open, close it and open it again first.
echo.
pause
