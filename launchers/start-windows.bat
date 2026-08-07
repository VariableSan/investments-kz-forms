@echo off
cd /d "%~dp0.."
docker compose --profile web up --build
pause