@echo off
REM ============================================================
REM DAEMON — fica rodando em loop, processa chamados novos
REM automaticamente. Pressione Ctrl+C pra parar.
REM ============================================================
cd /d "%~dp0"
echo.
echo === DAEMON - processamento automatico continuo ===
echo.
echo O sistema vai ficar verificando novos chamados a cada
echo intervalo definido em config.py (DAEMON_INTERVAL_SECONDS).
echo.
echo Pressione Ctrl+C para parar quando quiser.
echo.
pause
py daemon.py
echo.
echo === Daemon finalizado. ===
pause
