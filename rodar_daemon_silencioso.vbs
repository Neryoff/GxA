' Wrapper VBS — roda o daemon.py SEM mostrar janela preta
' O Windows executa isso a partir da pasta Inicializar

Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "py.exe """ & Replace(WScript.ScriptFullName, "rodar_daemon_silencioso.vbs", "daemon.py") & """", 0, False
