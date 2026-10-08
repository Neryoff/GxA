@echo off
REM ============================================================
REM Extrai o zip "Nota Fiscal - MEIs.zip" que está na Área de
REM Trabalho para uma pasta gestao_x_automation na mesma Área.
REM Duplo-clique neste arquivo.
REM ============================================================
echo Extraindo o zip na Area de Trabalho...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%USERPROFILE%\Desktop\Nota Fiscal - MEIs.zip' -DestinationPath '%USERPROFILE%\Desktop' -Force"
if errorlevel 1 (
    echo.
    echo FALHOU. Tentando metodo alternativo...
    echo Abrindo o zip no Explorer. Clique com botao direito e "Extrair tudo".
    explorer "%USERPROFILE%\Desktop\Nota Fiscal - MEIs.zip"
) else (
    echo.
    echo Pronto! Pasta criada em: %USERPROFILE%\Desktop\gestao_x_automation
    echo.
    explorer "%USERPROFILE%\Desktop\gestao_x_automation"
)
pause
