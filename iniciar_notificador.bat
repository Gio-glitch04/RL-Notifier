@echo off
title Notificador tienda Rocket League / Fortnite
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
rem Arranca el servidor local y abre la tienda en el navegador (http://127.0.0.1:8765)
python notificador.py
pause
