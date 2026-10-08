@echo off
REM ============================================================
REM Limpa a planilha de controle. Use se quiser comecar do zero
REM (deleta o .xlsx; o main.py recria na proxima execucao).
REM ============================================================
echo.
echo === LIMPANDO PLANILHA DE CONTROLE ===
echo.
del /f /q "%USERPROFILE%\Desktop\Nota Fiscal - MEIs\controle_notas_fiscais.xlsx" 2>nul
if errorlevel 1 (
    echo Planilha nao existia ou ja foi removida. Tudo certo.
) else (
    echo Planilha removida com sucesso.
)
echo.
echo === Finalizado. Pressione qualquer tecla para fechar. ===
pause
