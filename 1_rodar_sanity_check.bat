@echo off
REM ============================================================
REM Roda o sanity check (Etapa 0).
REM Duplo-clique aqui. O Chrome vai abrir sozinho.
REM ============================================================
cd /d "%~dp0"
echo.
echo === SANITY CHECK - Etapa 0 ===
echo.
py sanity_check.py
echo.
echo === Finalizado. Pressione qualquer tecla para fechar. ===
pause
