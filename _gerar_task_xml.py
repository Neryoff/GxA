"""
Gera o arquivo XML usado pelo schtasks /Create pra criar a tarefa agendada
com DOIS gatilhos:
  1) Ao iniciar o Windows (roda assim que o PC liga)
  2) A cada 5 minutos (depois do boot, continua rodando)

Uso: py _gerar_task_xml.py "C:\\caminho\\da\\pasta" "C:\\saida.xml"
"""
import sys


def gerar(script_dir: str, xml_file: str) -> None:
    # IMPORTANTE: o CalendarTrigger precisa de <ScheduleByDay> pra definir
    # QUANDO dispara a primeira vez. Sem isso o schtasks reclama.
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        '  <RegistrationInfo>\n'
        '    <Description>GestaoX Automacao Notas Fiscais - roda ao iniciar e a cada 5 min</Description>\n'
        '  </RegistrationInfo>\n'
        '  <Triggers>\n'
        '    <BootTrigger>\n'
        '      <Enabled>true</Enabled>\n'
        '    </BootTrigger>\n'
        '    <CalendarTrigger>\n'
        '      <StartBoundary>2026-01-01T00:00:00</StartBoundary>\n'
        '      <Enabled>true</Enabled>\n'
        '      <ScheduleByDay>\n'
        '        <DaysInterval>1</DaysInterval>\n'
        '      </ScheduleByDay>\n'
        '      <Repetition>\n'
        '        <Interval>PT5M</Interval>\n'
        '        <StopAtDurationEnd>false</StopAtDurationEnd>\n'
        '      </Repetition>\n'
        '    </CalendarTrigger>\n'
        '  </Triggers>\n'
        '  <Settings>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        '    <StartWhenAvailable>true</StartWhenAvailable>\n'
        '    <AllowStartOnDemand>true</AllowStartOnDemand>\n'
        '    <Enabled>true</Enabled>\n'
        '    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>\n'
        '  </Settings>\n'
        '  <Actions Context="Author">\n'
        '    <Exec>\n'
        '      <Command>py.exe</Command>\n'
        '      <Arguments>main.py</Arguments>\n'
        f'      <WorkingDirectory>{script_dir}</WorkingDirectory>\n'
        '    </Exec>\n'
        '  </Actions>\n'
        '</Task>\n'
    )
    # schtasks /XML exige UTF-16 com BOM
    with open(xml_file, 'w', encoding='utf-16') as f:
        f.write(xml)
    print(f"XML gerado: {xml_file}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('Uso: py _gerar_task_xml.py "C:\\caminho\\da\\pasta" "C:\\saida.xml"')
        sys.exit(1)
    gerar(sys.argv[1], sys.argv[2])
