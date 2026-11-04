# Diagnóstico inicial do cadastro — 4 de novembro de 2026

Leitura de `data/vessels.sqlite3`, sem alterar os registros. Relatório reproduzível em `data/diagnostico-inicial.json` (arquivo local, fora do Git).

## Cobertura

| Campo | Preenchidos | Cobertura |
|---|---:|---:|
| Nome | 403 | 100% |
| IMO | 166 | 41,2% |
| Indicativo | 188 | 46,7% |
| Tipo AIS conhecido | 187 | 46,4% |
| Comprimento | 188 | 46,7% |
| Largura | 186 | 46,2% |
| Estaleiro, classe/projeto, país, modelo | 0 | 0% |

Existem 403 embarcações: 216 sem tipo informado, 83 classificadas como outros, 85 de carga e 19 navios-tanque. Há 237 sem IMO; os 166 IMOs presentes têm sete dígitos e nenhum é compartilhado entre cadastros. Isso verifica formato e duplicidade, não autenticidade nem dígito verificador.

## Coleta complementar

402 consultas estão pendentes e uma terminou em erro genérico. Nenhum cadastro contém dados externos. Portanto, ainda não é possível concluir que o Wikidata tem baixa cobertura dessa amostra: quase toda a fila ainda não foi consultada.

Uma tentativa isolada com a consulta ampliada encontrou `CERTIFICATE_VERIFY_FAILED: certificate has expired`. Esse teste não identifica a origem do erro genérico anterior. A validação HTTPS foi preservada; a coleta externa precisa ser validada novamente após resolver a cadeia de certificados/data do ambiente.

## Prioridades

1. Resolver a falha HTTPS e validar um lote pequeno pelo coletor.
2. Comparar encontrados, não encontrados, ambíguos e erros, separando embarcações com IMO das identificadas apenas por MMSI.
3. Medir o ganho de cobertura de cada campo antes de selecionar uma segunda fonte.

O diagnóstico é uma fotografia inicial; executar `python -m mvision.diagnostics` produz números atualizados. Modelos comerciais continuam dependentes de confirmação; tipo no Wikidata, classe e modelo permanecem distintos.

## Validação posterior no mesmo dia

A base passou a conter 946 cadastros: 88 com comprimento inferior a 50 m, 388 de 50 a < 250 m, 71 com 250 m ou mais e 399 sem comprimento conhecido. O coletor AIS já recebe posições classe A/B sem filtro de comprimento; o filtro visual agora separa o porte médio.

O teste HTTPS via Windows retornou 200. A consulta Python foi corrigida para usar um contexto explícito de `truststore`, com verificação de certificado e hostname. Uma consulta isolada retornou dados do Emma Mærsk. Um lote real do cadastro retornou uma correspondência (Tordis Knutsen) e duas ausências de correspondência, sem erro HTTPS. O processo que já estava aberto ainda precisa ser reiniciado para carregar esse código. Os resultados anteriores de erro serão reagendados na inicialização do coletor.
