@echo off
REM ==========================================================================
REM  Ejecuta el orquestador diario. Es lo que llama el Programador de tareas.
REM ==========================================================================
cd /d "%~dp0"
if not exist logs mkdir logs

REM Si usas Anaconda (Spyder), se activa su entorno para que encuentre todo.
REM Ajusta la ruta si tu Anaconda esta en otro lugar.
set "ANACONDA=%USERPROFILE%\anaconda3"
if exist "%ANACONDA%\Scripts\activate.bat" call "%ANACONDA%\Scripts\activate.bat" "%ANACONDA%"

python orquestador_diario.py %* >> "logs\tarea_programada.log" 2>&1
exit /b %ERRORLEVEL%
