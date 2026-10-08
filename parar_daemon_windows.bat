@echo off
REM ============================================================
REM Para a tarefa agendada do GestaoX.
REM Use quando quiser desativar o processamento automatico.
REM Para reativar, rode o agendar_daemon_windows.bat de novo.
REM ============================================================

set TASK_NAME=GestaoX Automacao Notas Fiscais

echo.
echo === Removendo tarefa agendada: "%TASK_NAME%" ===
echo.

schtasks /Delete /TN "%TASK_NAME%" /F

if errorlevel 1 (
    echo.
    echo A tarefa nao existia ou ja foi removida. Tudo certo.
) else (
    echo.
    echo OK! Tarefa removida. O sistema NAO vai mais processar sozinho.
    echo.
    echo Para reativar: rode o agendar_daemon_windows.bat
)
echo.
pause
