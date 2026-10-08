"""
Validação automática da Data de Vencimento.

REGRA DOS 7 DIAS + FLUXO DE SEGUNDA E QUARTA
─────────────────────────────────────────────
1) Pega a data de ABERTURA do chamado (campo "Data" da grade / Detalhes).
   A hora é IGNORADA — só importa o dia.
2) Soma 7 dias completos → data mínima bruta.
3) Ajusta essa data mínima para o próximo dia de fluxo (segunda ou quarta):
     Seg → mantém Seg
     Ter → joga pra Qua (mesma semana)
     Qua → mantém Qua
     Qui → joga pra Seg seguinte
     Sex → joga pra Seg seguinte
     Sáb → joga pra Seg seguinte
     Dom → joga pra Seg seguinte
4) Compara com a data informada pela pessoa:
     - Se a data informada < data mínima  → corrige pra data mínima
     - Se a data informada cai em dia que não é Seg/Qua → ajusta pra próximo Seg/Qua
     - Se a data informada é Seg ou Qua E >= data mínima → mantém
5) Se a pessoa não informou nenhuma data → preenche com a data mínima válida.

NÃO mexer no resto: essa lógica só afeta o que vai pra coluna "Data de venc."
"""

from datetime import date, datetime, timedelta
import re


# ── helpers internos ────────────────────────────────────────────────────────
def _parse_date(s: str | None) -> date | None:
    """Tenta vários formatos comuns: dd/mm/yyyy, yyyy-mm-dd, dd-mm-yyyy, dd/mm/yy."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Fallback: extrai qualquer data dd/mm/yyyy do texto
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _next_flow_day(d: date) -> date:
    """
    Ajusta d para a próxima data de fluxo (segunda ou quarta) >= d.
      Mon (0) → Mon
      Tue (1) → Wed (mesma semana)
      Wed (2) → Wed
      Thu (3) → próxima Mon
      Fri (4) → próxima Mon
      Sat (5) → próxima Mon
      Sun (6) → próxima Mon
    """
    wd = d.weekday()
    if wd in (0, 2):  # Seg ou Qua
        return d
    if wd == 1:       # Ter → Qua
        return d + timedelta(days=1)
    # Qui/Sex/Sáb/Dom → próxima Seg
    days_to_mon = (7 - wd) % 7
    if days_to_mon == 0:
        days_to_mon = 7
    return d + timedelta(days=days_to_mon)


def _is_flow_day(d: date) -> bool:
    return d.weekday() in (0, 2)  # Seg ou Qua


_WD_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


# ── API pública ─────────────────────────────────────────────────────────────
def validate_due_date(open_date_str: str, user_due_date_str: str) -> tuple[str, str, dict]:
    """
    Valida a data de vencimento segundo a regra dos 7 dias + Seg/Qua.

    Retorna:
      (data_final, motivo, debug)
        data_final : string "dd/mm/yyyy" (ou "" se indefinido)
        motivo     : "ok" | "corrigida_anterior" | "corrigida_dia_invalido"
                     | "preenchida_min" | "indefinida"
        debug      : dict com open_date, min_date, user_date, final_date,
                     open_weekday_pt, min_weekday_pt, final_weekday_pt
    """
    debug = {
        "open_date": open_date_str or "",
        "open_weekday_pt": "",
        "user_date": user_due_date_str or "",
        "min_date": "",
        "min_weekday_pt": "",
        "final_date": "",
        "final_weekday_pt": "",
    }

    # Sem referência de abertura → não dá pra validar, mantém o que vier
    if not open_date_str:
        debug["final_date"] = user_due_date_str or ""
        return user_due_date_str or "", "indefinida", debug

    open_d = _parse_date(open_date_str)
    if not open_d:
        debug["final_date"] = user_due_date_str or ""
        return user_due_date_str or "", "indefinida", debug

    debug["open_weekday_pt"] = _WD_PT[open_d.weekday()]

    # Data mínima = abertura + 7 dias, ajustada pra fluxo
    raw_min = open_d + timedelta(days=7)
    min_date = _next_flow_day(raw_min)
    debug["min_date"] = min_date.strftime("%d/%m/%Y")
    debug["min_weekday_pt"] = _WD_PT[min_date.weekday()]

    # Se a pessoa não informou nada → preenche com a mínima
    if not user_due_date_str:
        debug["final_date"] = min_date.strftime("%d/%m/%Y")
        debug["final_weekday_pt"] = _WD_PT[min_date.weekday()]
        return min_date.strftime("%d/%m/%Y"), "preenchida_min", debug

    user_d = _parse_date(user_due_date_str)
    if not user_d:
        # Não conseguiu parsear → mantém como está e deixa o humano ver
        debug["final_date"] = user_due_date_str
        return user_due_date_str, "indefinida", debug

    # Regra principal: data é válida se for Seg/Qua E >= mínimo
    if _is_flow_day(user_d) and user_d >= min_date:
        debug["final_date"] = user_d.strftime("%d/%m/%Y")
        debug["final_weekday_pt"] = _WD_PT[user_d.weekday()]
        return user_due_date_str, "ok", debug

    # Caso contrário, ajusta
    if user_d < min_date:
        # Anterior ao mínimo → usa o mínimo
        debug["final_date"] = min_date.strftime("%d/%m/%Y")
        debug["final_weekday_pt"] = _WD_PT[min_date.weekday()]
        return min_date.strftime("%d/%m/%Y"), "corrigida_anterior", debug

    # user_d >= min_date mas não é dia de fluxo → ajusta pra próximo Seg/Qua
    final = _next_flow_day(user_d)
    debug["final_date"] = final.strftime("%d/%m/%Y")
    debug["final_weekday_pt"] = _WD_PT[final.weekday()]
    return final.strftime("%d/%m/%Y"), "corrigida_dia_invalido", debug


def extract_open_date_from_row(cell_texts: list[str]) -> str:
    """
    Recebe os textos de TODAS as células de uma linha da grade e tenta
    extrair a 'Data de abertura' (coluna "Data" do Gestão X).

    A coluna "Data" tipicamente tem formato "dd/mm/yyyy hh:mm:ss".
    A coluna "Previsão" também tem data, mas vem DEPOIS da "Data" no header.
    Como "Data" aparece ANTES de "Previsão" na ordem das colunas, basta
    pegar a PRIMEIRA célula que casa com `dd/mm/yyyy hh:mm:ss`.
    Se não achar nenhuma com hora, pega a primeira que só tem data.
    """
    # 1ª preferência: dd/mm/yyyy hh:mm:ss (com hora)
    pat_with_time = re.compile(r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})")
    for txt in cell_texts:
        if not txt:
            continue
        m = pat_with_time.search(txt)
        if m:
            return m.group(1)

    # 2ª preferência: só dd/mm/yyyy — pega o PRIMEIRO
    pat_date_only = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
    for txt in cell_texts:
        if not txt:
            continue
        m = pat_date_only.search(txt)
        if m:
            return m.group(1)

    return ""
