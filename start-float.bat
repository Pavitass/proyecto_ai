@echo off
REM App Electron nativa (control escritorio). Antes: python run.py en helpdesk_agent
REM Otro puerto: set HELPDESK_URL=http://127.0.0.1:PUERTO
setlocal
cd /d "%~dp0electron"
if not defined HELPDESK_URL set HELPDESK_URL=http://127.0.0.1:8787
if not exist node_modules (
  echo Instalando dependencias...
  call npm install
)
call npm start
