@echo off
REM ============================================================
REM Roda a Etapa 1 e fecha a janela sozinho depois.
REM ============================================================
cd /d "%~dp0"
echo.
echo === ETAPA 1 - processar 1 chamado ===
echo.
py main.py
echo.
echo === Finalizado. Esta janela fecha em 5 segundos. ===
timeout /t 5 /nobreak >nul
exit
