@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python run.py --scenario waf --execute
) else (
  py -3 run.py --scenario waf --execute
)
set "REDTEAM_RESULT=%ERRORLEVEL%"
echo Code de resultat : %REDTEAM_RESULT%
pause
exit /b %REDTEAM_RESULT%
