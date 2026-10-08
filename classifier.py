"""
Regras de classificação de anexos para identificar Notas Fiscais.

Retorna prioridade 1, 2, 3 ou 0 (descartado). Apenas 1 anexo por chamado
é escolhido (maior prioridade; empate = primeiro da lista).

Prioridades
-----------
1  Melhor: nome contém "NF", "NF-e" ou "NFe" (ex: "NF 56 GUSTAVO LIMA.pdf")
2  Chave NF-e: nome tem ≥ 30 dígitos consecutivos (chave de acesso tem 44)
3  Plausível: PDF/XML sem pista forte, mas que pode ser NF
0  Descartado: OC, screenshot, número curto, extensão proibida
"""
import re
from pathlib import Path

# Extensões que NUNCA são NF (imagens, office, compactados etc.)
EXCLUDED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff",
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".txt", ".rtf", ".csv", ".log",
    ".zip", ".rar", ".7z", ".tar", ".gz",
}

# Extensões que podem ser NF
NF_EXTENSIONS = {".pdf", ".xml"}

# Regex para "OC" como palavra (OC Instalação, OC 1234, etc.) ou
# "oc " no começo do nome.
OC_PATTERN = re.compile(r"(?:^oc\b|\boc\b|\soc\s)", re.IGNORECASE)

# Regex para detectar "NF" / "NF-e" / "NFe" como palavra.
# Aceita "NF" cercado por início/fim de string, espaço, "_", "." ou "-".
NF_PATTERN = re.compile(r"(?:^|[\s_])nf(?:[\s_.\-]|$)", re.IGNORECASE)


def classify(filename: str) -> int:
    """
    Classifica um nome de arquivo.

    Returns
    -------
    int
        0 = descartado, 1 = P1 (NF no nome), 2 = P2 (chave numérica),
        3 = P3 (plausível), 99 = erro / classificação indefinida.
    """
    if not filename:
        return 0

    name_lower = filename.lower()
    ext = Path(filename).suffix.lower()
    stem = Path(filename).stem

    # ── EXCLUSÕES ─────────────────────────────────────────────────────────
    # 1. Extensão proibida
    if ext in EXCLUDED_EXTENSIONS:
        return 0

    # 2. Contém "OC" (Ordem de Compra)
    if OC_PATTERN.search(filename):
        return 0

    # 3. Filename é só dígitos curtos (ex: 206743, 387652, 209489) → provável OC.
    #    Considera letras (NÃO só dígito) como identificação textual válida,
    #    mas ignora separadores comuns (parênteses, espaços, hífen, etc.)
    def _is_only_short_digits(s: str) -> bool:
        clean = re.sub(r"[\s()_\-\.\[\]]", "", s)
        return clean.isdigit() and len(clean) <= 8

    # O sistema adiciona "{código}_" no início do nome (ex: "ATIBAIA176300_209489 (1).pdf").
    # Precisamos checar tanto o stem completo QUANTO o trecho depois do "_"
    # pra detectar se o nome ORIGINAL era só número curto.
    if _is_only_short_digits(stem):
        return 0
    if "_" in stem:
        after_underscore = stem.split("_", 1)[1]
        if _is_only_short_digits(after_underscore):
            return 0

    # 4. Captura de tela / screenshot / print / consulta / relatório genérico
    if any(kw in name_lower for kw in (
        "captura de tela", "screenshot", "print ", "print_", "screen ",
        "consulta", "optantes", "comprovante", "recibo", "relatorio ",
    )):
        return 0

    # ── PRIORIDADES ───────────────────────────────────────────────────────
    # P1: nome contém NF / NF-e / NFe
    if NF_PATTERN.search(filename):
        return 1

    # P2: ≥ 30 dígitos consecutivos no nome (chave NF-e tem 44)
    digits = re.sub(r"\D", "", filename)
    if len(digits) >= 30:
        return 2

    # P3: PDF ou XML sem pista forte
    if ext in NF_EXTENSIONS:
        return 3

    # Qualquer outra coisa cai fora
    return 0


def pick_best(filenames: list[str]) -> tuple[int | None, str | None]:
    """
    Recebe lista de nomes de anexos.
    Retorna (indice, nome) do melhor candidato, ou (None, None) se nenhum servir.

    Critérios em ordem de prioridade:
      1) Menor classe vence (P1 < P2 < P3)
      2) No empate de classe, maior SEQUÊNCIA consecutiva de dígitos vence
         (NFS-e tem chave de acesso com 44 dígitos consecutivos no nome —
          OC e outros documentos têm só números curtos)
      3) Persistindo empate, primeiro da lista
    """
    best_idx: int | None = None
    best_priority = 99
    best_digits = -1
    best_name: str | None = None

    for i, name in enumerate(filenames):
        p = classify(name)
        if p == 0 or p >= best_priority and p != best_priority:
            # Pior classe, descarta (a menos que ainda nao tenha nenhum)
            continue

        # Calcula a MAIOR sequência de dígitos consecutivos no nome
        # Ex: "209489 (1)" → 6  |  "25075072...8375" → 44
        longest_seq = 0
        for m in re.finditer(r"\d+", name):
            longest_seq = max(longest_seq, len(m.group()))

        if p < best_priority or (p == best_priority and longest_seq > best_digits):
            best_priority = p
            best_digits = longest_seq
            best_idx = i
            best_name = name

    if best_idx is None:
        return None, None
    return best_idx, best_name


# ── Sanity-check rápido: rodar `python classifier.py` para ver exemplos ────
if __name__ == "__main__":
    samples = [
        "NF 56 GUSTAVO LIMA.pdf",
        "NF-e 18_250750722683987605867000000000000000000000000.pdf",
        "250750722683987605867000000000000000000000000.pdf",
        "OC Instalação de ar condicionado AMIRRAED.pdf",
        "OC 123456.pdf",
        "206743.pdf",
        "387652.pdf",
        "Captura de tela 2026 09 09 110413.png",
        "nota_fiscal_cliente_x.pdf",
        "relatorio_mensal.pdf",
        "scan001.pdf",
        "documento_recebimento.xml",
        "anexo_sem_nome.pdf",
        "NFe_001_2024.pdf",
        "orcamento_2024.pdf",
    ]
    print(f"{'ARQUIVO':<70} {'CLASSE':<10}")
    print("-" * 80)
    for s in samples:
        c = classify(s)
        label = {0: "DESCARTADO", 1: "P1 (NF)", 2: "P2 (chave)", 3: "P3 (plausível)"}.get(c, "?")
        marker = " ←" if c == 1 else (" ←*" if c == 2 else "")
        print(f"{s:<70} {label}{marker}")
    print()
    print("* = seria a escolhida entre todas numa disputa")
    print()
    # Teste do pick_best
    candidatos = [
        "Captura de tela 2026 09 09 110413.png",
        "NF-e 18_250750722683987605867000000000000000000000000.pdf",
        "OC Instalação.pdf",
    ]
    idx, name = pick_best(candidatos)
    print(f"pick_best escolheu: {name!r} (índice {idx})")
