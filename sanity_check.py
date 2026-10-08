"""
Sanity check — Etapa 0.

Só faz: login → aplicar filtros → contar/listar linhas do grid principal
e da grade de anexos do primeiro chamado. NÃO baixa nada, NÃO escreve
planilha. Roda com browser aberto pra você ver se os seletores batem.

Uso:
  python sanity_check.py
"""
import logging
import re
import sys

from playwright.sync_api import sync_playwright

import config
from main import (
    IFRAME_NAME,
    MAIN_GRID_ID,
    _read_cell_text,
    apply_filters,
    list_tickets,
    login,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sanity")


def list_attachments_debug(page) -> list[tuple[int, str]]:
    """Mesma lógica robusta do main.py, mas com mais log."""
    iframe = page.frame_locator(f"iframe[name=\"{IFRAME_NAME}\"]")
    iframe.get_by_text("Anexos", exact=True).click()
    try:
        iframe.locator("#gridAnexos").wait_for(state="visible", timeout=10000)
    except Exception:
        log.warning("Grade #gridAnexos não apareceu em 10s; seguindo mesmo assim.")
    page.wait_for_timeout(2000)

    # Camada 1: seletor genérico
    cells = iframe.locator(f"[id^='gridAnexos_ctl00_'][id$='_gbcAnexo']")
    n_cells = cells.count()
    log.info("Camada 1: %d célula(s) gbcAnexo", n_cells)
    rows = []
    for i in range(n_cells):
        cell = cells.nth(i)
        row = cell.locator("xpath=ancestor::tr[1]")
        row_cells = row.locator("td")
        n_row_cells = row_cells.count()
        cell_texts = []
        best = ""
        for j in range(n_row_cells):
            txt = _read_cell_text(row_cells.nth(j))
            cell_texts.append(txt)
            if txt and (txt.lower().endswith(".pdf") or txt.lower().endswith(".xml")):
                best = txt
                break
            if len(txt) > len(best) and not txt.replace(":", "").replace("/", "").replace(" ", "").isdigit():
                best = txt
        log.info("  célula %d: row_cells=%d, textos=%s, escolhido=%r",
                 i, n_row_cells, cell_texts, best)
        if best:
            rows.append((i, best))
    if rows:
        return rows

    # Camada 2: tbody tr
    log.warning("Camada 1 vazia, tentando tbody tr")
    body_rows = iframe.locator("#gridAnexos tbody tr")
    n_body = body_rows.count()
    log.info("Camada 2: %d linha(s) tbody tr", n_body)
    if n_body > 0:
        for i in range(n_body):
            row = body_rows.nth(i)
            row_cells = row.locator("td")
            n_row_cells = row_cells.count()
            best = ""
            for j in range(n_row_cells):
                txt = _read_cell_text(row_cells.nth(j))
                if txt and (txt.lower().endswith(".pdf") or txt.lower().endswith(".xml")):
                    best = txt
                    break
                if len(txt) > len(best) and not txt.replace(":", "").replace("/", "").replace(" ", "").isdigit():
                    best = txt
            if best:
                rows.append((i, best))
    return rows


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.set_default_timeout(config.DEFAULT_TIMEOUT_MS)

        login(page)
        apply_filters(page)

        # 1) Linhas do grid principal
        log.info("=" * 60)
        log.info("PROCURANDO linhas do grid principal…")
        main_rows = list_tickets(page)
        log.info("Grid principal: %d linha(s) encontrada(s).", len(main_rows))

        # Mostra o texto de cada linha (procura o código do chamado)
        code_pat = re.compile(r"\b[A-Z]{2,10}\d{6,12}\b")
        for i, link in enumerate(main_rows[:10]):
            # Tenta ler o código da linha inteira
            row = link.locator("xpath=ancestor::tr[1]")
            cells = row.locator("td")
            n = cells.count()
            code = None
            all_texts = []
            for j in range(n):
                txt = _read_cell_text(cells.nth(j))
                all_texts.append(txt)
                if not code:
                    m = code_pat.search(txt)
                    if m:
                        code = m.group(0)
            log.info("  [%02d] código=%s | células=%s", i, code, all_texts[:6])

        if not main_rows:
            log.error("0 linhas no grid principal. Filtro pode estar errado.")
            browser.close()
            return 1

        # 2) Abre o PRIMEIRO chamado e olha a grade de anexos
        log.info("=" * 60)
        log.info("Abrindo o primeiro chamado para inspecionar a grade de anexos…")
        main_rows[0].click()
        iframe = page.frame_locator(f"iframe[name=\"{IFRAME_NAME}\"]")
        iframe.locator("body").wait_for(state="visible", timeout=20000)
        page.wait_for_timeout(1500)

        # Tenta ler o código do iframe
        body_text = iframe.locator("body").text_content() or ""
        m = code_pat.search(body_text)
        log.info("Código do chamado aberto: %s", m.group(0) if m else "(não encontrado)")

        log.info("PROCURANDO linhas da grade de anexos…")
        attach_rows = list_attachments_debug(page)
        log.info("=" * 60)
        log.info("RESULTADO FINAL — %d anexo(s) encontrado(s):", len(attach_rows))
        for i, name in attach_rows:
            log.info("  [%02d] %s", i, name)

        if not attach_rows:
            log.error("0 anexos identificados. Vou inspecionar a grade inteira…")
            # Dump de todas as tr
            all_tr = iframe.locator("#gridAnexos tr")
            log.info("Total de <tr> dentro de #gridAnexos: %d", all_tr.count())
            for i in range(min(all_tr.count(), 20)):
                txt = _read_cell_text(all_tr.nth(i))
                log.info("  tr[%d] texto completo: %r", i, txt[:200])

        log.info("=" * 60)
        log.info("Sanity check concluído. O browser ficou aberto pra você inspecionar.")
        log.info("Aperte Ctrl+C pra fechar.")
        try:
            page.wait_for_timeout(600_000)  # 10 min
        except KeyboardInterrupt:
            pass
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
