@echo off
REM ============================================================
REM Inicia o daemon INVISIVEL (sem janela preta).
REM Coloque um atalho deste arquivo na pasta Inicializar
REM do Windows pra rodar automaticamente ao ligar o PC.
REM
REM Feito pra ser executado pelo Agendador de Tarefas ou
REM manualmente. NUNCA mostra janela.
REM ============================================================

cd /d "%~dp0"

REM Mata daemon anterior (libera lock antigo se existir)
del /F /Q "%USERPROFILE%\gestao_x_daemon.lock" >nul 2>&1

REM Inicia o daemon minimizado (sem janela preta)
REM pyw.exe = Python sem console (não cria janela)
REM Se pyw.exe nao existir, usa py.exe com start /min
start "" /min pyw.exe daemon.py 2>nul

REM Se pyw.exe falhou, tenta py.exe normal
if errorlevel 1 (
    start "" /min py.exe daemon.py
)