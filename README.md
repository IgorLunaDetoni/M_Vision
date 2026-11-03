# M Vision

Integrador local de embarcações e aeronaves, com mapa mundial, histórico consultável de 30 dias e exportações CSV/Excel. Interface em português e servidor Python em `127.0.0.1`. A coleta funciona enquanto o aplicativo estiver aberto.

## Iniciar

```powershell
.\start.cmd
```

Abra **http://127.0.0.1:8000** e encerre com `Ctrl+C` no terminal. O iniciador procura Python no ambiente virtual, no PATH, no launcher `py` e no runtime local do Codex. Com Python 3.10+ disponível, também pode executar `python app.py`.

A demonstração usa apenas a biblioteca padrão do Python. Leaflet, fontes e tiles OpenStreetMap precisam de internet. Se o mapa não carregar, as consultas e a lista continuam disponíveis.

## Funcionalidades

- 36 embarcações e 6 aeronaves **fictícias**, com identificadores `DEMO-`. Posições fixas, sem simulação de deslocamento; registros demonstrativos separados dos dados reais.
- Camadas de embarcações/aeronaves, busca por nome, MMSI, IMO, ICAO e indicativo; filtros combináveis por fonte, tipo, porte e movimento.
- Filtro pela área visível ou por retângulo desenhado: clique em **Desenhar área** e depois em dois cantos do mapa. **Ir para coordenadas** centraliza o mapa; marque o filtro de área visível para restringir a consulta à região.
- Ficha com identificação, posição, velocidade em nós, direção, altitude quando disponível, fonte, horários e idade da última posição.
- Trajetória das últimas 6 horas coletadas. Intervalos acima de 30 minutos e cruzamentos da linha de mudança de data não são unidos por linhas.
- Consulta de uma data/hora nos últimos 30 dias: mostra o último estado conhecido e coletado até aquele instante, sem usar nomes/metadados recebidos no futuro e sem interpolar posições.
- Exportação **CSV ou XLSX**, com seleção de dados **tratados ou brutos**, obedecendo aos filtros. Sem período, exporta o mapa consultado; com início/fim, exporta as observações **coletadas** no intervalo, inclusive múltiplas observações do mesmo objeto.
- Favoritos no navegador. Atualização automática do mapa a cada 5 minutos; botão Atualizar para consulta imediata. No histórico, o horário consultado permanece fixo.

Os campos de data da interface usam o fuso do navegador; armazenamento e detalhes usam UTC. O histórico começa com a coleta: períodos com o computador desligado terão lacunas. Na demonstração, consultar antes da primeira inicialização devolve uma consulta vazia.

## Armazenamento em pastas locais

```text
data/
├── brutos/<fonte>/AAAA-MM-DD.jsonl
├── tratados/<fonte>/AAAA-MM-DD.csv
├── historico/
│   ├── brutos/<fonte>/AAAA-MM-DD.jsonl.gz
│   └── tratados/<fonte>/AAAA-MM-DD.csv.gz
├── exportacoes/mvision-*.csv ou *.xlsx
├── vessels.sqlite3    # índice local das fontes reais
└── demo.sqlite3       # índice local separado da demonstração
```

Cada JSONL contém a resposta original, `raw_id`, fonte e horário de coleta. Cada CSV tratado contém uma linha por atualização normalizada, estado conhecido do objeto, `record_id`, `raw_id`, identificador, tipo, posição, velocidade, direção e horários. Campos ausentes ficam vazios. Os IDs ligam cada linha tratada à mensagem bruta correspondente.

`event_at` preserva o horário original quando informado pela fonte. `updated_at` data a posição; `position_collected_at` registra quando ela foi recebida. `collected_at` data a atualização atual, inclusive dados estáticos. `timestamp_basis` informa se a posição usa horário da fonte ou da coleta. Mensagens estáticas não renovam a idade das coordenadas. Pacotes de telemetria sem posição válida permanecem nos brutos. A exportação bruta da posição atual inclui também a mensagem que originou as coordenadas, quando a última atualização foi somente de dados estáticos.

O SQLite é um índice **local** para consultas e uma fila durável de gravação. Os JSONL/CSV são gravados em lotes de até 5 segundos ou 1.000 pacotes. Uma interrupção abrupta pode perder o lote ainda em memória. Gravações de arquivos interrompidas são retomadas usando os tamanhos confirmados no índice, sem duplicar linhas.

O arquivamento roda na inicialização e a cada hora. Dias UTC completos anteriores à janela de 30 dias são compactados em gzip e verificados por SHA-256 antes de remover os arquivos ativos. A base só elimina os registros após confirmar os arquivos históricos. O dia que atravessa o limite permanece inteiro em disco; as consultas aplicam o corte exato de 30 dias. Arquivos históricos e exportações não têm exclusão automática e continuarão ocupando espaço no disco.

O banco anterior, se existir, é importado uma única vez. Seus registros recebem a marca `normalized_only`: as respostas originais antigas não podem ser recuperadas. Não há reconstrução automática do índice a partir dos arquivos nesta versão; preserve também os arquivos SQLite ao fazer backup.

Para escolher outra pasta local, defina antes de iniciar:

```powershell
$env:MVISION_DATA_DIR = 'C:\Dev\M_Vision\data'
```

A pasta deve ficar fora de `public/`. Os arquivos de dados não são servidos como arquivos estáticos. Exportações também são salvas em `data/exportacoes/`, além do download pelo navegador. CSV exportado usa UTF-8 BOM, separador `;` e proteção de texto interpretável como fórmula. XLSX preserva identificadores como texto. Os arquivos CSV canônicos em `tratados/` preservam os valores normalizados.

Respostas de aeronaves podem conter vários objetos. Na exportação bruta filtrada, `payload_scope` indica que somente os estados correspondentes foram incluídos, preservando os valores originais de cada estado. A resposta completa permanece em `brutos/`. Sem filtros e com período, a exportação bruta conserva a resposta completa. Respostas muito longas excedem o limite de texto do Excel: nesse caso, use CSV ou os JSONL originais.

## Conectar embarcações: AISStream

O adaptador está implementado, mas precisa de uma chave própria. Consulte a [documentação oficial](https://aisstream.io/documentation) para acesso, cobertura e limites. As condições de armazenamento e exportação devem ser confirmadas com o fornecedor. Nenhuma conta real foi conectada para validar esta entrega.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:VESSEL_SOURCE = 'aisstream'
$aisSecret = Read-Host 'Chave AISStream' -AsSecureString
$env:AISSTREAM_API_KEY = [System.Net.NetworkCredential]::new('', $aisSecret).Password
.\start.cmd
```

A assinatura padrão cobre o mundo, sem filtro por embarcação. O coletor lê continuamente o WebSocket comprimido; não desliga entre consultas do mapa. Recebe posições de classe A/B e dados estáticos tipo 5 e reconecta com espera progressiva. O horário `MetaData.time_utc`, quando válido, data a posição; caso contrário, registra explicitamente o horário da coleta. Credenciais e erros do fornecedor nunca são gravados nos arquivos de telemetria.

A cobertura corresponde aos receptores da fonte e pode ter lacunas, principalmente em oceanos. AIS básico não garante subtipos como LNG/LPG, contêiner ou graneleiro. Destino/status são autodeclarados. Os filtros do mapa não alteram a coleta mundial. Para restringir a própria assinatura, use `AISSTREAM_BOUNDING_BOXES`, conforme `.env.example`.

## Conectar aeronaves: OpenSky (opcional)

O adaptador faz consultas mundiais em `/states/all` a cada **300 segundos**, com OAuth2, renovação de token e espera quando o limite da API é atingido. O horário de posição usa `time_position`, não o último contato geral; a velocidade é convertida de m/s para nós. Aeronaves sem coordenadas ou horário de posição válido permanecem somente na resposta bruta.

A fonte fica desabilitada por padrão. Os [termos da OpenSky](https://opensky-network.org/about/terms-of-use) exigem licença escrita para uso operacional automatizado. Após obter o acesso e confirmar as condições:

```powershell
$env:AIRCRAFT_SOURCE = 'opensky'
$env:OPENSKY_LICENSE_CONFIRMED = 'true'
$env:OPENSKY_CLIENT_ID = 'seu-client-id'
$openSkySecret = Read-Host 'Client secret OpenSky' -AsSecureString
$env:OPENSKY_CLIENT_SECRET = [System.Net.NetworkCredential]::new('', $openSkySecret).Password
.\start.cmd
```

Mantenha `VESSEL_SOURCE=aisstream` para combinar fontes reais. Para testar só aeronaves, use `VESSEL_SOURCE=disabled`. Demonstração e fontes reais não são combinadas. Não há garantia de gratuidade da licença operacional. Consulte a [documentação oficial da API](https://openskynetwork.github.io/opensky-api/rest.html).

O arquivo `.env.example` documenta a configuração; o programa **não carrega `.env` automaticamente**. Todas as chaves ficam no servidor. Após encerrar, remova os segredos da sessão do PowerShell com `Remove-Item Env:AISSTREAM_API_KEY` e `Remove-Item Env:OPENSKY_CLIENT_SECRET`, conforme as fontes usadas.

Para voltar à demonstração:

```powershell
$env:VESSEL_SOURCE = 'demo'
$env:AIRCRAFT_SOURCE = 'disabled'
.\start.cmd
```

`COLLECTION_INTERVAL_SECONDS` aceita valores a partir de 300 para a coleta OpenSky. O mapa consulta a cada 5 minutos. Para outra porta, defina `$env:PORT = '8001'` antes de iniciar.

## APIs locais e limites

- `GET /api/objects`: posição atual ou `at` em ISO 8601 com fuso. Aceita `q`, `source`, `object_type`, `type`, `size`, `motion`, `ids` separados por vírgula e `bounds=sul,oeste,norte,leste`.
- `GET /api/vessels`: compatibilidade com a camada marítima.
- `GET /api/trajectory?object_id=...&source=...&hours=6`: posições coletadas no intervalo, até o horário `at` opcional.
- `GET /api/export`: mesmos filtros, `format=csv|xlsx`, `dataset=raw|treated`, `start`/`end` opcionais em ISO 8601 com fuso. O período considera o horário da coleta.

A lista mostra até 200 objetos; a consulta do mapa retorna até 5.000 por padrão e informa cortes. Filtre a região para consultar objetos fora desse limite. **A exportação não usa o limite de marcadores**. Toda a telemetria recebida das fontes configuradas é armazenada, independentemente desses limites de visualização. Volume mundial e longos períodos podem consumir muito disco/memória; a versão inicial não foi submetida a teste de carga mundial. Não há autenticação ou publicação: acesso apenas local.

## Estrutura e validação

```text
app.py                 Servidor local, configuração e APIs
mvision/ais.py         Adaptador AISStream
mvision/aircraft.py    Adaptador OpenSky opcional
mvision/store.py       JSONL, CSV, índice, histórico e arquivamento
mvision/exports.py     Exportação CSV e XLSX
mvision/demo.py        Embarcações e aeronaves fictícias
public/                Interface e mapa Leaflet
tests/                 Testes de integração e persistência
```

```powershell
python -m unittest discover -s tests -v
node --check public/app.js
```

Os testes cobrem normalização, associação bruto/tratado, reinicialização, consultas sem informações futuras, filtros espaciais, exportações, proteção de arquivos, recuperação de gravação interrompida e preservação de dados quando o arquivamento falha. As conexões reais precisam ser validadas com credenciais próprias. Imagens de satélite e meteorologia permanecem para a próxima etapa.

`test.py` e a pasta `APIs/` preexistentes foram preservados.

## Referências

- [Leaflet 1.9.4](https://leafletjs.com/reference.html).
- [AISStream](https://aisstream.io/documentation).
- [OpenSky REST API](https://openskynetwork.github.io/opensky-api/rest.html).
- [OpenStreetMap](https://www.openstreetmap.org/copyright) e [política de uso dos tiles](https://operations.osmfoundation.org/policies/tiles/).

As posições são indicativas e não devem ser utilizadas para navegação.
