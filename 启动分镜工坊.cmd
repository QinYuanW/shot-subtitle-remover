@echo off
"%~dp0.venv\Scripts\python.exe" -X utf8 "%~dp0launch.py"
if errorlevel 1 pause
