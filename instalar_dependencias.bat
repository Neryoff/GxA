@echo off
echo ===========================================
echo  Instalando dependencias extras para OCR
echo ===========================================
echo.

echo [1/3] Instalando pacotes Python...
python -m pip install --user pytesseract pdf2image

echo.
echo [2/3] Verificando se tesseract (binario) esta instalado...
where tesseract >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ========================================================
    echo  ATENCAO: tesseract NAO esta instalado no sistema!
    echo ========================================================
    echo.
    echo Baixe e instale o tesseract OCR:
    echo   https://github.com/UB-Mannheim/tesseract/wiki
    echo.
    echo IMPORTANTE: na instalacao, marque:
    echo   - Additional language data - Portuguese
    echo   - Additional language data - English
    echo.
    echo Depois rode este script novamente para verificar.
    pause
    exit /b 1
) else (
    echo  tesseract OK em:
    tesseract --version 2>&1 | findstr "tesseract"
)

echo.
echo [3/3] Verificando idioma portugues...
tesseract --list-langs 2>&1 | findstr /I "por eng" >nul
if %errorlevel% neq 0 (
    echo.
    echo ========================================================
    echo  ATENCAO: tesseract nao tem idioma portugues!
    echo ========================================================
    echo.
    echo Reinstale o tesseract marcando:
    echo   - Additional language data - Portuguese
    echo   - Additional language data - English
    pause
    exit /b 1
) else (
    echo  Idiomas OK
)

echo.
echo ===========================================
echo  OK! Dependencias instaladas.
echo ===========================================
pause
