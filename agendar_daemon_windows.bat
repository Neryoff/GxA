@echo off
REM ============================================================
REM Cria tarefa agendada SEM precisar de admin.
REM Roda com o seu proprio usuario (suficiente pro nosso caso).
REM
REM Dois gatilhos:
REM   1) Ao iniciar o Windows (roda assim que o PC liga)
REM   2) A cada 5 minutos
REM ============================================================

set TASK_NAME=GestaoX Automacao Notas Fiscais
set SCRIPT_DIR=%~dp0
set XML_FILE=%SCRIPT_DIR%gestao_x_task.xml
set LOG_FILE=%SCRIPT_DIR%agendar_daemon.log

REM Limpa log antigo
> "%LOG_FILE%" echo === Iniciando em %date% %time% ===

echo.
echo === Criando tarefa: "%TASK_NAME%" ===
echo.
echo Pasta: %SCRIPT_DIR%
echo.

REM Gera o XML com os 2 gatilhos via Python
py "%SCRIPT_DIR%_gerar_task_xml.py" "%SCRIPT_DIR:~0,-1%" "%XML_FILE%" 1>>"%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [ERRO] Falha ao gerar XML. Veja %LOG_FILE%
    type "%LOG_FILE%"
    pause
    exit /b 1
)
echo [OK] XML gerado: %XML_FILE%

REM Deleta tarefa antiga (se existir) - silencioso
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

REM Cria tarefa nova (SEM /RL HIGHEST pra nao precisar de admin)
schtasks /Create /TN "%TASK_NAME%" /XML "%XML_FILE%" 1>>"%LOG_FILE%" 2>&1
set CREATE_RESULT=%errorlevel%

REM Limpa XML temporario
del "%XML_FILE%" 2>nul

if %CREATE_RESULT% neq 0 (
    echo.
    echo [ERRO] Falha ao criar tarefa. Codigo: %CREATE_RESULT%
    echo Detalhes no log: %LOG_FILE%
    echo.
    type "%LOG_FILE%"
    echo.
    echo Possiveis causas:
    echo   - Politica da TI bloqueia tarefas agendadas
    echo   - Falta permissao no usuario
    echo.
    echo SOLUCAO ALTERNATIVA: abra o CMD como admin e rode:
    echo   schtasks /Create /TN "GestaoX" /TR "py.exe \"main.py\"" /SC MINUTE /MO 5 /F
    echo.
    pause
    exit /b 1
)

REM Verifica se foi criada
schtasks /Query /TN "%TASK_NAME%" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERRO] Tarefa nao aparece no Task Scheduler.
    echo Detalhes no log: %LOG_FILE%
    type "%LOG_FILE%"
    pause
    exit /b 1
)

echo.
echo ============================================
echo OK! Tarefa criada com sucesso.
echo.
echo Gatilhos:
echo   1) Ao iniciar o Windows
echo   2) A cada 5 minutos
echo.
echo TESTE: desligue o PC, ligue de novo,
echo e veja se rodou (confira na planilha).
echo ============================================
echo.
echo Para verificar: Win+R - taskschd.msc
echo Para REMOVER: rode o parar_daemon_windows.bat
echo.

del "%LOG_FILE%" 2>nul
pause
