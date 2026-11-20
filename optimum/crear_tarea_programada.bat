@echo off
REM ==========================================================================
REM  Crea la tarea diaria en el Programador de tareas de Windows.
REM  Doble clic sobre este archivo (una sola vez). Cambia la hora si queres.
REM ==========================================================================
set "HORA=07:15"
set "NOMBRE=Optimum - Perfil de Carga diario"

schtasks /Create /F /SC DAILY /ST %HORA% /TN "%NOMBRE%" /TR "\"%~dp0ejecutar_orquestador.bat\""
if errorlevel 1 (
  echo.
  echo No se pudo crear la tarea. Proba ejecutando este archivo como administrador.
) else (
  echo.
  echo Tarea "%NOMBRE%" creada: corre todos los dias a las %HORA%.
  echo Para probarla ahora:  schtasks /Run /TN "%NOMBRE%"
  echo Para verla o editarla: abri "Programador de tareas" de Windows.
)
pause
