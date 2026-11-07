@echo off
rem Запуск патчера на Windows: двойной клик или "tools\sync.cmd --push" из консоли.
rem Нужен только Git for Windows (https://git-scm.com/download/win), в нём уже есть bash и perl.
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "GITBASH="
for /f "delims=" %%G in ('where git 2^>nul') do if not defined GITBASH if exist "%%~dpG..\bin\bash.exe" set "GITBASH=%%~dpG..\bin\bash.exe"
if not defined GITBASH if exist "%ProgramFiles%\Git\bin\bash.exe" set "GITBASH=%ProgramFiles%\Git\bin\bash.exe"
if not defined GITBASH if exist "%LocalAppData%\Programs\Git\bin\bash.exe" set "GITBASH=%LocalAppData%\Programs\Git\bin\bash.exe"
if not defined GITBASH (
  echo Не найден Git for Windows. Поставь его: https://git-scm.com/download/win
  pause
  exit /b 1
)

"%GITBASH%" tools/sync.sh %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
