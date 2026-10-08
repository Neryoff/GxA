"""
Configurações da automação Gestão X.

Preencha USERNAME e PASSWORD (ou defina as variáveis de ambiente
GESTAO_X_USER e GESTAO_X_PASS) antes de rodar.
"""
import os
from pathlib import Path

# === CREDENCIAIS ============================================================
# Opção 1: editar aqui (não commitar credenciais reais!)
USERNAME = os.getenv("GESTAO_X_USER", "joao.faria")
PASSWORD = os.getenv("GESTAO_X_PASS", "147258")

# === FILTROS ================================================================
SERVICO = "CSC FINANCEIRO/CONTAS A PAGAR/Pagamento de Fornecedores - MEIs"
GRUPO = "CSC - Contas a Pagar - Lançamentos"

# === PASTAS =================================================================
# Caminho da Área de Trabalho (funciona em Windows, macOS e Linux).
DESKTOP = Path.home() / "Desktop"

# Pasta onde as Notas Fiscais (PDF/XML) baixadas são salvas.
NF_FOLDER = DESKTOP / "Nota Fiscal - MEIs"

# Planilha de controle (criada automaticamente se não existir).
SPREADSHEET = NF_FOLDER / "controle_notas_fiscais.xlsx"

# === MODO DE EXECUÇÃO =======================================================
# False = Etapa 1: processa APENAS o primeiro chamado da lista (ideal para teste).
# True  = Etapa 2: itera todos os chamados visíveis.
PROCESS_ALL_TICKETS = True

# Intervalo (em segundos) entre cada checagem do daemon.
# Padrão: 300s = 5 minutos. Use 60 pra testes rápidos, 600-900 pra produção.
DAEMON_INTERVAL_SECONDS = 300

# === BROWSER / DEBUG ========================================================
# False = abre o navegador (recomendado na Etapa 1 para acompanhar o que tá rolando).
# True  = roda em background (mais rápido, sem pista visual).
HEADLESS = False

# True = roda o daemon SEM mostrar o Chrome (recomendado quando tá em background).
# False = abre o Chrome (útil pra ver o que tá acontecendo).
DAEMON_HEADLESS = True

# Delay em ms entre cada ação do Playwright. 0 = sem delay. Use 300-500 se quiser
# "modo câmera lenta" para debug.
SLOW_MO_MS = 0

# Timeout padrão para esperas do Playwright.
DEFAULT_TIMEOUT_MS = 30_000
