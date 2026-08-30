@echo off
echo ===========================================
echo   Update-Service wird vorbereitet...
echo ===========================================
echo.

:: Magie: Springe IMMER in das Hauptverzeichnis von TargetVision (wo die tools/ Datei liegt)
cd /d "%~dp0.."

echo ===========================================
echo   Shooting DeLuebs - Update-Service 🎯
echo ===========================================
echo.
:: Pruefe, ob der Ordner nebenan ueberhaupt existiert
if exist "..\ShootingDeLuebs\" (
    pushd "..\ShootingDeLuebs"
    
    echo Suche nach neuen Versionen auf GitHub...
    git fetch origin
    git --no-pager diff --stat --color HEAD origin/main
    git reset --hard origin/main
    
    :: Springe zurueck zu TargetVision
    popd
) else (
    echo [INFO] Der Ordner "ShootingDeLuebs" wurde auf diesem PC nicht gefunden.
    echo        Das Update wird uebersprungen!
)
echo.

echo ===========================================
echo   Championship DeLuebs - Update-Service 📊
echo ===========================================
echo.
if exist "..\ChampionshipDeLuebs\" (
    pushd "..\ChampionshipDeLuebs"
    
    echo Suche nach neuen Versionen auf GitHub...
    git fetch origin
    git --no-pager diff --stat --color HEAD origin/main
    git reset --hard origin/main
    
    popd
) else (
    echo [INFO] Der Ordner "ChampionshipDeLuebs" wurde auf diesem PC nicht gefunden.
    echo        Das Update wird uebersprungen!
)
echo.

echo ===========================================
echo   TargetVision DeLuebs - Update-Service 🎯
echo ===========================================
echo.
echo Suche nach neuen Versionen auf GitHub...
:: Da wir das Wirts-System sind, updaten wir uns als Allerletztes!
git fetch origin
git --no-pager diff --stat --color HEAD origin/main
git reset --hard origin/main
echo.

echo -------------------------------------------
echo Update-Vorgang abgeschlossen.
echo.
pause