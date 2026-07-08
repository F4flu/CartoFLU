@echo off
:: ============================================================
::  CartoFLU - Serveur local unique (APRS-IS + RF KISS + cartes)
::
::  Utilise TOUJOURS le Python portable fourni dans le dossier
::  python-portable\ (independamment du Python eventuellement
::  installe sur le poste) -> comportement identique partout.
::
::  Usage : ouvrir CartoFLU.html dans le navigateur, PUIS
::          lancer ce script pour demarrer les serveurs.
:: ============================================================
title CartoFLU - Serveur local
cd /d "%~dp0"

set "PYEXE=python-portable\python.exe"
set "PYURL=https://www.python.org/ftp/python/3.12.4/python-3.12.4-embed-amd64.zip"

:: ---- 1) Le script serveur est-il bien present ? ------------------
if not exist "cartoflu_serveur.py" goto no_script

:: ---- 2) Python portable fourni avec l'application ? --------------
if exist "%PYEXE%" goto run

:: ---- Absent (dossier supprime ?) -> telechargement de secours ----
echo.
echo  [INFO] Python portable introuvable dans .\python-portable\
echo  [INFO] Telechargement de secours (~12 Mo) depuis python.org...
echo.

:: Telechargement : curl.exe (natif Win10 1803+/Win11, rapide), sinon PowerShell
if exist "%SystemRoot%\System32\curl.exe" (
    curl.exe -L --fail --ssl-no-revoke -o python-portable.zip "%PYURL%"
) else (
    echo  [INFO] curl indisponible - repli PowerShell...
    powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%PYURL%' -OutFile 'python-portable.zip' -UseBasicParsing } catch { exit 1 }"
)

if not exist "python-portable.zip" (
    echo.
    echo  [ERREUR] Telechargement echoue ^(reseau / proxy / pare-feu ?^).
    echo  Restaurez le dossier python-portable\ fourni avec l'application,
    echo  ou telechargez manuellement :
    echo     %PYURL%
    echo  puis extrayez-le dans un dossier nomme python-portable\
    pause
    exit /b 1
)

:: Extraction : tar.exe (natif Win10+/Win11), sinon PowerShell
echo.
echo  [INFO] Extraction...
if exist "%SystemRoot%\System32\tar.exe" (
    if not exist "python-portable" mkdir "python-portable"
    tar.exe -xf python-portable.zip -C python-portable
) else (
    powershell -NoProfile -Command "Expand-Archive -Path 'python-portable.zip' -DestinationPath 'python-portable' -Force"
)
del /f /q python-portable.zip >nul 2>&1

if not exist "%PYEXE%" (
    echo  [ERREUR] Extraction echouee.
    pause
    exit /b 1
)
echo  [OK] Python portable restaure dans .\python-portable\

:run
echo.
echo  Demarrage du serveur CartoFLU (double source : Internet + RF)...
echo    - Relais APRS-IS    : ws://localhost:2237
echo    - RF KISS/Direwolf  : tcp://localhost:8100  (si un TNC KISS ecoute)
echo    - Tuiles hors ligne : http://localhost:8080/
echo.
echo  Ouvrez CartoFLU.html dans votre navigateur si ce n'est pas deja fait.
echo  Ctrl+C pour arreter le serveur.
echo.

:: Lance le serveur unique en double source (APRS-IS + KISS RF).
:: Pour n'utiliser qu'une source : remplacez "both" par "aprsis" ou "kiss".
%PYEXE% cartoflu_serveur.py --callsign F4FLU --source both --kissport 8100

echo.
echo  [FIN] Le serveur s'est arrete.
pause
exit /b 0

:: ============================================================
:: Diagnostic : cartoflu_serveur.py introuvable
:: ============================================================
:no_script
echo.
echo  [ERREUR] cartoflu_serveur.py introuvable dans ce dossier :
echo     %CD%
echo.
if exist "cartoflu_serveur.py.txt" (
    echo  ^>^> Un fichier "cartoflu_serveur.py.txt" est present.
    echo     Windows a ajoute une extension .txt cachee.
    echo     Renommez-le en "cartoflu_serveur.py" et relancez.
    echo     Astuce : Explorateur ^> Affichage ^> "Extensions de noms
    echo     de fichiers", puis supprimez le ".txt" a la fin du nom.
) else (
    echo  ^>^> Placez cartoflu_serveur.py dans CE dossier, a cote du .bat.
    echo     Si vous avez lance le .bat depuis l'interieur d'un ZIP,
    echo     extrayez d'abord TOUT le contenu du ZIP, puis relancez.
)
echo.
echo  Fichiers reellement presents dans ce dossier :
echo  ------------------------------------------------
dir /b
echo  ------------------------------------------------
echo.
pause
exit /b 1
