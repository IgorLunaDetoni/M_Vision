# M Vision

Integrador local de embarcações e aeronaves, com mapa mundial, histórico consultável de 30 dias e exportações CSV/Excel. Interface em português e servidor Python em `127.0.0.1`. A coleta funciona enquanto o aplicativo estiver aberto.

## Iniciar

Para iniciar **M Vision + coleta AISStream** juntos, usando a chave salva no Windows:

```powershell
.\start-local.cmd
```

Também pode dar duplo clique em `start-local.cmd`. O iniciador usa o ambiente Python local disponível e chama `start-aisstream.ps1`, que recupera a credencial salva. Se ainda não houver chave, solicita o cadastro com entrada oculta. Se o terminal não aceitar colar a chave, cadastre antes com `.\save-aisstream-key.ps1 -Clipboard`. As dependências de `requirements.txt` precisam estar instaladas no ambiente usado.

Abra **http://127.0.0.1:8000** (ou a porta definida em `PORT`). A coleta AISStream e o servidor rodam juntos enquanto essa janela estiver aberta; encerre com `Ctrl+C`. O servidor e os dados ficam no computador; a coleta AISStream precisa de internet. Em caso de erro, a janela permanece aberta para leitura da mensagem.

Para iniciar a demonstração com a configuração padrão:

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
- Favoritos no navegador. Atualização automática do mapa a cada 50 segundos; botão Atualizar para consulta imediata. No histórico, o horário consultado permanece fixo.
- No topo do mapa, **Último recebimento da API** mostra a data/hora local da mensagem de rastreamento mais recente recebida pelo servidor. É verificado a cada 10 segundos, inclusive no histórico, e independe dos filtros ou do horário em que a tela foi consultada. Inclui mensagens brutas sem posição válida, preserva o horário entre reinicializações e não conta demonstração/importações normalizadas como recebimento real. O detalhe ao passar o mouse mostra os horários por fonte.

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

O filtro **Tipo de embarcação** inclui pesca (AIS 30), rebocador/reboque (31, 32 e 52), passageiros (60–69), veleiro (36) e recreio (37), além de carga e navios-tanque. A classificação aparece na lista, na ficha e nas cores do mapa; os filtros também se aplicam às exportações. Ela depende do tipo transmitido pela embarcação, sem inferência pelo nome. Mensagens `StaticDataReport` classe B complementam nome, tipo, indicativo e dimensões, associadas pelo MMSI. Embarcações já armazenadas serão classificadas conforme novas mensagens estáticas chegarem; o histórico anterior é preservado.

O filtro de porte separa pequeno (`compact`, comprimento > 0 e < 50 m), médio (`medium`, 50 a < 250 m), grande (`large`, ≥ 250 m) e não informado (`unknown`). São faixas operacionais do aplicativo, não uma classificação oficial. A API mantém `small` como compatibilidade com o filtro anterior de comprimento < 250 m. **Todos os portes** inclui as embarcações sem dimensões. O porte não restringe a assinatura AIS: posições classe A/B já são coletadas independentemente do comprimento.

No mapa, **Verificar dados desta área** consulta todas as embarcações com posição no trecho visível, sem os filtros da lista e sem o limite de marcadores. Mostra totais, posições de até 15 minutos/24 horas, porte médio e comprimento ausente. No histórico, as idades são relativas ao horário consultado. Também informa quando a região visível não está integralmente contida em uma das caixas da assinatura configurada. Isso não mede a disponibilidade dos receptores do fornecedor: um porto vazio no mapa significa ausência de posições recebidas/armazenadas nessa área, não ausência de embarcações. A API correspondente é `GET /api/coverage?bounds=sul,oeste,norte,leste`, com `at` opcional.

Com as dependências instaladas, execute `.\start-aisstream.ps1` para iniciar a fonte real. Na primeira execução, o iniciador solicita a chave com entrada oculta e a salva no **Gerenciador de Credenciais do Windows**, no destino `M_Vision/AISStream`. Nas próximas execuções, usa a chave salva automaticamente. O segredo fica fora dos arquivos do projeto e do Git. Crie sua chave na conta do [AISStream](https://aisstream.io/); conectar o Git no VS Code não configura essa credencial. Acesse `http://127.0.0.1:8000` após iniciar.

Para cadastrar ou trocar a chave sem iniciar o app:

```powershell
.\save-aisstream-key.ps1
```

O comando pede o segredo com entrada oculta, sem incluí-lo no histórico de comandos. Para verificar somente se há uma chave salva, use `.\save-aisstream-key.ps1 -Status`. Para remover a chave local, use `.\save-aisstream-key.ps1 -Remove`. A remoção local não revoga a chave na conta AISStream.

Cole somente o valor da chave, sem rótulos ou comandos. Espaços, tabulações e quebras de linha nas extremidades são removidos antes de salvar; espaços internos e caracteres de controle restantes são rejeitados sem alterar a credencial anterior.

Se colar com `Ctrl+V` produzir erro de caractere de controle, copie a chave no painel AISStream e execute `.\save-aisstream-key.ps1 -Clipboard`. Essa opção lê a área de transferência local diretamente, sem mostrar a chave nem passá-la como argumento do comando. O comando não limpa a área de transferência; depois de salvar, copie outro texto para substituir a chave.

A credencial pertence ao usuário atual do Windows e permanece neste computador, inclusive entre reinicializações. O armazenamento usa `CredWriteW`/`CredReadW` nativos, sem dependências extras ou arquivo `.env` com o segredo. Aplicativos executados com a mesma conta do Windows podem acessar suas credenciais: esse mecanismo protege o armazenamento local, não substitui a proteção da conta/computador. Durante a execução, a chave é passada ao processo do servidor pelo ambiente; o iniciador restaura o ambiente anterior ao encerrar. Se `AISSTREAM_API_KEY` já estiver definida na sessão, ela tem prioridade e não substitui automaticamente a credencial salva. [Referência da Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw).

O `.gitignore` também exclui `.env` e suas variantes locais (preservando `.env.example`), pastas `secrets/` e `credentials/`, além de arquivos `*.secret` e `*.credentials.xml`. O Gerenciador de Credenciais fica fora da árvore do repositório.

O adaptador está implementado, mas precisa de uma chave própria. Consulte a [documentação oficial](https://aisstream.io/documentation) para acesso, cobertura e limites. As condições de armazenamento e exportação devem ser confirmadas com o fornecedor. Nenhuma conta real foi conectada para validar esta entrega.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:VESSEL_SOURCE = 'aisstream'
$aisSecret = Read-Host 'Chave AISStream' -AsSecureString
$env:AISSTREAM_API_KEY = [System.Net.NetworkCredential]::new('', $aisSecret).Password
.\start.cmd
```

A assinatura padrão cobre uma área aproximada do Brasil e águas próximas, delimitada por `AISSTREAM_BOUNDING_BOXES=[[[-40,-80],[10,-25]]]` (sudoeste e nordeste em latitude/longitude). É uma caixa retangular, não uma fronteira marítima, e inclui partes de países vizinhos e do Atlântico. Ajuste essa variável para outra região; as coordenadas devem seguir o formato documentado em `.env.example`. O coletor lê continuamente o WebSocket comprimido; não desliga entre consultas do mapa. Recebe posições de classe A/B e dados estáticos tipo 5 e reconecta com espera progressiva. O horário `MetaData.time_utc`, quando válido, data a posição; caso contrário, registra explicitamente o horário da coleta. Credenciais e erros do fornecedor nunca são gravados nos arquivos de telemetria.

A cobertura corresponde aos receptores da fonte e pode ter lacunas, principalmente em oceanos. AIS básico não garante subtipos como LNG/LPG, contêiner ou graneleiro. Destino/status são autodeclarados. Os filtros do mapa não alteram a área de coleta. Para restringir a própria assinatura, use `AISSTREAM_BOUNDING_BOXES`, conforme `.env.example`.

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

`COLLECTION_INTERVAL_SECONDS` aceita valores a partir de 300 para a coleta OpenSky. O mapa consulta a cada 50 segundos. Para outra porta, defina `$env:PORT = '8001'` antes de iniciar.

## APIs locais e limites

### Cadastro ANTAQ e cruzamento com AIS

Em **Cadastro de embarcações → Importar ANTAQ**, selecione uma exportação CSV, XLSX ou HTML oficial, confira a prévia e importe. O cruzamento usa IMO/MMSI exatos e compatíveis; registros vinculados complementam a linha AIS existente. Nomes iguais não são unidos automaticamente. Reimportações não acrescentam uma cópia do cadastro, e conflitos ficam indicados para revisão. As edições manuais, os arquivos originais e as fontes por campo são preservados. A demonstração não recebe registros reais por esse fluxo.

A importação está implementada; a carga real depende de uma exportação da ANTAQ, ainda não obtida devido à indisponibilidade de acesso ao portal neste ambiente. Esses arquivos acrescentam dados cadastrais, sem criar coordenadas ou trajetórias. Veja formatos, regras de associação, APIs e comandos em [Integração ANTAQ](docs/antaq-integration.md).

### Cadastro local e coleta de informações complementares

Abra **Cadastro de embarcações** no topo do mapa, ou `/registry.html`. A tabela inclui nome, MMSI, IMO, tipo AIS, indicativo, dimensões, destino, modelo comercial, fabricante/estaleiro, classe/projeto, país de registro informado pelo Wikidata, observações e fontes. Há busca, filtros por tipo/resultado da consulta e páginas de 100 registros. A tela atualiza a cada 50 segundos. O botão **Editar** permite adicionar modelo e informações verificadas, com URL da fonte; valores manuais têm prioridade de exibição e são preservados pelo coletor.

O cadastro fica na tabela SQLite `vessel_registry`, dentro de `data/vessels.sqlite3`, e não é apagado pelo arquivamento da telemetria após 30 dias. A inicialização importa as embarcações AIS reais já existentes no índice; novas mensagens alimentam o cadastro em lotes junto à persistência da telemetria. Dados de demonstração e aeronaves não entram no cadastro. Alterações de IMO invalidam resultados externos; quando um IMO conhecido muda, informações manuais anteriores são guardadas no histórico interno de identidade para não serem atribuídas à nova identidade.

Ao iniciar com `VESSEL_SOURCE=aisstream`, o coletor complementar consulta o [serviço público do Wikidata](https://www.wikidata.org/wiki/Wikidata:Data_access) em segundo plano, por IMO exato ou, na ausência dele, por MMSI exato. Consulta no máximo uma embarcação por vez, com intervalo mínimo de 10 segundos. Registra encontrado, não encontrado, ambíguo ou erro, além da data e URL de origem. Resultados são consultados novamente após 30 dias; falhas têm espera para nova tentativa e limites HTTP recebem espera global. Reservas interrompidas são retomadas após 5 minutos. `VESSEL_ENRICHMENT_ENABLED=false` desabilita a coleta complementar.

A cobertura do Wikidata é limitada, especialmente para barcos menores. O coletor preenche fabricante, classe/projeto e país quando disponíveis; **modelo comercial permanece vazio até haver confirmação manual**, pois a classe naval não equivale ao modelo. Não há busca aproximada pelo nome nem raspagem de sites comerciais. O cadastro atual não altera consultas históricas de posição.

O coletor também consulta tipo declarado no Wikidata (`P31`), operador (`P137`), criação/construção (`P571`), entrada em serviço (`P729`) e arqueação bruta (`P1093`, índice GT sem unidade de massa). Criação e entrada em serviço são campos separados; não se infere o ano de construção de uma data de comissionamento. Operador e país informados pelo Wikidata não garantem vigência atual. Múltiplos valores são preservados, sem escolher arbitrariamente um operador como atual. A consulta usa ramos independentes para evitar multiplicação entre propriedades e rejeita respostas que atinjam o limite de resultados.

Na tela de cadastro, **Diagnóstico** mostra cobertura por campo e resultados das consultas para toda a base, independentemente dos filtros da tabela. **Histórico de fontes por campo** mostra valores, origem, URL, propriedade Wikidata e última coleta conhecida. Divergências entre valores manuais e públicos são sinalizadas; o manual mantém prioridade. A tabela permanente `vessel_field_sources` preserva valores anteriores e separa evidências por identidade MMSI/IMO. Não contém as referências bibliográficas originais de cada declaração do Wikidata: a origem registrada é a página da entidade consultada. Dados legados são identificados nos metadados; datas de coleta por campo desconhecidas permanecem vazias.

O diagnóstico também pode ser executado sem iniciar o servidor, abrindo o banco somente para leitura:

```powershell
.\data\runtime\Scripts\python.exe -m mvision.diagnostics --output data/diagnostico-atual.json
```

Use `--database` para escolher outro índice. O relatório contém total, resultados de consulta, tipos, cobertura efetiva por campo (manual → externo → AIS), identificadores ausentes/com formato inválido, IMOs compartilhados e erros. O formato do IMO não substitui validação do dígito verificador. Valores `unknown` e dimensões zero não contam como preenchidos. O diagnóstico inicial está documentado em `docs/diagnostico-base-2026-11-04.md`.

Para executar um lote manual, respeitando a fila e os intervalos:

```powershell
.\data\runtime\Scripts\python.exe -m mvision.enrichment --limit 10
```

Se usar seu próprio ambiente, substitua o executável pelo Python correspondente. O argumento `--database` permite escolher outro índice SQLite. O cadastro precisa ter sido criado pela inicialização do aplicativo. Falhas de rede/certificado aparecem na coluna de consulta e não interrompem a coleta AIS; a validação HTTPS permanece habilitada.

Para o HTTPS das consultas ao Wikidata, `truststore` usa a validação nativa de certificados do sistema operacional, sem modificar o comportamento SSL global. No Windows, isso permite construir a cadeia usando CryptoAPI em vez de depender apenas da cadeia obtida pelo OpenSSL. Certificados e nomes de servidor continuam sendo verificados; sem a dependência, usa-se a validação padrão do Python. Na validação local de 04/11/2026, o Windows aceitou a cadeia que o OpenSSL rejeitava como expirada, e as consultas reais passaram com o contexto nativo. Consulte a [documentação do truststore](https://truststore.readthedocs.io/en/stable/).

Após atualizar as dependências, reinicie o app no terminal que contém sua chave AIS. A inicialização do coletor complementar reagenda somente os erros de certificado HTTPS; outros erros e limites HTTP mantêm seus prazos. A fila é processada gradualmente, com intervalo mínimo de 10 segundos. Para reagendar essas falhas e validar um lote manual:

```powershell
.\data\runtime\Scripts\python.exe -m pip install -r requirements.txt
.\data\runtime\Scripts\python.exe -m mvision.enrichment --retry-tls-errors --limit 3
```

Se a falha persistir mesmo com `truststore`, confira a data/hora e a cadeia de certificados do sistema/rede; a aplicação não desativa a validação HTTPS.

- `GET /api/registry`: cadastro atual, com `q`, `type`, `status`, `limit` (1–500) e `offset`.
- `GET /api/registry/diagnostics`: diagnóstico completo da base atual, sem filtros ou paginação.
- `POST /api/registry`: edição manual em JSON `{ "mmsi": "...", "fields": { "model": "...", "manufacturer": "...", "vessel_class": "...", "notes": "...", "source_url": "https://..." } }`.

- `GET /api/objects`: posição atual ou `at` em ISO 8601 com fuso. Aceita `q`, `source`, `object_type`, `type`, `size`, `motion`, `ids` separados por vírgula e `bounds=sul,oeste,norte,leste`.
- `GET /api/receipts`: `last_received_at` e `last_received_by_source`, em UTC, da recepção real de mensagens de rastreamento. Os mesmos campos acompanham `/api/objects`. Sem mensagens reais, o horário é `null`; o horário de consulta da API não o substitui.
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
