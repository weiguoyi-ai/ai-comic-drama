@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI 漫剧工坊

set PY=
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" set PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if "%PY%"=="" set PY=python

echo ============================================
echo   AI 漫剧工坊 - 正在启动
echo   浏览器打开 http://127.0.0.1:8000
echo   关闭本窗口即停止服务
echo ============================================
start "" http://127.0.0.1:8000
"%PY%" server.py
pause
