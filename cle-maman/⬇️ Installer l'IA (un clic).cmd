@echo off
chcp 65001 >nul
title Installation de l'assistante
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\preparer.ps1"
if errorlevel 1 (
  echo.
  echo Il y a eu un probleme. Verifie la connexion internet, puis relance ce fichier :
  echo ce qui est deja telecharge ne sera pas refait.
)
echo.
pause
