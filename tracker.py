"""
Planilha de controle: registra cada chamado processado e impede duplicidade.

Layout:
  Aba "Controle"     → TODOS os registros (visão geral)
  Aba por unidade    → SÓ os daquela unidade (ex: "João Pessoa", "Atibaia")
  → Criadas automaticamente quando aparecer uma unidade nova.

Colunas (iguais em todas as abas):
  Chamado | Unidade | Solicitante | Fornecedor | Total de anexos | Arquivo salvo
  | Status | Data/hora | Data de abertura | OC | Data de venc. | num. Nota
  | serie | data emiss. | Histórico
"""
from datetime import datetime
from pathlib import Path
import re

from openpyxl import Workbook, load_workbook


HEADERS = [
    "Chamado",
    "Unidade",
    "Solicitante",
    "Adiantamento anterior",
    "Total de anexos",
    "Arquivo salvo",
    "Status",
    "Data/hora",
    "Data de abertura",
    "OC",
    "Data de venc.",
    "num. Nota",
    "serie",
    "data emiss.",
    "Histórico",
]

# Excel limita nomes de aba a 31 chars
MAX_SHEET_NAME = 31

# Mapeamento de prefixo do código → nome amigável da aba.
# Adicione aqui unidades novas que devam ter nome com acento ou personalizado.
# Se a unidade não estiver aqui, o sistema usa o próprio prefixo como nome da aba
# (ex: "JP" → aba "JP", "CAETE" → aba "CAETE").
UNIDADE_NOMES = {
    "JP": "João Pessoa",
    "ATIBAIA": "Atibaia",
    "ALEXANIA": "Alexânia",
    "ARAXÁ": "Araxá",
    "CAETÉ": "Caeté",
    "ALEGRO": "Alegro",
    "TAQUARITINGA": "Taquaritinga",
    "SALVADOR": "Salvador",
    "BELEM": "Belém",
}

# Nome da aba principal (mantém TUDO, espelho da operação)
SHEET_PRINCIPAL = "Controle"


# ── Helpers de unidade ──────────────────────────────────────────────────────
def get_unidade_from_code(code: str) -> tuple[str, str]:
    """
    Extrai a unidade a partir do código do chamado.
    Ex: "JP0000175238" → ("JP", "João Pessoa")
        "ATIBAIA00012" → ("ATIBAIA", "Atibaia")
        "CAETE00099"   → ("CAETE", "CAETE")   ← sem acento, dinâmico

    Retorna (prefixo, nome_da_aba).
    Se o código não tem prefixo claro, retorna ("OUTROS", "OUTROS").
    """
    if not code:
        return "OUTROS", "OUTROS"
    m = re.match(r"^([A-ZÀ-Ÿ]+?)(?=\d)", code)
    if not m:
        return "OUTROS", "OUTROS"
    prefixo = m.group(1).upper()
    nome = UNIDADE_NOMES.get(prefixo, prefixo)
    # Excel limita nome da aba a 31 chars
    if len(nome) > MAX_SHEET_NAME:
        nome = nome[:MAX_SHEET_NAME]
    return prefixo, nome


# ── Planilha ───────────────────────────────────────────────────────────────
def ensure_spreadsheet(path: Path) -> None:
    """Cria a planilha com a aba principal 'Controle' se não existir."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_PRINCIPAL
    ws.append(HEADERS)
    _set_widths(ws)
    wb.save(path)


def _set_widths(ws) -> None:
    """Larguras padrão das colunas (chamável pra qualquer aba nova)."""
    widths = [18, 14, 22, 30, 14, 50, 28, 22, 22, 14, 14, 12, 10, 14, 60]
    for i, w in enumerate(widths, start=1):
        col_letter = ws.cell(row=1, column=i).column_letter
        ws.column_dimensions[col_letter].width = w


def _get_or_create_sheet(wb, nome: str):
    """Retorna a aba pelo nome. Se não existir, cria com cabeçalho padrão."""
    if nome in wb.sheetnames:
        return wb[nome]
    ws = wb.create_sheet(title=nome)
    ws.append(HEADERS)
    _set_widths(ws)
    return ws


def is_already_processed(path: Path, code: str) -> bool:
    """Procura o código em TODAS as abas (anti-duplicidade)."""
    if not path.exists():
        return False
    wb = load_workbook(path)
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row and row[0] == code:
                    return True
        return False
    finally:
        wb.close()


def _find_row_status(path: Path, code: str) -> str | None:
    """Retorna o Status de um código (ou None se não existir em nenhuma aba)."""
    if not path.exists():
        return None
    wb = load_workbook(path)
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row and row[0] == code:
                    # Status está na coluna G (índice 6)
                    return row[6] if len(row) > 6 else ""
        return None
    finally:
        wb.close()


def is_in_error_state(path: Path, code: str) -> bool:
    """Retorna True se o código está na planilha MAS com status de erro."""
    status = _find_row_status(path, code)
    if not status:
        return False
    return str(status).startswith("ERRO:")


def should_process(path: Path, code: str) -> bool:
    """Retorna True se o código deve ser processado:
       - NÃO está na planilha (novo) → True
       - Está com status de ERRO → True (permite retentar)
       - Está com sucesso → False (já processado, pula)
    """
    if not is_already_processed(path, code):
        return True  # novo
    return is_in_error_state(path, code)  # erro → retenta


def register(
    path: Path,
    code: str,
    unidade: str = "",
    solicitante: str = "",
    adiantamento_anterior: str = "",
    total_attachments: int = 0,
    saved_filename: str = "",
    status: str = "",
    data_abertura: str = "",
    oc: str = "",
    data_venc: str = "",
    num_nota: str = "",
    serie: str = "",
    data_emiss: str = "",
    historico: str = "",
) -> str:
    """
    Adiciona uma linha à planilha em DUAS abas:
      1) "Controle" (visão geral — sempre TUDO)
      2) Aba da unidade (criada automaticamente se não existir)

    Se o mesmo código já existir em qualquer aba, NÃO duplica — atualiza.
    Retorna string descrevendo onde foi salvo (pro log).
    """
    ensure_spreadsheet(path)
    wb = load_workbook(path)
    try:
        # Detecta unidade e nome da aba
        prefixo, nome_aba = get_unidade_from_code(code)
        if not unidade:
            unidade = prefixo

        row = [
            code,
            unidade,
            solicitante,
            adiantamento_anterior,
            total_attachments,
            saved_filename,
            status,
            datetime.now().isoformat(timespec="seconds"),
            data_abertura,
            oc,
            data_venc,
            num_nota,
            serie,
            data_emiss,
            historico,
        ]

        # 1) Aba principal "Controle" — sempre
        if SHEET_PRINCIPAL in wb.sheetnames:
            ws_main = wb[SHEET_PRINCIPAL]
        else:
            # Migração: planilha antiga sem aba "Controle"
            ws_main = wb.active
            ws_main.title = SHEET_PRINCIPAL
            if ws_main.max_row == 0:
                ws_main.append(HEADERS)
                _set_widths(ws_main)

        # Anti-duplicidade NA ABA PRINCIPAL: se já existe, atualiza
        _upsert_row(ws_main, code, row)
        log_sheet = f"{SHEET_PRINCIPAL}"

        # 2) Aba da unidade — cria se não existir
        if nome_aba != SHEET_PRINCIPAL:
            ws_unid = _get_or_create_sheet(wb, nome_aba)
            _upsert_row(ws_unid, code, row)
            log_sheet += f" + aba '{nome_aba}'"

        wb.save(path)
        return log_sheet
    finally:
        wb.close()


def _upsert_row(ws, code: str, new_row: list) -> None:
    """
    Se o código já existir na aba (coluna A), atualiza a linha.
    Caso contrário, adiciona nova linha.
    """
    for row_idx in range(2, ws.max_row + 1):
        existing = ws.cell(row=row_idx, column=1).value
        if existing == code:
            for col_idx, val in enumerate(new_row, start=1):
                ws.cell(row=row_idx, column=col_idx).value = val
            return
    # Não existe → append
    ws.append(new_row)


def migrate_to_units(path: Path) -> int:
    """
    Função utilitária: pega todos os registros da aba "Controle" que
    ainda não foram distribuídos pras abas de unidade e distribui.

    Retorna quantos registros foram migrados.
    """
    if not path.exists():
        return 0
    wb = load_workbook(path)
    try:
        if SHEET_PRINCIPAL not in wb.sheetnames:
            return 0
        ws_main = wb[SHEET_PRINCIPAL]
        migrados = 0
        for row in ws_main.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue
            code = row[0]
            _, nome_aba = get_unidade_from_code(code)
            if nome_aba == SHEET_PRINCIPAL:
                continue
            ws_unid = _get_or_create_sheet(wb, nome_aba)
            # Já existe nessa aba?
            ja_existe = False
            for r in ws_unid.iter_rows(min_row=2, values_only=True):
                if r and r[0] == code:
                    ja_existe = True
                    break
            if not ja_existe:
                ws_unid.append(list(row))
                migrados += 1
        if migrados > 0:
            wb.save(path)
        return migrados
    finally:
        wb.close()


# ── Sanity-check rápido ────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    import logging
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    tmp = Path(tempfile.gettempdir()) / "_tracker_test.xlsx"
    if tmp.exists():
        tmp.unlink()

    ensure_spreadsheet(tmp)
    print(f"Criou planilha: {tmp}")

    log = register(tmp, code="JP0000172118", unidade="JP",
                  solicitante="Raie", adiantamento_anterior="NÃO",
                  total_attachments=3, saved_filename="NF 56.pdf",
                  status="NF encontrada (P1)",
                  data_abertura="21/09/2026 14:39:48",
                  oc="380958", data_venc="30/09/2024",
                  num_nota="56", serie="70000", data_emiss="22/09/2026",
                  historico="JP0000172118 / REF. Shows")
    print(f"  → escreveu em: {log}")

    log = register(tmp, code="ATIBAIA0000174594", unidade="ATIBAIA",
                  solicitante="Maria", adiantamento_anterior="SIM",
                  total_attachments=1, saved_filename="NF 99.pdf",
                  status="NF encontrada (P2)",
                  data_abertura="22/09/2026 10:00:00",
                  oc="987654", data_venc="15/10/2026",
                  num_nota="99", serie="80000", data_emiss="01/10/2026",
                  historico="ATIBAIA0000174594 / REF. Limpeza")
    print(f"  → escreveu em: {log}")

    assert is_already_processed(tmp, "JP0000172118") is True
    assert is_already_processed(tmp, "NOVO12345") is False
    print("✓ Anti-duplicidade OK")

    wb = load_workbook(tmp)
    print(f"\nAbas finais: {wb.sheetnames}")
    for sn in wb.sheetnames:
        ws = wb[sn]
        print(f"\n--- Aba '{sn}' ({ws.max_row - 1} registros) ---")
        for row in ws.iter_rows(values_only=True):
            print(f"  {row}")

    tmp.unlink()
    print(f"\nOK → removido {tmp}")

