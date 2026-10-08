@echo off
REM ============================================================
REM DESINSTALA o daemon automatico (remove da pasta Inicializar).
REM Tambem mata o processo python.exe se estiver rodando.
REM ============================================================

set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set VBS_TARGET=%STARTUP_DIR%\rodar_daemon_silencioso.vbs
set LOCK_FILE=%USERPROFILE%\gestao_x_daemon.lock

echo.
echo === Desinstalando GestaoX automatico ===
echo.

REM Remove o .vbs da pasta Inicializar
if exist "%VBS_TARGET%" (
    del /F /Q "%VBS_TARGET%"
    echo [OK] Removido da pasta Inicializar.
) else (
    echo [INFO] Arquivo ja nao estava na pasta Inicializar.
)

REM Mata o processo python.exe do daemon se estiver rodando
echo.
echo Verificando se o daemon esta rodando...
tasklist /FI "IMAGENAME eq python.exe" /FO CSV /NH | findstr /I "python.exe" >nul
if not errorlevel 1 (
    echo [INFO] Encontrado processo python.exe. Tentando parar...
    taskkill /F /IM python.exe /FI "WINDOWTITLE eq GestaoX*" >nul 2>&1
    REM Se o filtro nao funcionar, mata todos os python.exe (pode ter outros)
    echo.
    echo [AVISO] Se houver outros Python rodando, pule o proximo passo.
    echo.
    set /p KILL_ALL="Matar TODOS os processos python.exe? (s/n): "
    if /I "%KILL_ALL%"=="s" (
        taskkill /F /IM python.exe
        echo [OK] Todos os python.exe foram finalizados.
    ) else (
        echo [INFO] Finalize manualmente o daemon pelo Gerenciador de Tarefas.
    )
) else (
    echo [INFO] Nenhum daemon rodando agora.
)

REM Remove o lock file se existir
if exist "%LOCK_FILE%" (
    del /F /Q "%LOCK_FILE%"
    echo [OK] Lock file removido.
)

echo.
echo ============================================
echo Pronto! O daemon NAO vai mais iniciar sozinho.
echo.
echo Para reativar: rode instalar_automatico.bat
echo ============================================
echo.
pause
