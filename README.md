# Booking × OPERA — GitHub Actions

Automação sem painel próprio para extrair reservas da Booking, consultar os
valores no OPERA e publicar a conciliação como artefato do GitHub Actions. O
navegador fica visível na máquina Windows que executa o runner.

## Configuração no GitHub

1. Crie um repositório privado e envie este projeto.
2. Em **Settings → Actions → Runners**, adicione um runner `self-hosted` Windows
   com os rótulos padrão `self-hosted`, `windows` e `x64`.
3. Na máquina do runner, instale Chrome/Chromium e inicie o runner por `run.cmd`
   dentro da sessão do usuário conectado. Não o instale como serviço: serviços
   do Windows não conseguem mostrar o navegador na área de trabalho.
4. Em **Settings → Secrets and variables → Actions**, crie estes *Repository secrets*:
   - `BOOKING_USERNAME`
   - `BOOKING_PASSWORD`
   - `OPERA_USERNAME`
   - `OPERA_PASSWORD`
   - `OPERA_HOTEL` (nome exato exibido no seletor do OPERA)
5. Abra **Actions → Conciliação Booking x OPERA → Run workflow**.
6. Acompanhe o navegador na máquina do runner e baixe o artefato
   `booking-opera-<número>` ao final.

O agendamento padrão executa de segunda a sexta às 10:00 UTC (07:00 no horário
de Brasília, UTC-3). Cron do GitHub sempre usa UTC.

## Execução local

Requisitos: Python 3.12, `uv` e Chrome/Chromium compatível.

```powershell
Copy-Item .env.example .env
# Carregue as variáveis da forma apropriada ao seu ambiente.
uv sync
uv run python main.py --output-dir output --fail-on-divergence
```

O navegador é visível por padrão (`BOOKING_HEADLESS=false`). A variável pode ser
alterada para `true` caso futuramente a execução visual deixe de ser necessária.

## Códigos de saída

- `0`: automação concluída (sem divergências quando a opção de falha é usada);
- `1`: configuração inválida ou falha geral da automação;
- `2`: divergência/erro de reserva com `--fail-on-divergence`.

Os arquivos gerados em `output/` são:

- `reservas_booking.csv`;
- `conferencia_booking_opera.csv`;
- `conferencia_booking_opera.xlsx`.

O relatório final segue o modelo `Sheet0`, com as colunas `Reservation number`,
`Booked on`, `Arrival`, `Departure`, `Guest name`, `Rooms`, `Persons`,
`Room nights`, `Commission %`, valores, `Status` e `OBSERVAÇÕES`. Reservas
agrupadas têm valores e quantidades somados. Cancelamentos sem cobrança são
marcados como `CANCELLED`, no-shows sem cobrança como `NO_SHOW`, e diferenças
registram os valores Booking e OPERA em `OBSERVAÇÕES`.

## Limitações operacionais

O runner precisa permanecer ligado, com usuário conectado, `run.cmd` ativo e
acesso de rede à Booking e ao OPERA (incluindo VPN, se necessária). MFA, CAPTCHA
ou aprovação interativa ainda exigirão intervenção no navegador. Por segurança,
use runner dedicado e aceite apenas workflows de branches confiáveis.

## Testes

```powershell
uv run python -m unittest discover -s tests -v
```
