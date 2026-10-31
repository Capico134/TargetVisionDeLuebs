@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

:: 1. Ins Verzeichnis der Batch-Datei wechseln (NAS/Netzlaufwerk-sicher)
set "PROG_DIR=%~dp0"
pushd "%PROG_DIR%"

:: =========================================================================
:: 1. REQUIREMENTS-CHECK (Sauber ohne Fehlermeldung bei Erstausführung)
:: =========================================================================
if exist "requirements.txt" (
    powershell -NoProfile -Command "$cur = (Get-FileHash 'requirements.txt').Hash; $old = if (Test-Path '.requirements_hash') { (Get-Content '.requirements_hash' -Raw).Trim() } else { '' }; if ($cur -ne $old) { exit 1 } else { exit 0 }"
    
    if errorlevel 1 (
        echo [INFO] Neue oder geaenderte Modulanforderungen erkannt.
        echo Installiere benoetigte Pakete via pip...
        python -m pip install -r requirements.txt
        if not errorlevel 1 (
            powershell -NoProfile -Command "(Get-FileHash 'requirements.txt').Hash | Out-File -Encoding ascii -NoNewline '.requirements_hash'"
        )
        echo.
    )
)

:: =========================================================================
:: 2. ICON-INSPEKTOR: Sucht Verknuepfungen und setzt scheibe.ico (nur 1x)
:: =========================================================================
set "MARKER_FILE=%PROG_DIR%.icon_applied"
set "ICON_FILE=%PROG_DIR%scheibe.ico"

if not exist "%MARKER_FILE%" (
    if exist "%ICON_FILE%" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "$desktops = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory')) | Select-Object -Unique; $icon = '%ICON_FILE%'; $prog = '%PROG_DIR%'; $links = foreach ($d in $desktops) { Get-ChildItem -Path $d -Filter '*.lnk' -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'StartTargetVisionDeLuebs*.lnk' -or $_.Name -like 'TargetVision*.lnk' } }; if ($links) { $ws = New-Object -ComObject WScript.Shell; foreach ($f in $links) { $s = $ws.CreateShortcut($f.FullName); $s.IconLocation = $icon + ',0'; $s.WorkingDirectory = $prog; $s.Save(); Write-Host ('[INFO] Desktop-Verknuepfung veredelt: ' + $f.Name) }; Set-Content -Path '%MARKER_FILE%' -Value '1' -Force }"
    )
)

:: =========================================================================
:: 3. HAUPTANWENDUNG STARTEN
:: =========================================================================
echo Starte TargetVision...
python TargetVisionDeLuebs.py

popd
