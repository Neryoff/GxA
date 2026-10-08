@echo off
REM ============================================================
REM INSTALA o daemon pra rodar automaticamente quando o PC ligar.
REM NAO precisa de admin!
REM
REM Usa a pasta "Inicializar" do seu usuario (pessoal).
REM Roda INVISIVEL (sem janela preta nem Chrome).
REM
REM Para DESinstalar: rode o desinstalar_automatico.bat
REM ============================================================

set SCRIPT_DIR=%~dp0
set BAT_SOURCE=%SCRIPT_DIR%iniciar_daemon_silencioso.bat
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

echo.
echo === Instalando GestaoX pra rodar automaticamente ===
echo.
echo Pasta Inicializar: %STARTUP_DIR%
echo.

if not exist "%BAT_SOURCE%" (
    echo [ERRO] Arquivo nao encontrado: %BAT_SOURCE%
    pause
    exit /b 1
)

REM Remove versao anterior (se tiver) - silencioso
del /F /Q "%STARTUP_DIR%\iniciar_daemon_silencioso.bat" >nul 2>&1
del /F /Q "%STARTUP_DIR%\rodar_daemon_silencioso.vbs" >nul 2>&1

REM Copia o .bat pra pasta Inicializar
copy /Y "%BAT_SOURCE%" "%STARTUP_DIR%\iniciar_daemon_silencioso.bat" >nul
if errorlevel 1 (
    echo [ERRO] Falha ao copiar. Verifique permissoes.
    pause
    exit /b 1
)

REM Limpa lock antigo (caso tenha sobrado)
del /F /Q "%USERPROFILE%\gestao_x_daemon.lock" >nul 2>&1

echo.
echo ============================================
echo OK! Instalado com sucesso.
echo.
echo Da agora em diante, quando voce LIGAR o PC
echo e FIZER LOGIN, o daemon inicia sozinho
echo (invisivel, sem janela, sem Chrome).
echo
echo Ele verifica novos chamados a cada 5 minutos.
echo ============================================
echo.
echo ONDE VER O QUE TA ACONTECENDO:
echo   - Log:    %USERPROFILE%\gestao_x_daemon.log
echo   - Lock:   %USERPROFILE%\gestao_x_daemon.lock
echo   - PDFs:   %USERPROFILE%\Desktop\Nota Fiscal - MEIs\
echo   - Planilha: controle_notas_fiscais.xlsx na mesma pasta
echo.
echo PARA PARAR:
echo   Rode o desinstalar_automatico.bat
echo   OU mate o python.exe no Gerenciador de Tarefas
echo.
pause