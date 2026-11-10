# Integração do cadastro ANTAQ

O M Vision importa exportações de frota da ANTAQ e cruza os identificadores com o cadastro AIS local. O resultado aparece em **Cadastro de embarcações**, sem criar outra posição ou outro marcador para o mesmo barco.

## Importar pela interface

1. Inicie o servidor com a base real (`VESSEL_SOURCE=aisstream` ou `disabled`). A demonstração não aceita esta importação.
2. Abra **Cadastro de embarcações → Importar ANTAQ**.
3. Selecione a exportação oficial e informe a URL HTTPS oficial de onde ela foi obtida.
4. Clique em **Conferir prévia**. Confira linhas, registros novos/atualizados, repetições e vínculos.
5. Clique em **Importar e cruzar** para gravar.

A prévia não grava cadastros nem evidências ANTAQ. A gravação conserva o arquivo original em `data/brutos/antaq/importacoes/<sha256>.<extensão>` e registra o relatório em `antaq_imports`. Os registros normalizados ficam em `antaq_vessels`, no mesmo SQLite do cadastro real.

Formatos aceitos: CSV, XLSX e tabelas HTML, até 16 MB. Arquivos `.xls` que sejam HTML são aceitos; o formato binário antigo do Excel precisa ser salvo como CSV ou XLSX. O leitor não executa fórmulas ou macros. CSV aceita separadores comuns, UTF-8, UTF-16 com BOM e Windows-1252.

O arquivo deve conter nome da embarcação e ao menos uma coluna de IMO, MMSI, inscrição ou código ANTAQ. Cabeçalhos comuns como `Nome da Embarcação`, `Número IMO`, `MMSI`, `Inscrição`, `Empresa`, `Estaleiro`, `Comprimento`, `Boca`, `AB`, `TPB` e `Ano de Construção` são reconhecidos. Colunas não reconhecidas continuam disponíveis no arquivo original, mas não são incorporadas aos campos tratados.

## Como o cruzamento funciona

- IMO exato, com sete dígitos e dígito verificador válido, pode vincular um registro a um único cadastro AIS.
- MMSI exato pode vincular quando o IMO informado não contradiz o cadastro AIS.
- Se IMO e MMSI apontarem para barcos diferentes, ou se um IMO aparecer em vários MMSIs locais, não há associação automática.
- Nome igual não confirma identidade. Inscrições e códigos ANTAQ ajudam a reconhecer reimportações do cadastro ANTAQ; não substituem um identificador compartilhado com o AIS.
- Se um MMSI anteriormente vinculado passar a transmitir outro IMO, registros ANTAQ sem IMO ficam em conflito para revisão. Não acompanham automaticamente a nova identidade.

Os casos vinculados aparecem na linha AIS já existente, com as informações ANTAQ e suas fontes. Os demais aparecem como cadastro ANTAQ sem telemetria, com o motivo da pendência. Use **Origem do cadastro → ANTAQ aguardando vínculo / revisão** para encontrá-los. Quando chegar uma mensagem AIS com identificadores correspondentes, o sistema refaz o cruzamento automaticamente.

Reimportar o mesmo arquivo não acrescenta uma cópia do cadastro. A inscrição ou o código pode manter o vínculo entre duas exportações quando uma delas acrescenta um IMO antes ausente. Identificadores incompatíveis dentro do cadastro ANTAQ fazem a operação ser rejeitada integralmente; é preciso revisar o arquivo antes de gravar.

## Prioridade e rastreabilidade

As edições manuais mantêm prioridade. Nome, identificadores e dimensões já recebidos por AIS são preservados. Os campos cadastrais ANTAQ complementam a ficha; dados Wikidata continuam disponíveis. Evidências antigas permanecem no histórico de fontes por campo, sem alterar o histórico das posições.

Cadastros ANTAQ não entram na fila de posições, não renovam o indicador de recebimento da API de rastreamento e não são colocados no mapa sem coordenadas AIS. Esta integração não fornece localização ou histórico de movimentação da ANTAQ.

## Importar pelo terminal

Com a exportação disponível no computador, faça primeiro a prévia:

```powershell
cd C:\Dev\M_Vision
.\data\runtime\Scripts\python.exe -m mvision.antaq 'C:\caminho\frota-antaq.xlsx'
```

Depois de conferir o relatório, acrescente `--apply` para gravar:

```powershell
.\data\runtime\Scripts\python.exe -m mvision.antaq 'C:\caminho\frota-antaq.xlsx' --apply
```

`--database` permite escolher outro SQLite. `--source-url` registra o endereço oficial específico da exportação. O comando não baixa dados do portal; importa o arquivo indicado.

## APIs locais

- `GET /api/registry/antaq`: totais ANTAQ por situação do vínculo e última importação.
- `GET /api/registry?origin=antaq|aisstream|linked|unlinked`: cadastro unificado, com paginação e filtros existentes.
- `POST /api/registry/antaq/import`: JSON com `filename`, `content` em base64, `source_url` e `commit` booleano. Sem `commit: true`, devolve apenas a prévia.

## Situação da fonte

Em 10/11/2026, as tentativas de acesso ao endereço de frota legado e à página oficial retornaram falha de resolução DNS neste ambiente. Nas tentativas anteriores, o painel público alternativo também recusou o acesso automatizado. Não foi obtida uma exportação real nesta entrega e nenhum registro demonstrativo foi importado como ANTAQ.

O caminho implementado é a importação de arquivo obtido no [portal oficial de navegação marítima e de apoio](https://www.gov.br/antaq/pt-br/assuntos/navegacao/maritima-de-de-apoio). A compatibilidade com os cabeçalhos de uma exportação real deve ser confirmada assim que esse arquivo estiver disponível.
