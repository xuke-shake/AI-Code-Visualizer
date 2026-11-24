@echo off
cd /d "%~dp0"

start "AI-Code-Visualizer Backend" cmd /k "call conda.bat activate vue && cd /d backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

start "AI-Code-Visualizer Frontend" cmd /k "cd /d frontend && npm run dev"