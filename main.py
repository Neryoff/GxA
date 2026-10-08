"""
Automação Gestão X — versão SIMPLES.

Fluxo:
  1) Login
  2) Aplicar filtro de serviço + grupo
  3) Listar TODOS os tickets da página
  4) Para cada ticket:
     a) Clica no lnkHistorico
     b) Vai pra aba Anexos
     c) Lê os anexos
     d) Identifica a NF
     e) Baixa
     f) Salva em ~/Desktop/Nota Fiscal - MEIs/
     g) Registra na planilha
     h) Fecha
"""
import logging
import re
import sys
from pathlib import Path

from playwright.sync_api import (
    BrowserContext,
    Download,
    Locator,
    Page,
    TimeoutError as PWTimeout,
    sync_playwright,
)

import classifier
import config
import due_date_validator
import tracker


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gestao_x")


# Constantes de seletores
URL_LOGIN = "https://csc.taua.com.br/Login.aspx"
URL_CHAMADOS = "https://csc.taua.com.br/Chamados/TodosV2"
IFRAME_NAME = "radChamado"
MAIN_GRID_ID = "ctl00_MainContent_gridchamados"
ATTACH_GRID_ID = "gridAnexos"


# ── Helpers ────────────────────────────────────────────────────────────────
def _read_cell_text(cell) -> str:
    """Tenta ler o texto de uma célula."""
    try:
        t = (cell.text_content() or "").strip()
        if t:
            return t
    except Exception:
        pass
    try:
        t = (cell.inner_text() or "").strip()
        if t:
            return t
    except Exception:
        pass
    try:
        t = (cell.evaluate("el => (el.innerText || el.textContent || '').trim()") or "").strip()
        if t:
            return t
    except Exception:
        pass
    return ""


def _read_code_from_row(row_locator) -> str | None:
    """Procura o código do chamado (XX000000000) no texto das células da linha."""
    cells = row_locator.locator("td")
    n = cells.count()
    code_pat = re.compile(r"\b[A-Z]{2,10}\d{6,12}\b")
    for j in range(n):
        txt = _read_cell_text(cells.nth(j))
        m = code_pat.search(txt)
        if m:
            return m.group(0)
    return None


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def _read_nfse_from_pdf(pdf_path: str) -> dict:
    """
    Lê o PDF da NFS-e e extrai:
      - num_nota: número da NFS-e
      - serie: série
      - data_emiss: data de emissão (só data, sem hora)
      - ref: descrição do serviço (vai pro Histórico)
    Retorna dict com chaves vazias se o PDF não puder ser lido.
    """
    info = {"num_nota": "", "serie": "", "data_emiss": "", "ref": ""}
    try:
        import pdfplumber
    except ImportError:
        log.warning("  pdfplumber não instalado — pulando leitura do PDF")
        return info

    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
        log.info("  PDF lido (pdfplumber): %d chars extraídos", len(text.strip()))
    except Exception as e:
        log.warning("  ERRO ao abrir PDF com pdfplumber: %s (%s)", type(e).__name__, e)
        text = ""

    # ─── FALLBACK OCR: se pdfplumber extraiu pouco/vazio, é PDF escaneado/imagem ───
    if len(text.strip()) < 50:
        log.warning("  Texto extraído pequeno (%d) — tentando OCR (tesseract)", len(text.strip()))
        try:
            from pdf2image import convert_from_path
            import pytesseract
            images = convert_from_path(pdf_path, dpi=200)
            ocr_text = ""
            for img in images:
                # Tenta português primeiro, depois inglês como fallback
                for lang in ("por", "eng"):
                    try:
                        page_text = pytesseract.image_to_string(img, lang=lang)
                        if page_text and len(page_text.strip()) > len(ocr_text.strip()):
                            ocr_text = page_text
                        if ocr_text.strip():
                            break
                    except Exception:
                        continue
                ocr_text += "\n"
            if ocr_text.strip():
                text = ocr_text
                log.info("  ✓ OCR extraiu %d chars", len(text.strip()))
            else:
                log.warning("  OCR também não retornou texto útil")
        except ImportError:
            log.warning("  pytesseract/pdf2image não instalado — instale com: pip install pytesseract pdf2image")
        except Exception as e:
            log.warning("  ERRO no OCR: %s (%s)", type(e).__name__, e)

    if not text.strip():
        log.warning("  PDF sem texto extraído (pdfplumber E OCR falharam)")
        return info

    # Debug: mostra como o texto do PDF vem (ajuda a calibrar o regex depois)
    log.info("  Tamanho total do texto do PDF: %d chars", len(text))
    # Mostra as PRIMEIRAS 50 linhas (pra calibrar regex quando bate errado)
    log.info("  ── Primeiras 50 linhas do PDF ──")
    for i, ln in enumerate(text.splitlines()[:50], 1):
        log.info("    %2d| %s", i, ln[:180])
    log.info("  ── Fim das primeiras 50 linhas ──")
    # Mostra só linhas com palavras-chave (em vez de 800 chars fixos que podem cortar info)
    log.info("  Linhas com palavras-chave (NFS/DPS/SÉRIE/NÚMERO/EMISS/CHAVE):")
    for ln in text.splitlines():
        if any(kw in ln.upper() for kw in ["NFS", "DPS", "SÉRIE", "SERIE", "NÚMERO", "NUMERO", "EMISS", "CHAVE"]):
            log.info("    | %s", ln.strip()[:200])

    # Salva o texto completo num arquivo pra eu poder ver se precisar
    try:
        debug_path = Path(pdf_path).parent / f"_DEBUG_pdf_text_{Path(pdf_path).stem}.txt"
        # Garante 1 único arquivo (remove qualquer cópia antiga antes)
        if debug_path.exists():
            debug_path.unlink()
        debug_path.write_text(text, encoding="utf-8")
        log.info("  Texto completo salvo em: %s", debug_path.name)
    except Exception as e:
        log.warning("  não consegui salvar texto debug: %s", e)

    # 1) Número da NFS-e — aceita várias formas do label e do separador
    log.info("  Tentando achar Número da NFS-e...")
    found_num = False
    for pat in [
        # SEM espaços entre palavras: pega 1º número da linha ABAIXO do label
        r"N[ÚU]MERODANFS[\s\-·]*e?[^\n]*\n\s*(\d+)",
        # COM espaços: pega 1º número da linha ABAIXO do label
        r"N[ÚU]MERO\s+DA\s+NFS[\s\-·]*e?[^\n]*\n\s*(\d+)",
        # SEM espaços entre palavras (formato real do pdfplumber)
        r"N[ÚU]MERODANFS[\s\-·]*e?\s*[:\n\t]*\s*(\d+)",
        # COM espaços (PDF "limpo")
        r"N[ÚU]MERO\s+DA\s+NFS[\s\-·]*e?\s*[:\n\t]*\s*(\d+)",
        r"N[ÚU]MERO\s*DA\s*NFS[\s\-·]*e?\s*[:\n\t]*\s*(\d+)",
        # Variações do label
        r"N[ºo°]\s*DA\s*NFS[\s\-·]*e?\s*[:\n\t]*\s*(\d+)",
        r"No\.?\s*DA\s+NFS[\s\-·]*e?\s*[:\n\t]*\s*(\d+)",
        r"N\.?\s*DA\s+NFS[\s\-·]*e?\s*[:\n\t]*\s*(\d+)",
        # Aceita ponto no lugar do traço: "NFS.e"
        r"N[ÚU]MERO\s*DA\s*NFS\.?\s*e?\s*[:\n\t]*\s*(\d+)",
        # Pega só o que vem depois do label "NFS-e"
        r"NFS[\s\-·]*e\s*[:\n\t]*\s*(\d{1,8})\b",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            # Tem que ser dígito razoável (1-8 dígitos)
            if candidate.isdigit() and 1 <= len(candidate) <= 8:
                info["num_nota"] = candidate
                log.info("    ✓ achou: %s (padrão: %r)", info["num_nota"], pat)
                found_num = True
                break
    if not found_num:
        # Fallback agressivo: procura "NFS" perto de um número curto
        # (mas ignora a chave de acesso, que tem 50 dígitos)
        for m in re.finditer(r"NFS[\s\-·.]*e?", text, re.IGNORECASE):
            tail = text[m.end(): m.end() + 200]
            num = re.search(r"\s*[:\n\t]*\s*(\d{1,8})\b", tail)
            if num and not re.match(r"^\d{20,}", tail):
                info["num_nota"] = num.group(1).strip()
                log.info("    ✓ achou por fallback: %s (depois de 'NFS-e')", info["num_nota"])
                found_num = True
                break
    if not info["num_nota"]:
        log.info("    ✗ nenhum padrão bateu pra num_nota")

    # 2) Série da DPS — vem na linha de valores abaixo do label
    log.info("  Tentando achar Série...")
    found_serie = False
    for pat in [
        # SEM espaços entre palavras: pega 2º número da linha ABAIXO de NÚMERODADPS
        r"N[ÚU]MERODADPS[^\n]*\n\s*\d+\s+(\d+)",
        # COM espaços: pega 2º número da linha ABAIXO de NÚMERO DA DPS
        r"N[ÚU]MERO\s+DA\s+DPS[^\n]*\n\s*\d+\s+(\d+)",
        # SEM espaços: direto após SÉRIEDADPS (caso número esteja na mesma linha)
        r"S[ÉE]RIEDADPS\s*[:\n\t]*\s*(\d+)",
        # COM espaços
        r"S[ÉE]RIE\s+DA\s+DPS\s*[:\n\t]*\s*(\d+)",
        r"S[ÉE]RIE\s*DA\s*DPS\s*[:\n\t]*\s*(\d+)",
        r"SERIE\s+DA\s+DPS\s*[:\n\t]*\s*(\d+)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if candidate.isdigit() and 1 <= len(candidate) <= 8:
                info["serie"] = candidate
                log.info("    ✓ achou: %s (padrão: %r)", info["serie"], pat)
                found_serie = True
                break
    if not found_serie:
        # Fallback: procura "SÉRIE DA DPS" e pula pra próxima linha com 2+ números
        for m in re.finditer(r"S[ÉE]RIE\s*DA\s*DPS", text, re.IGNORECASE):
            tail = text[m.end(): m.end() + 300]
            # Pula pra próxima linha se a atual não tem número
            nl = tail.find("\n")
            if nl != -1:
                tail2 = tail[nl + 1:]
            else:
                tail2 = tail
            nums = re.findall(r"\d+", tail2)
            if len(nums) >= 2:
                # 2º número da linha de valores = série (geralmente dps_num, serie, data)
                info["serie"] = nums[1]
                log.info("    ✓ achou por fallback: %s (2º número na linha dps)",
                         info["serie"])
                found_serie = True
                break
    if not info["serie"]:
        log.info("    ✗ nenhum padrão bateu pra serie")

    # 3) Data de emissão — formato é dd/mm/aaaa + (hh:mm:ss concatenado sem espaço)
    log.info("  Tentando achar Data de emissão...")
    for pat in [
        # Genérico: data concatenada com hora (sem espaço entre eles)
        r"(\d{2}/\d{2}/\d{4})\d{2}:\d{2}:\d{2}",
        # Linha de valores: 3 números (num_dps, série, data+hora)
        r"N[ÚU]MERODADPS\s*\n?\s*\d+\s+\d+\s+(\d{2}/\d{2}/\d{4})",
        # COM espaços no label
        r"DATA\s+(?:E\s+HORA\s+)?DA\s+EMISS[ÃÃ]O\s+DA\s+NFS[- ]?e?\s*[:\n]?\s*(\d{2}/\d{2}/\d{4})",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            info["data_emiss"] = m.group(1).strip()
            log.info("    ✓ achou: %s (padrão: %r)", info["data_emiss"], pat)
            break
    if not info["data_emiss"]:
        log.info("    ✗ nenhum padrão bateu pra data_emiss")

    # 4) Descrição do Serviço — pega até 500 chars depois do label e depois resume
    log.info("  Tentando achar Descrição do Serviço...")
    ref_raw = ""
    for pat in [
        # SEM espaços
        r"Descri[çc][ãa]odoServi[çc]o\s*\n+([\s\S]{1,500}?)(?=\n[A-ZÀ-Ÿ]{3,}|\Z)",
        # COM espaços (PDF "limpo")
        r"Descri[çc][ãa]o\s+do\s+Servi[çc]o\s*\n?\s*([\s\S]{1,500}?)(?=\n[A-ZÀ-Ÿ]{3,}|\Z)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            ref_raw = m.group(1).strip()
            # Insere espaços onde estavam (formato djviny400 → dj viny 400)
            # porque o pdfplumber removeu os espaços entre palavras
            ref_raw = re.sub(r"(\d{3,4})(\d{2}/\d{2})", r"\1 \2", ref_raw)  # "40018/09" → "400 18/09"
            ref_raw = re.sub(r"(\d{2})/(\d{2})dj", r"\1/\2 dj", ref_raw)
            ref_raw = re.sub(r"dj([A-Za-zÀ-ÿ]+)", r"dj \1", ref_raw)
            ref_raw = re.sub(r"(\d{3,4})([A-Za-zÀ-ÿ])", r"\1 \2", ref_raw)
            ref_raw = re.sub(r"([A-Za-zÀ-ÿ])(\d{3,4})", r"\1 \2", ref_raw)
            ref_raw = re.sub(r"vozeviol", r"voz e viol", ref_raw)
            ref_raw = re.sub(r"pagode(\d)", r"pagode \1", ref_raw)
            # Resume a descrição em uma REF curta
            info["ref"] = _summarize_ref(ref_raw)
            log.info("    ✓ bruto (%d chars) → resumo: %s", len(ref_raw), info["ref"])
            break
    if not info["ref"]:
        log.info("    ✗ nenhum padrão bateu pra ref")

    return info


def _summarize_ref(desc: str, max_len: int = 60) -> str:
    """
    Resume a descrição do serviço vinda da NFS-e em uma REF. curta.

    Estratégia:
      1) Pré-processa: insere espaços onde pdfplumber comeu (dj, pagode, etc.)
      2) Normaliza espaços duplicados
      3) Tenta separar palavras comuns grudadas ("Serviçodearte" → "Serviço de arte")
      4) Corta em " para " (separa a descrição do nome do tomador)
      5) Pega só a parte antes da primeira vírgula (essência da descrição)
      6) Se ainda assim passar de max_len, trunca no último espaço

    Exemplo:
      "Serviçodeartefeito sob encomenda,customizaçãodeum...paraoTAUA HOTEL..."
      → "Serviço de arte feito sob encomenda"
    """
    if not desc:
        return ""

    # Tenta separar preposições comuns grudadas no INÍCIO de uma palavra
    # (precedidas por outra letra minúscula, seguidas por MAIÚSCULA)
    # Ex: "artefeitoSobEncomenda" → "artefeito Sob Encomenda"
    # Limitação: não separa preposições no MEIO de palavras longas minúsculas
    # (ex: "Serviçodeartefeito" continua grudado — precisaria de dicionário).
    # Mas PDFs que já vêm com espaços entre palavras ficam perfeitos.
    SMALL_WORDS = [
        "para", "com", "sob", "por",
        "dos", "das", "nos", "nas",
        "de", "do", "da",
        "em", "no", "na",
    ]

    s = desc.strip()

    # Re-insere espaço entre dígito+letra (ex: "400dj" → "400 dj")
    s = re.sub(r"(\d)([A-Za-z])", r"\1 \2", s)
    # Re-insere espaço entre letra+dígito (ex: "viny400" → "viny 400")
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)

    # Separa preposições comuns seguidas de MAIÚSCULA (caso comum em colagens)
    for w in SMALL_WORDS:
        s = re.sub(
            rf"(?<=[a-zà-ÿ])({w})(?=[A-ZÀ-Ÿ])",
            r" \1 ",
            s,
        )

    # Normaliza espaços duplicados
    s = re.sub(r"\s+", " ", s).strip()

    # Corta em " para " (remove o nome do tomador no final)
    m = re.search(r"\s+para\s+", s, re.IGNORECASE)
    if m:
        s = s[: m.start()].strip()
    # Pega só a parte antes da primeira vírgula (essência da descrição)
    if "," in s:
        s = s.split(",", 1)[0].strip()
    # Trunca no último espaço se passar do limite
    if len(s) > max_len:
        trunc = s[:max_len].rsplit(" ", 1)[0].strip()
        s = trunc + "…" if trunc else s[:max_len] + "…"
    return s


# ── 1. Login ───────────────────────────────────────────────────────────────
def login(page: Page) -> None:
    log.info("Acessando %s", URL_LOGIN)
    page.goto(URL_LOGIN)
    page.locator("#edtLogin").click()
    page.locator("#edtLogin").fill(config.USERNAME)
    page.get_by_role("textbox", name="Se sua senha foi resetada,").click()
    page.get_by_role("textbox", name="Se sua senha foi resetada,").fill(config.PASSWORD)
    page.get_by_role("textbox", name="Se sua senha foi resetada,").press("Enter")
    try:
        page.get_by_role("button", name="Submit").click(timeout=2000)
    except PWTimeout:
        pass
    page.goto(URL_CHAMADOS)
    page.wait_for_load_state("networkidle")


# ── 2. Filtros ─────────────────────────────────────────────────────────────
def apply_filters(page: Page) -> None:
    log.info("Aplicando filtros: serviço + grupo")
    page.get_by_alt_text("Filter DESCRICAO_SERVICO").click()
    page.get_by_alt_text("Filter DESCRICAO_SERVICO").fill(config.SERVICO)
    page.get_by_alt_text("Filter DESCRICAO_SERVICO").press("Enter")
    page.get_by_alt_text("Filter NOME_GRUPO_SOLUCIONADOR column").click()
    page.get_by_alt_text("Filter NOME_GRUPO_SOLUCIONADOR column").fill(config.GRUPO)
    page.get_by_alt_text("Filter NOME_GRUPO_SOLUCIONADOR column").press("Enter")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


# ── 3. Listar tickets (lê tudo via JS em UMA chamada) ─────────────────────
def list_tickets(page: Page) -> list[dict]:
    """Lê todos os tickets da grade em UMA chamada JavaScript.
    Retorna lista de dicts {code, link_id, row_idx}."""
    log.info("Mapeando linhas do grid…")
    data = page.evaluate(
        """gridSel => {
            const grid = document.querySelector(gridSel);
            if (!grid) return [];
            const trs = grid.querySelectorAll('tbody tr');
            const rows = [];
            trs.forEach((tr, idx) => {
                const cells = tr.querySelectorAll('td');
                const cellTexts = [];
                cells.forEach(c => cellTexts.push((c.innerText || c.textContent || '').trim()));
                // Acha o link lnkHistorico
                const link = tr.querySelector('[id*="_lnkHistorico"]');
                // Acha a checkbox
                const cb = tr.querySelector('input[type="checkbox"]');
                rows.push({
                    idx,
                    cellTexts,
                    linkId: link ? link.id : null,
                    hasCheckbox: !!cb,
                });
            });
            return rows;
        }""",
        f"#{MAIN_GRID_ID}",
    )
    code_pat = re.compile(r"\b[A-Z]{2,10}\d{6,12}\b")
    rows = []
    for r in data or []:
        code = None
        for txt in r.get("cellTexts", []):
            m = code_pat.search(txt)
            if m:
                code = m.group(0)
                break
        if code:
            rows.append({
                "code": code,
                "link_id": r.get("linkId"),
                "row_idx": r.get("idx"),
            })
    log.info("  %d ticket(s) identificado(s)", len(rows))
    return rows


# ── 4. Processar 1 ticket ──────────────────────────────────────────────────
def _find_link_by_code(page: Page, code: str):
    """Acha o lnkHistorico da linha cujo código bate. Retorna o Locator ou None.
    Necessário porque a grid re-renderiza após processar cada ticket
    e os link_ids antigos ficam inválidos."""
    try:
        return page.locator(
            f"#{MAIN_GRID_ID} tr",
            has=page.locator(f"td:has-text(\"{code}\")"),
        ).first.locator("[id*='_lnkHistorico']").first
    except Exception:
        return None


def _parse_field(body_text: str, label_regex: str) -> str:
    """Procura um campo no texto do Detalhes. Ex: 'Ordem de compra\\s*\\n?\\s*([0-9]+)'."""
    m = re.search(label_regex, body_text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def read_ticket_details(page: Page, iframe, code: str) -> dict:
    """
    Lê os campos da aba Detalhes:
      - OC (Ordem de compra)
      - Data de venc. (Data do primeiro vencimento, só a data, sem hora)
      - Forma de pagamento (PIX, Depósito Bancário, etc.)
      - Pix (chave PIX) ou Banco/Agência/Conta Corrente
    E monta o Histórico conforme a forma de pagamento:
      - PIX          → "<code> / PIX <chave>"
      - Depósito      → "<code> / Banco <nome> / Agência <num> / Conta Corrente <num>"
    Retorna dict {"oc", "data_venc", "historico"}.
    Mesmo que a NF não seja encontrada, faz essa leitura.
    """
    details = {"oc": "", "data_venc": "", "forma_pagamento": "", "tipo_chave_pix": "",
               "pix": "", "banco": "", "agencia": "", "conta": "", "historico": "",
               "adiantamento_anterior": ""}

    # 1) Entra na aba Detalhes (se já tiver nela, é no-op)
    try:
        iframe.get_by_text("Detalhes", exact=True).click(timeout=5000)
        page.wait_for_timeout(2000)
    except Exception as e:
        log.warning("  não consegui abrir aba Detalhes: %s", e)
        return details

    # 2) Lê todo o texto do body do iframe
    body_text = ""
    try:
        body_text = iframe.locator("body").text_content() or ""
    except Exception:
        return details

    # 2b) Fornecedor — pega do campo "PRESTADOR / FORNECEDOR" → "Nome / Nome Empresarial"
    # O texto no Gestão X é algo como:
    #   "PRESTADOR / FORNECEDOR\nCNPJ / CPF / NIF\n60.722.580/0001-52\nNome / Nome Empresarial\nRAIE FERNANDES FERREIRA\n..."
    forn_match = re.search(
        r"(?:Prestador\s*/?\s*Fornecedor|Fornecedor\s*/?\s*Prestador)\s*\n[^\n]*\n[^\n]*\nNome\s*/\s*Nome\s*Empresarial\s*\n([^\n]+)",
        body_text, re.IGNORECASE
    )
    if forn_match:
        details["fornecedor"] = forn_match.group(1).strip()
    else:
        # Fallback: tenta padrões mais simples
        forn_match = re.search(
            r"Nome\s*/\s*Nome\s*Empresarial\s*\n([^\n]+)",
            body_text, re.IGNORECASE
        )
        if forn_match:
            details["fornecedor"] = forn_match.group(1).strip()

    # 2c) Adiantamento anterior: "Foi realizado algum adiantamento...?"
    #     O texto na Detalhes vem tipo:
    #     "Foi realizado algum adiantamento ao fornecedor para pagamento deste documento anteriormente?*\nNÃO"
    adt_match = re.search(
        r"Foi realizado algum adiantamento[^?]*\?\*?\s*\n?\s*(SIM|NAO|NÃO|Sim|Nao|Não|s|n)",
        body_text, re.IGNORECASE
    )
    if adt_match:
        resp = adt_match.group(1).upper().strip()
        # Normaliza pra SIM ou NÃO
        if resp in ("S", "SIM"):
            details["adiantamento_anterior"] = "SIM"
        elif resp in ("N", "NAO", "NÃO"):
            details["adiantamento_anterior"] = "NÃO"

    # 3) Extrai cada campo via regex
    # OC
    details["oc"] = _parse_field(body_text, r"Ordem de compra\s*[\n:]?\s*([0-9]+)")
    # Data do primeiro vencimento (só data, formato dd/mm/aaaa)
    details["data_venc"] = _parse_field(body_text, r"Data do primeiro vencimento\s*[\n:]?\s*(\d{2}/\d{2}/\d{4})")
    # Forma de pagamento (PIX, Depósito Bancário, etc.)
    fp_match = re.search(
        r"Forma de pagamento\s*[\n:]?\s*([^\n]+?)(?=\s*\n\s*(?:Tipo|Banco|Conta|$))",
        body_text, re.IGNORECASE,
    )
    if fp_match:
        details["forma_pagamento"] = fp_match.group(1).strip()
    # Tipo da chave PIX (CELULAR, CPF / CNPJ, E-MAIL, etc.)
    tipo_pix_match = re.search(
        r"Tipo da chave\s+[Pp]ix\s*[\n:]?\s*([^\n]+?)(?=\s*\n\s*(?:Pix|$))",
        body_text, re.IGNORECASE,
    )
    if tipo_pix_match:
        details["tipo_chave_pix"] = tipo_pix_match.group(1).strip()
    # Chave PIX (a real, não a do label "Tipo da chave Pix")
    # O body tem algo como: "Tipo da chave pix\nCPF/CNPJ\n\nPix\n59790459187"
    # Pega TODOS os matches e usa o ÚLTIMO com pelo menos 5 chars
    # (chaves PIX sempre têm 11+ dígitos, então "Tipo" de 4 chars não vai matchar)
    pix_matches = re.findall(
        r"\bPix\b\s*[\n:]?\s*([0-9A-Za-z@._\-]{5,})",
        body_text,
    )
    if pix_matches:
        details["pix"] = pix_matches[-1]
    # Banco / Agência / Conta (para Depósito)
    banco = re.search(r"Banco\s*[\n:]?\s*([^\n]+?)(?=\s*\n\s*Agência)", body_text, re.IGNORECASE)
    if banco:
        details["banco"] = banco.group(1).strip()
    ag = re.search(r"Agência\s*[\n:]?\s*([0-9\-]+)", body_text, re.IGNORECASE)
    if ag:
        details["agencia"] = ag.group(1).strip()
    cc = re.search(r"Conta(?:\s+corrente)?\s*[\n:]?\s*([0-9\-]+)", body_text, re.IGNORECASE)
    if cc:
        details["conta"] = cc.group(1).strip()

    # 4) Monta histórico conforme forma de pagamento + REF da NFS-e
    # O Histórico tem estrutura:
    #   PIX:      "DOC <num> / <code> / REF. <ref> / / / / PIX <tipo> <chave>"
    #   Depósito: "DOC <num> / <code> / REF. <ref> / / <banco> / <agencia> / <conta> /"
    # O <num> e <ref> vêm do PDF da NFS-e.
    # Inicialmente só temos o code e o pagamento; o num/ref entram depois (via PDF).
    forma = details["forma_pagamento"].upper()
    pagamento_part = ""
    if "PIX" in forma and details["pix"]:
        tipo = details.get("tipo_chave_pix", "").strip()
        if tipo:
            pagamento_part = f"PIX {tipo} {details['pix']}"
        else:
            pagamento_part = f"PIX {details['pix']}"
    elif ("DEPÓSITO" in forma or "DEPOSITO" in forma) and details["banco"]:
        pagamento_part = f"{details['banco']} / {details['agencia']} / {details['conta']}"
    details["historico_base"] = pagamento_part  # guarda pro PDF complementar depois

    log.info("  Detalhes: OC=%s | venc=%s | forma=%s | pix=%s | tipo=%s | hist=%s",
             details["oc"] or "—",
             details["data_venc"] or "—",
             details["forma_pagamento"] or "—",
             details["pix"] or "—",
             details["tipo_chave_pix"] or "—",
             details["historico"] or "—")
    return details


def process_ticket(page: Page, t: dict) -> None:
    code = t["code"]
    data_abertura = t.get("data_abertura", "")
    log.info("─" * 50)
    log.info("Processando: %s", code)
    if data_abertura:
        log.info("  Data de abertura (lida da grade): %s", data_abertura)
    else:
        log.warning("  Data de abertura NÃO encontrada na grade — validação de venc. será pulada")

    if not tracker.should_process(config.SPREADSHEET, code):
        log.info("  ↪ já na planilha com sucesso, pulando")
        return

    # 1) Espera a grid terminar de carregar (RadAjax pode estar animando)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

    # 2) Acha o lnkHistorico pelo código (grid pode ter re-renderizado)
    link = _find_link_by_code(page, code)
    if not link or link.count() == 0:
        log.error("  link do ticket %s não encontrado na grid (pode ter sumido)", code)
        return
    # 3) Clica via JavaScript direto (bypassa o overlay do RadAjax)
    try:
        link.evaluate("el => el.click()")
    except Exception as e:
        log.warning("  JS click falhou, tentando click normal: %s", e)
        try:
            link.click(force=True, timeout=5000)
        except Exception as e2:
            log.error("  falha ao clicar no link: %s", e2)
            return
    page.wait_for_timeout(3000)  # tempo pro iframe carregar

    # 2) Confere se o iframe subiu
    try:
        iframe = page.frame_locator(f"iframe[name=\"{IFRAME_NAME}\"]")
        iframe.locator("body").wait_for(state="visible", timeout=5000)
    except Exception as e:
        log.error("  iframe não subiu: %s", e)
        return

    # ---- FLUXO 1: tentar achar NF nos Anexos ----
    attachments: list[tuple[int, str]] = []
    best_idx, best_name = None, None
    try:
        iframe.get_by_text("Anexos", exact=True).click(timeout=5000)
        page.wait_for_timeout(2000)
        attachments = _read_attachments(iframe)
        log.info("  %d anexo(s) nos Anexos", len(attachments))
        filenames = [n for _, n in attachments]
        best_idx, best_name = classifier.pick_best(filenames)
    except Exception as e:
        log.warning("  não consegui ler Anexos: %s", e)

    saved_path = ""
    prio = 0
    if best_idx is not None:
        prio = classifier.classify(best_name)
        log.info("  NF escolhida (P%d): %s", prio, best_name)
        # Tenta baixar
        try:
            cell_selector = f"#{ATTACH_GRID_ID}_ctl00_ctl{best_idx + 4:02d}_gbcAnexo"
            cell_loc = iframe.locator(cell_selector)
            if cell_loc.count() == 0:
                cell_loc = iframe.locator(f"[id^='{ATTACH_GRID_ID}_ctl00_'][id$='_gbcAnexo']").nth(best_idx)
            with page.expect_download(timeout=15000) as dl_info:
                try:
                    cell_loc.evaluate("el => el.click()")
                except Exception:
                    cell_loc.click(force=True, timeout=5000)
            dl = dl_info.value
            config.NF_FOLDER.mkdir(parents=True, exist_ok=True)
            fname = _sanitize_filename(f"{code}_{best_name}")
            dest = config.NF_FOLDER / fname
            n = 2
            while dest.exists():
                stem, suf = dest.stem, dest.suffix
                dest = config.NF_FOLDER / f"{stem} ({n}){suf}"
                n += 1
            dl.save_as(str(dest))
            saved_path = str(dest)
            log.info("  Salvo: %s", dest)
        except Exception as e:
            log.error("  falha no download: %s", e)
    else:
        log.info("  Nenhuma NF identificada nos Anexos — vou ler Detalhes mesmo assim")

    # ---- FLUXO 2: ler Detalhes (sempre, mesmo sem NF) ----
    details = read_ticket_details(page, iframe, code)

    # ---- Validação da Data de vencimento (regra 7 dias + Seg/Qua) ----
    # data_abertura vem da grade (coluna "Data"); data_venc vem do Detalhes.
    # Aplica a regra e substitui details["data_venc"] com a data válida.
    venc_original = details.get("data_venc", "")
    venc_final, motivo, dbg = due_date_validator.validate_due_date(
        data_abertura, venc_original
    )
    details["data_venc"] = venc_final
    if motivo == "ok":
        log.info("  Vencimento: %s (mantida — data válida)", venc_final)
    elif motivo == "indefinida":
        if venc_original:
            log.warning("  Vencimento: '%s' — não consegui validar (formato?), mantendo como está",
                        venc_original)
        else:
            log.info("  Vencimento: vazio — sem data de abertura pra validar, seguindo em branco")
    elif motivo == "preenchida_min":
        log.info("  Vencimento: vazio → preenchido com mínimo %s (%s)",
                 dbg["min_date"], dbg["min_weekday_pt"])
    elif motivo == "corrigida_anterior":
        log.info("  Vencimento: %s → corrigido pra %s (%s) [abertura=%s (%s) + 7d = %s (%s)]",
                 venc_original or "—", venc_final, dbg["final_weekday_pt"],
                 dbg["open_date"], dbg["open_weekday_pt"],
                 dbg["min_date"], dbg["min_weekday_pt"])
    elif motivo == "corrigida_dia_invalido":
        log.info("  Vencimento: %s → corrigido pra %s (%s) [não era Seg/Qua]",
                 venc_original or "—", venc_final, dbg["final_weekday_pt"])
    else:
        log.info("  Vencimento: motivo=%s final=%s", motivo, venc_final)

    # ---- FLUXO 3: ler o PDF da NFS-e (se foi baixado) pra extrair num_nota/serie/data/REF ----
    nfse = {"num_nota": "", "serie": "", "data_emiss": "", "ref": ""}
    pdf_leitura_ok = False
    if saved_path:
        nfse = _read_nfse_from_pdf(saved_path)
        # Considera leitura OK se pelo menos num_nota foi extraído
        pdf_leitura_ok = bool(nfse["num_nota"])
        log.info("  NFS-e: num=%s | serie=%s | data=%s | ref=%s",
                 nfse["num_nota"] or "—", nfse["serie"] or "—",
                 nfse["data_emiss"] or "—", nfse["ref"] or "—")
        if not pdf_leitura_ok:
            log.warning("  ⚠ PDF salvo mas num_nota NÃO foi extraído — vai reprocessar")

    # ---- Monta o Histórico final (com num_nota e REF da NFS-e) ----
    # PIX:      DOC <num> / <code> / REF. <ref> / / / / PIX <tipo> <chave>
    # Depósito: DOC <num> / <code> / REF. <ref> / / <banco> / <agencia> / <conta> /
    # Se num_nota não foi lido do PDF, OMITE o prefixo "DOC" (não duplica o code)
    pagamento_part = details.get("historico_base", "")
    ref_part = f"REF. {nfse['ref']}" if nfse["ref"] else ""
    tem_doc = bool(nfse["num_nota"])
    doc_part = f"DOC {nfse['num_nota']}" if tem_doc else ""
    if pagamento_part:
        if "PIX" in details["forma_pagamento"].upper():
            # PIX: code + ref + (3 slashes) + pagamento
            if tem_doc:
                details["historico"] = f"{doc_part} / {code} / {ref_part} / / / / {pagamento_part}"
            else:
                details["historico"] = f"{code} / {ref_part} / / / / {pagamento_part}"
        else:
            # Depósito: code + ref + (1 slash) + pagamento
            if tem_doc:
                details["historico"] = f"{doc_part} / {code} / {ref_part} / / {pagamento_part}"
            else:
                details["historico"] = f"{code} / {ref_part} / / {pagamento_part}"
    else:
        if tem_doc:
            details["historico"] = f"{doc_part} / {code} / {ref_part}"
        else:
            details["historico"] = f"{code} / {ref_part}"

    # ---- Registra ----
    # Se PDF foi baixado mas num_nota NÃO foi extraído → registra como ERRO pra reprocessar
    if saved_path and not pdf_leitura_ok:
        status = f"ERRO: PDF lido mas num_nota/serie não extraídos"
        saved_name = best_name
    elif best_idx is not None:
        status = f"NF encontrada (P{prio})"
        saved_name = best_name
    else:
        status = "NF não encontrada"
        saved_name = "—"

    # Monta string de depósito consolidada (Banco / Agência / Conta) — só usada
    # internamente pra montar o Histórico. NÃO vai pra planilha.
    deposito_str = ""
    if details["banco"]:
        deposito_str = f"{details['banco']} / {details['agencia']} / {details['conta']}".strip(" /")

    log.info("  Escrevendo na planilha: %s (adiantamento=%s)",
             code, details.get("adiantamento_anterior") or "—")
    sheets = tracker.register(
        config.SPREADSHEET,
        code=code,
        unidade=tracker.get_unidade_from_code(code)[0],
        solicitante=t.get("solicitante", ""),
        adiantamento_anterior=details.get("adiantamento_anterior", ""),
        total_attachments=len(attachments),
        saved_filename=saved_name,
        status=status,
        data_abertura=t.get("data_abertura", ""),
        oc=details["oc"],
        data_venc=details["data_venc"],
        num_nota=nfse["num_nota"],
        serie=nfse["serie"],
        data_emiss=nfse["data_emiss"],
        historico=details["historico"],
    )
    log.info("  ✓ salvo em: %s", sheets)

    # 9) Fecha
    try:
        page.get_by_title("Close").click(timeout=2000)
    except Exception:
        page.keyboard.press("Escape")
    page.wait_for_timeout(1500)


def _read_attachments(iframe) -> list[tuple[int, str]]:
    """Lê os anexos da grade, tentando várias estratégias.

    Estratégias (em ordem):
      1) Células com id que termina em _gbcAnexo (botão de seleção)
      2) tbody tr (#gridAnexos > tbody > tr)
      3) TRs que tenham QUALQUER célula com texto terminado em .pdf/.xml
      4) JavaScript puro que percorre a grade inteira
      5) Links de download dentro da grade

    Se não achar nada, RECLICA em "Anexos" e tenta de novo (até 3 vezes).
    """
    import time as _time

    rows: list[tuple[int, str]] = []

    def _try_all_strategies(attempt: int) -> list[tuple[int, str]]:
        """Tenta todas as estratégias de leitura."""
        attempt_rows: list[tuple[int, str]] = []

        # Espera a grade aparecer e ter conteúdo
        try:
            iframe.locator(f"#{ATTACH_GRID_ID}").wait_for(state="visible", timeout=10000)
            iframe.wait_for_function(
                f"""() => {{
                    const g = document.querySelector('#{ATTACH_GRID_ID}');
                    if (!g) return false;
                    return g.querySelectorAll('tr').length > 1;
                }}""",
                timeout=5000,
            )
        except Exception:
            pass
        _time.sleep(2.0)

        # ── Estratégia 1: gbcAnexo ─────────────────────────────────
        try:
            cells = iframe.locator(f"[id^='{ATTACH_GRID_ID}_ctl00_'][id$='_gbcAnexo']")
            n = cells.count()
            for i in range(n):
                cell = cells.nth(i)
                try:
                    row_tr = cell.locator("xpath=ancestor::tr[1]")
                    row_cells = row_tr.locator("td")
                    nc = row_cells.count()
                    best = ""
                    for j in range(nc):
                        txt = _read_cell_text(row_cells.nth(j))
                        if txt and (txt.lower().endswith(".pdf") or txt.lower().endswith(".xml")):
                            best = txt
                            break
                    if not best:
                        for j in range(nc):
                            txt = _read_cell_text(row_cells.nth(j))
                            if len(txt) > len(best) and not txt.replace(":", "").replace("/", "").replace(" ", "").isdigit():
                                best = txt
                    if best:
                        attempt_rows.append((i, best))
                except Exception:
                    continue
            if attempt_rows:
                log.info("    [tentativa %d] ✓ Estratégia 1: %d anexos", attempt, len(attempt_rows))
                return attempt_rows
        except Exception:
            pass

        # ── Estratégia 2: tbody tr ────────────────────────────────────
        try:
            body_rows = iframe.locator(f"#{ATTACH_GRID_ID} tbody tr")
            n = body_rows.count()
            log.info("    [tentativa %d] tbody tr: %d", attempt, n)
            for i in range(n):
                row = body_rows.nth(i)
                rcells = row.locator("td")
                nc = rcells.count()
                best = ""
                for j in range(nc):
                    txt = _read_cell_text(rcells.nth(j))
                    if txt and (txt.lower().endswith(".pdf") or txt.lower().endswith(".xml")):
                        best = txt
                        break
                if not best and nc:
                    for j in range(nc):
                        txt = _read_cell_text(rcells.nth(j))
                        if len(txt) > len(best):
                            best = txt
                if best:
                    attempt_rows.append((i, best))
            if attempt_rows:
                log.info("    [tentativa %d] ✓ Estratégia 2: %d anexos", attempt, len(attempt_rows))
                return attempt_rows
        except Exception:
            pass

        # ── Estratégia 3: TODOS os <tr> ───────────────────────────────
        try:
            all_trs = iframe.locator(f"#{ATTACH_GRID_ID} tr")
            n = all_trs.count()
            log.info("    [tentativa %d] todos trs: %d", attempt, n)
            seen = set()
            for i in range(n):
                txt = _read_cell_text(all_trs.nth(i))
                m = re.search(r"[\w\-_.\(\)\[\] ]+\.(?:pdf|xml)", txt, re.IGNORECASE)
                if m and m.group() not in seen:
                    seen.add(m.group())
                    attempt_rows.append((len(attempt_rows), m.group().strip()))
            if attempt_rows:
                log.info("    [tentativa %d] ✓ Estratégia 3: %d anexos", attempt, len(attempt_rows))
                return attempt_rows
        except Exception:
            pass

        # ── Estratégia 4: JavaScript puro ─────────────────────────────
        try:
            js_result = iframe.evaluate(
                """gridSel => {
                    const grid = document.querySelector(gridSel);
                    if (!grid) return [];
                    const trs = grid.querySelectorAll('tr');
                    const out = [];
                    trs.forEach((tr, idx) => {
                        const txt = (tr.innerText || tr.textContent || '').trim();
                        const m = txt.match(/[\\w\\-_\\.\\(\\)\\[\\] ]+\\.(?:pdf|xml)/i);
                        if (m) out.push([idx, m[0].trim()]);
                    });
                    return out;
                }""",
                f"#{ATTACH_GRID_ID}",
            )
            for idx, name in js_result or []:
                if name and name not in [r[1] for r in attempt_rows]:
                    attempt_rows.append((idx, name))
            if attempt_rows:
                log.info("    [tentativa %d] ✓ Estratégia 4 (JS): %d anexos", attempt, len(attempt_rows))
                return attempt_rows
        except Exception:
            pass

        # ── Estratégia 5: links de download ────────────────────────────
        try:
            links = iframe.locator(f"#{ATTACH_GRID_ID} a[href*='.pdf'], #{ATTACH_GRID_ID} a[href*='.xml']")
            n = links.count()
            for i in range(n):
                href = links.nth(i).get_attribute("href") or ""
                name = href.split("/")[-1].split("?")[0] or f"anexo_{i}.pdf"
                if name not in [r[1] for r in attempt_rows]:
                    attempt_rows.append((len(attempt_rows), name))
            if attempt_rows:
                log.info("    [tentativa %d] ✓ Estratégia 5 (links): %d anexos", attempt, len(attempt_rows))
                return attempt_rows
        except Exception:
            pass

        return []

    # ── LOOP PRINCIPAL: tenta até 3 vezes, re-clicando na aba Anexos ──
    for attempt in range(1, 4):
        log.info("    ─── Tentativa %d/3 ───", attempt)
        rows = _try_all_strategies(attempt)
        if rows:
            return rows
        # Se falhou, clica em outra aba e volta pra Anexos pra recarregar
        if attempt < 3:
            try:
                iframe.get_by_text("Histórico", exact=True).click(timeout=3000)
                _time.sleep(0.5)
                iframe.get_by_text("Anexos", exact=True).click(timeout=5000)
                _time.sleep(1.5)
            except Exception:
                _time.sleep(1)

    log.warning("    ✗ Nenhuma estratégia achou anexos após 3 tentativas")
    return []

    # ── Estratégia 1: seletor genérico gbcAnexo ─────────────────────────
    try:
        cells = iframe.locator(f"[id^='{ATTACH_GRID_ID}_ctl00_'][id$='_gbcAnexo']")
        n = cells.count()
        log.info("    gbcAnexo cells: %d", n)
        for i in range(n):
            cell = cells.nth(i)
            try:
                row_tr = cell.locator("xpath=ancestor::tr[1]")
                row_cells = row_tr.locator("td")
                nc = row_cells.count()
                best = ""
                for j in range(nc):
                    txt = _read_cell_text(row_cells.nth(j))
                    if txt and (txt.lower().endswith(".pdf") or txt.lower().endswith(".xml")):
                        best = txt
                        break
                if not best:
                    for j in range(nc):
                        txt = _read_cell_text(row_cells.nth(j))
                        if len(txt) > len(best) and not txt.replace(":", "").replace("/", "").replace(" ", "").isdigit():
                            best = txt
                if best:
                    rows.append((i, best))
            except Exception:
                continue
        if rows:
            log.info("    ✓ Estratégia 1 (gbcAnexo): %d anexos", len(rows))
            return rows
    except Exception as e:
        log.warning("    Estratégia 1 falhou: %s", e)

    # ── Estratégia 2: tbody tr ───────────────────────────────────────────
    try:
        body_rows = iframe.locator(f"#{ATTACH_GRID_ID} tbody tr")
        n = body_rows.count()
        log.info("    tbody tr: %d", n)
        for i in range(n):
            row = body_rows.nth(i)
            rcells = row.locator("td")
            nc = rcells.count()
            best = ""
            for j in range(nc):
                txt = _read_cell_text(rcells.nth(j))
                if txt and (txt.lower().endswith(".pdf") or txt.lower().endswith(".xml")):
                    best = txt
                    break
            if not best and nc:
                for j in range(nc):
                    txt = _read_cell_text(rcells.nth(j))
                    if len(txt) > len(best):
                        best = txt
            if best:
                rows.append((i, best))
        if rows:
            log.info("    ✓ Estratégia 2 (tbody tr): %d anexos", len(rows))
            return rows
    except Exception as e:
        log.warning("    Estratégia 2 falhou: %s", e)

    # ── Estratégia 3: TODOS os <tr> da grade, procurando .pdf/.xml ─────
    try:
        all_trs = iframe.locator(f"#{ATTACH_GRID_ID} tr")
        n = all_trs.count()
        log.info("    todos trs: %d", n)
        seen = set()
        for i in range(n):
            txt = _read_cell_text(all_trs.nth(i))
            m = re.search(r"[\w\-_.\(\)\[\] ]+\.(?:pdf|xml)", txt, re.IGNORECASE)
            if m and m.group() not in seen:
                seen.add(m.group())
                rows.append((len(rows), m.group().strip()))
        if rows:
            log.info("    ✓ Estratégia 3 (todos tr): %d anexos", len(rows))
            return rows
    except Exception as e:
        log.warning("    Estratégia 3 falhou: %s", e)

    # ── Estratégia 4: JavaScript puro ────────────────────────────────────
    try:
        js_result = iframe.evaluate(
            """gridSel => {
                const grid = document.querySelector(gridSel);
                if (!grid) return [];
                const trs = grid.querySelectorAll('tr');
                const out = [];
                trs.forEach((tr, idx) => {
                    const txt = (tr.innerText || tr.textContent || '').trim();
                    const m = txt.match(/[\\w\\-_\\.\\(\\)\\[\\] ]+\\.(?:pdf|xml)/i);
                    if (m) out.push([idx, m[0].trim()]);
                });
                return out;
            }""",
            f"#{ATTACH_GRID_ID}",
        )
        log.info("    JS puro: %d itens", len(js_result or []))
        for idx, name in js_result or []:
            if name and name not in [r[1] for r in rows]:
                rows.append((idx, name))
        if rows:
            log.info("    ✓ Estratégia 4 (JS): %d anexos", len(rows))
            return rows
    except Exception as e:
        log.warning("    Estratégia 4 falhou: %s", e)

    # ── Estratégia 5: links de download dentro da grade ──────────────────
    try:
        links = iframe.locator(f"#{ATTACH_GRID_ID} a[href*='.pdf'], #{ATTACH_GRID_ID} a[href*='.xml']")
        n = links.count()
        log.info("    links download: %d", n)
        for i in range(n):
            href = links.nth(i).get_attribute("href") or ""
            name = href.split("/")[-1].split("?")[0] or f"anexo_{i}.pdf"
            rows.append((len(rows), name))
        if rows:
            log.info("    ✓ Estratégia 5 (links): %d anexos", len(rows))
            return rows
    except Exception as e:
        log.warning("    Estratégia 5 falhou: %s", e)

    log.warning("    Nenhuma estratégia achou anexos (após %d tentativas)", tentativa + 1)
    return rows


# ── 9. Loop dinâmico ───────────────────────────────────────────────────────
def find_next_unprocessed(page) -> dict | None:
    """Lê a grade ATUAL e retorna um dict {"code", "data_abertura"} do primeiro ticket que:
       - Tem o GRUPO correto (lido da linha, não do filtro do topo)
       - NÃO está na planilha
       Retorna None se não há mais nenhum nesta página.
       SEMPRE lê a grade em tempo real — sem cache, sem contagem fixa.
       A data_abertura vem da coluna "Data" da grade (formato "dd/mm/yyyy hh:mm:ss")."""
    # Espera a grid ficar estável antes de ler
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    try:
        page.wait_for_function(
            f"document.querySelectorAll('#{MAIN_GRID_ID} tbody tr').length > 0",
            timeout=15000,
        )
    except Exception:
        pass
    page.wait_for_timeout(2000)

    data = page.evaluate(
        """gridSel => {
            const grid = document.querySelector(gridSel);
            if (!grid) return [];
            const trs = grid.querySelectorAll('tbody tr');
            const out = [];
            trs.forEach((tr) => {
                const cells = tr.querySelectorAll('td');
                const cellTexts = [];
                cells.forEach(c => cellTexts.push((c.innerText || c.textContent || '').trim()));
                out.push(cellTexts);
            });
            return out;
        }""",
        f"#{MAIN_GRID_ID}",
    )

    code_pat = re.compile(r"\b[A-Z]{2,10}\d{6,12}\b")
    target_group = config.GRUPO.strip()
    skipped_group = 0

    for cell_texts in data or []:
        # 1) Pega o código
        code = None
        for txt in cell_texts:
            m = code_pat.search(txt)
            if m:
                code = m.group(0)
                break
        if not code:
            continue

        # 2) Pega o Grupo da LINHA (não confia no filtro do topo)
        #    Procura a célula que parece Grupo: contém "CSC -" E "Contas a Pagar"
        row_group = ""
        for txt in cell_texts:
            if txt and "CSC -" in txt and "Contas a Pagar" in txt:
                row_group = txt
                break

        # Se a célula de Grupo tem valor diferente do target, pula
        if row_group and row_group != target_group:
            skipped_group += 1
            continue

        # 3) Filtra pela planilha: pula se já processado com SUCESSO.
        #    Se está com ERRO ou não está na planilha, processa.
        if tracker.should_process(config.SPREADSHEET, code):
            # Extrai a data de abertura da linha (coluna "Data" — formato dd/mm/yyyy hh:mm:ss)
            data_abertura = due_date_validator.extract_open_date_from_row(cell_texts)
            # Pega o solicitante: prioriza texto composto (com espaço = nome completo)
            # tipo "Raie Fernandes Ferreira". Pula o próprio código do chamado
            # e tipos genéricos ("Solicitação de serviços", "Reclamação", etc.).
            import re as _re
            # Termos comuns de TIPO de chamado que não são nome de solicitante
            TIPOS_GENERICOS = {
                "solicitação de serviços", "reclamação", "incidente",
                "solicitação", "atendimento", "demanda", "no meu trabalho",
                "trabalho", "manhã", "tarde", "noite", "integral",
                "semanal", "mensal", "diário", "diario",
                "8 horas", "6 horas", "4 horas", "12x36",
            }
            # LOG DE DIAGNÓSTICO: mostra TUDO que tem nas células
            log.info("    [DEBUG] cell_texts da linha: %s", cell_texts)
            solicitante = ""
            for txt in cell_texts:
                t = (txt or "").strip()
                if not t or len(t) <= 2:
                    continue
                # Pula o próprio código do chamado (ex: ATIBAIA176301)
                if _re.match(r"^[A-Z]{2,}\d{4,}$", t):
                    continue
                # Pula só-dígitos (datas, percentuais)
                if t.replace("/", "").replace(":", "").replace("%", "").replace(" ", "").isdigit():
                    continue
                # Pula tipos genéricos de chamado
                if t.lower() in TIPOS_GENERICOS:
                    continue
                # Pega primeiro texto COM espaço (= nome composto)
                if " " in t:
                    solicitante = t
                    break
                # Senão, guarda como fallback
                if not solicitante:
                    solicitante = t
            return {
                "code": code,
                "data_abertura": data_abertura,
                "solicitante": solicitante,
            }

    if skipped_group:
        log.info("    (pulados nesta página por grupo errado: %d)", skipped_group)
    return None


def has_next_page(page) -> bool:
    """Verifica se existe uma próxima página."""
    try:
        total_pages = page.evaluate(
            """gridSel => {
                const grid = document.querySelector(gridSel);
                if (!grid) return null;
                const all = grid.closest('div')?.parentElement?.innerText || grid.innerText || '';
                const m = all.match(/(\\d+)\\s+items?\\s+in\\s+(\\d+)\\s+pages?/i);
                if (m) return parseInt(m[2], 10);
                return null;
            }""",
            f"#{MAIN_GRID_ID}",
        )
        if total_pages is not None and total_pages <= 1:
            return False
    except Exception:
        pass
    candidates = page.locator(
        f"#{MAIN_GRID_ID} a[id*='_lnkNext'], "
        f"#{MAIN_GRID_ID} [id*='_NextPage'], "
        f"#{MAIN_GRID_ID} a.rgPageNext, "
        f"#{MAIN_GRID_ID} [class*='rgPageNext']"
    )
    n = candidates.count()
    for i in range(n):
        try:
            el = candidates.nth(i)
            if el.is_visible() and el.is_enabled():
                classes = (el.get_attribute("class") or "")
                if "Disabled" not in classes and "disabled" not in classes:
                    return True
        except Exception:
            continue
    return False


def go_to_next_page(page) -> bool:
    """Clica no botão de próxima página."""
    candidates = page.locator(
        f"#{MAIN_GRID_ID} a[id*='_lnkNext'], "
        f"#{MAIN_GRID_ID} [id*='_NextPage'], "
        f"#{MAIN_GRID_ID} a.rgPageNext, "
        f"#{MAIN_GRID_ID} [class*='rgPageNext']"
    )
    n = candidates.count()
    for i in range(n):
        try:
            el = candidates.nth(i)
            if el.is_visible() and el.is_enabled():
                classes = (el.get_attribute("class") or "")
                if "Disabled" not in classes and "disabled" not in classes:
                    el.click()
                    page.wait_for_load_state("networkidle", timeout=15000)
                    page.wait_for_timeout(1500)
                    return True
        except Exception:
            continue
    return False


def run_dynamic_loop(page) -> dict:
    """Loop 100% dinâmico:
    1) Olha pra grade AGORA
    2) Acha o próximo ticket não processado
    3) Processa
    4) Volta pra grade (re-lê em tempo real)
    5) Se não tem mais, tenta próxima página
    6) Se não tem próxima página, encerra
    Nada é fixo — sem lista prévia, sem contagem."""
    stats = {"pages": 0, "processed": 0, "skipped": 0, "nf_found": 0, "no_nf": 0, "errors": 0}
    page_num = 1
    last_processed = None
    stuck_count = 0

    while True:
        log.info("─" * 60)
        log.info("PÁGINA %d — procurando próximo não processado…", page_num)

        next_t = find_next_unprocessed(page)
        if next_t is None:
            log.info("Nenhum ticket novo nesta página.")
            if has_next_page(page):
                log.info("→ Indo para a próxima página…")
                if go_to_next_page(page):
                    page_num += 1
                    stats["pages"] += 1
                    continue
                else:
                    log.info("Não consegui ir para a próxima página. Encerrando.")
                    break
            else:
                log.info("Sem próxima página. Encerrando.")
                break

        # Anti-loop: se o "próximo" é o mesmo 2x, trava
        if next_t["code"] == last_processed:
            stuck_count += 1
            if stuck_count >= 2:
                log.warning("Travado no mesmo ticket. Encerrando.")
                break
        else:
            stuck_count = 0
        last_processed = next_t["code"]

        try:
            process_ticket(page, next_t)
            stats["processed"] += 1
        except Exception as e:
            log.exception("Erro processando %s: %s", next_t["code"], e)
            stats["errors"] += 1
            # Registra o erro na planilha (vai aparecer com status "ERRO: ..."
            # e o daemon vai retentar no próximo ciclo).
            _registrar_erro(next_t, str(e))
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            except Exception:
                pass

    return stats


def _registrar_erro(t: dict, motivo: str) -> None:
    """Registra um chamado com status de erro pra ser retentado depois."""
    code = t["code"]
    motivo_curto = motivo[:200].replace("\n", " ")
    try:
        tracker.register(
            config.SPREADSHEET,
            code=code,
            unidade=tracker.get_unidade_from_code(code)[0],
            solicitante=t.get("solicitante", ""),
            adiantamento_anterior="",
            total_attachments=0,
            saved_filename="—",
            status=f"ERRO: {motivo_curto}",
            data_abertura=t.get("data_abertura", ""),
            oc="",
            data_venc="",
            num_nota="",
            serie="",
            data_emiss="",
            historico="",
        )
        log.warning("  ⚠️  ERRO registrado pra %s — vai ser retentado no próximo ciclo", code)
    except Exception as e:
        log.error("  não consegui registrar erro: %s", e)


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> int:
    log.info("=" * 60)
    log.info("GESTÃO X — automação de Notas Fiscais (MEIs)")
    log.info("=" * 60)
    log.info("Pasta de NFs:   %s", config.NF_FOLDER)
    log.info("Planilha:       %s", config.SPREADSHEET)
    log.info(
        "Modo:           %s",
        "TODOS (loop dinâmico)" if config.PROCESS_ALL_TICKETS else "1 ticket (Etapa 1)",
    )

    tracker.ensure_spreadsheet(config.SPREADSHEET)

    # Migração automática: se a planilha já tem dados antigos só na aba "Controle"
    # (de versões anteriores do script), distribui pras abas de unidade.
    migrados = tracker.migrate_to_units(config.SPREADSHEET)
    if migrados > 0:
        log.info("✓ Migração: %d registro(s) antigo(s) distribuídos pras abas de unidade", migrados)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS, slow_mo=config.SLOW_MO_MS)
        context: BrowserContext = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(config.DEFAULT_TIMEOUT_MS)

        try:
            login(page)
            apply_filters(page)

            if config.PROCESS_ALL_TICKETS:
                stats = run_dynamic_loop(page)
            else:
                next_t = find_next_unprocessed(page)
                if not next_t:
                    log.warning("Nenhum ticket não processado encontrado.")
                    return 1
                process_ticket(page, next_t)
                stats = {"pages": 1, "processed": 1, "skipped": 0, "nf_found": 0, "no_nf": 0, "errors": 0}

        finally:
            log.info("Encerrando browser.")
            context.close()
            browser.close()

    log.info("=" * 60)
    log.info("RESUMO FINAL")
    log.info("=" * 60)
    log.info("Páginas percorridas:    %d", stats["pages"])
    log.info("Tickets processados:     %d", stats["processed"])
    log.info("  └─ com NF encontrada:  %d", stats["nf_found"])
    log.info("  └─ sem NF:             %d", stats["no_nf"])
    log.info("  └─ com erro:           %d", stats["errors"])
    log.info("Pulados (planilha):      %d", stats["skipped"])
    log.info("Planilha:                %s", config.SPREADSHEET)
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
