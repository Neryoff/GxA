"""
Script auxiliar — extrai o texto de TODOS os PDFs na pasta de NFs
e mostra quais campos da NFS-e foram achados.

Uso: py extrair_texto_pdf.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import pdfplumber
except ImportError:
    print("Instale pdfplumber: py -m pip install pdfplumber")
    sys.exit(1)

import config
from main import _summarize_ref

NF_FOLDER = Path(r"C:\Users\joao.faria\Desktop\Nota Fiscal - MEIs")

pdfs = sorted(NF_FOLDER.glob("*.pdf"))
if not pdfs:
    print(f"Nenhum PDF em {NF_FOLDER}")
    sys.exit(0)

for pdf in pdfs:
    print("=" * 70)
    print(f"PDF: {pdf.name}")
    print("=" * 70)
    try:
        with pdfplumber.open(pdf) as p:
            text = "\n".join(page.extract_text() or "" for page in p.pages)
    except Exception as e:
        print(f"  ERRO: {e}")
        continue

    print(f"  Tamanho do texto: {len(text)} chars")
    print()
    # Mostra só as linhas que têm palavras-chave
    for ln in text.splitlines():
        if any(kw in ln.upper() for kw in
               ["NFS", "DPS", "SÉRIE", "SERIE", "NÚMERO", "NUMERO", "EMISS", "CHAVE"]):
            print(f"  >>> {ln}")
    print()
    # Tenta achar padrões
    import re
    # num_nota
    m = re.search(r"N[ÚU]MERODANFS[- ]?e?\s*\n?\s*(\d+)", text, re.IGNORECASE)
    print(f"  num_nota (regex DANFS): {'OK → ' + m.group(1) if m else 'NÃO ACHOU'}")
    m = re.search(r"S[ÉE]RIEDADPS\s*\n?\s*(\d+)", text, re.IGNORECASE)
    print(f"  serie   (regex SÉRIEDADPS): {'OK → ' + m.group(1) if m else 'NÃO ACHOU'}")
    m = re.search(r"(\d{2}/\d{2}/\d{4})\d{2}:\d{2}:\d{2}", text)
    print(f"  data_emiss (data+hora): {'OK → ' + m.group(1) if m else 'NÃO ACHOU'}")
    print()
