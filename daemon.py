"""
DAEMON — automação contínua do Gestão X (versão silenciosa).

Roda em loop infinito:
  1) Acorda a cada X segundos (config.DAEMON_INTERVAL_SECONDS, padrão 300s = 5min)
  2) Abre browser, aplica filtros
  3) Processa TODOS os chamados novos/erro
  4) Fecha browser
  5) Volta a dormir

Anti-dupla-execução: cria um lock file. Se já existe, não roda outro.

Estados na planilha:
  ✅ Status que NÃO começa com "ERRO:" → sucesso, NÃO retenta
  ⚠️  Status que começa com "ERRO:" → erro, retenta no próximo ciclo
  🆕 Não está na planilha → novo, processa agora

Para parar: rode desinstalar_automatico.bat (se foi instalado no Startup)
           ou mate o processo python.exe daemon.py no Gerenciador de Tarefas.
"""
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

import config
import tracker
from main import (
    apply_filters,
    login,
    run_dynamic_loop,
)


# ── Lock file (evita rodar 2 daemons ao mesmo tempo) ────────────────────────
LOCK_FILE = Path.home() / "gestao_x_daemon.lock"


def _lock_exists_and_valid() -> bool:
    """Retorna True se existe um daemon já rodando (lock válido e PID ativo)."""
    if not LOCK_FILE.exists():
        return False
    try:
        pid = int(LOCK_FILE.read_text().strip())
        # No Windows: checa se o PID existe via tasklist
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in result.stdout
    except FileNotFoundError:
        # tasklist não existe (Linux) → não tem como validar
        # Bloqueia por segurança (assume que lock é válido)
        return True
    except Exception:
        # Outro erro → assume inválido (permite rodar)
        return False


def _adquirir_lock() -> bool:
    """Tenta criar o lock. Retorna False se outro daemon já tá rodando."""
    if _lock_exists_and_valid():
        return False
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def _liberar_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


# ── Logging: grava em arquivo (porque roda invisível) ────────────────────────
LOG_FILE = Path.home() / "gestao_x_daemon.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("daemon")


def ciclo_de_processamento() -> dict:
    """Abre o browser UMA vez, processa tudo, fecha."""
    stats = {"processed": 0, "errors": 0, "nf_found": 0, "pages": 0}
    log.info("=" * 60)
    log.info("CICLO INICIADO — %s", datetime.now().isoformat(timespec="seconds"))
    log.info("=" * 60)

    tracker.ensure_spreadsheet(config.SPREADSHEET)
    migrados = tracker.migrate_to_units(config.SPREADSHEET)
    if migrados > 0:
        log.info("✓ Migração: %d registro(s) antigo(s) distribuídos pras abas de unidade", migrados)

    with sync_playwright() as p:
        # Se DAEMON_HEADLESS=True, roda sem janela do navegador
        headless = getattr(config, "DAEMON_HEADLESS", True)
        browser = p.chromium.launch(headless=headless, slow_mo=config.SLOW_MO_MS)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(config.DEFAULT_TIMEOUT_MS)
        try:
            login(page)
            apply_filters(page)
            loop_stats = run_dynamic_loop(page)
            stats.update(loop_stats)
        finally:
            log.info("Encerrando browser.")
            context.close()
            browser.close()

    return stats


def main() -> int:
    if not _adquirir_lock():
        log.warning("Outro daemon já está rodando (lock=%s). Saindo.", LOCK_FILE)
        log.warning("Se não houver outro daemon rodando, delete o arquivo de lock manualmente.")
        return 1

    log.info("=" * 60)
    log.info("GESTÃO X — DAEMON (versão silenciosa)")
    log.info("=" * 60)
    log.info("Log:        %s", LOG_FILE)
    log.info("Lock:       %s", LOCK_FILE)
    log.info("Intervalo:  %ds (~%d min)",
             config.DAEMON_INTERVAL_SECONDS, config.DAEMON_INTERVAL_SECONDS // 60)
    log.info("Headless:   %s (sem janela do Chrome)" if getattr(config, "DAEMON_HEADLESS", True)
             else "False (vai abrir janela do Chrome)")
    log.info("")
    log.info("Para parar: feche o processo python.exe no Gerenciador de Tarefas")
    log.info("             ou rode o desinstalar_automatico.bat")
    log.info("")

    ciclos_seguidos_sem_trabalho = 0

    try:
        while True:
            try:
                stats = ciclo_de_processamento()

                if stats["processed"] > 0:
                    log.info("✓ Ciclo: %d processado(s), %d erro(s), %d com NF encontrada",
                             stats["processed"], stats["errors"], stats["nf_found"])
                    ciclos_seguidos_sem_trabalho = 0
                    sleep_seg = min(30, config.DAEMON_INTERVAL_SECONDS)
                    log.info("→ Teve trabalho. Próxima verificação em %ds…", sleep_seg)
                else:
                    ciclos_seguidos_sem_trabalho += 1
                    sleep_seg = config.DAEMON_INTERVAL_SECONDS
                    log.info("→ Sem chamados novos nesta rodada (#%d). Dormindo %ds (~%d min)…",
                             ciclos_seguidos_sem_trabalho, sleep_seg, sleep_seg // 60)

                time.sleep(sleep_seg)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log.exception("Erro inesperado no ciclo: %s", e)
                log.info("Aguardando 60s antes de tentar de novo…")
                time.sleep(60)

    except KeyboardInterrupt:
        log.info("Daemon parado pelo usuário.")
    finally:
        _liberar_lock()
        log.info("Lock liberado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
