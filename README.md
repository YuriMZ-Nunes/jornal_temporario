# Jornal Temporário

Pipeline em Python para transformar newsletters selecionadas no Gmail em uma edição editorial. O projeto recebe e-mails marcados com a label `news`, extrai notícias de fontes atualmente suportadas, normaliza os dados, seleciona candidatos, usa uma etapa editorial com LLM e gera o jornal final.

> **Escopo atual:** a extração é específica para duas newsletters já implementadas. A label `news` controla quais e-mails entram na fila de processamento, mas não torna automaticamente qualquer newsletter compatível. Cada fonte precisa de uma regra de extração própria.

## Visão geral do fluxo

```text
Gmail (label: news)
        │
        ▼
extract_newsletters.py
  ├─ identifica a newsletter
  ├─ aplica o parser específico da fonte
  └─ normaliza os itens extraídos
        │
        ▼
build_candidates.py
  └─ consolida e prepara candidatos editoriais
        │
        ▼
editor_llm.py
  └─ seleciona, revisa e organiza o conteúdo
        │
        ├──────────────────► download_images.py
        │                         └─ baixa/trata imagens usadas na edição
        ▼
gerar.py
  └─ monta a saída final

rodar_pipeline.py
  └─ orquestra as etapas do pipeline
```

## Como o processo funciona

### 1. Seleção dos e-mails no Gmail

O Gmail é a porta de entrada do pipeline. A curadoria inicial é manual: marque com a label `news` as edições de newsletter que devem ser consideradas para a próxima execução.

Essa label tem uma responsabilidade simples e importante: ela define **quais mensagens serão buscadas** pelo processo. Ela não identifica a estrutura interna da newsletter, não decide quais links são notícias e não adapta automaticamente HTML de fontes desconhecidas.

Antes de executar o pipeline, confirme que:

- A conta Gmail usada pelo projeto tem acesso às mensagens selecionadas.
- A label foi escrita exatamente como `news`, respeitando a configuração esperada pelo código.
- Os e-mails marcados pertencem a uma das newsletters suportadas ou já têm um extrator implementado.
- As mensagens contêm a versão HTML original; encaminhamentos e cópias podem alterar a estrutura que o parser espera.

### 2. Busca e extração das newsletters

O script `extract_newsletters.py` é o ponto mais específico do projeto. Ele busca os e-mails elegíveis e transforma o conteúdo bruto de cada mensagem em dados estruturados que as etapas posteriores conseguem consumir.

A extração segue, conceitualmente, estas fases:

1. Localizar as mensagens marcadas com `news`.
2. Ler metadados do e-mail, como remetente, assunto e data.
3. Obter o corpo HTML da mensagem.
4. Identificar a fonte da newsletter a partir de características conhecidas, como remetente, domínio, assunto ou estrutura do HTML.
5. Direcionar a mensagem para o parser correspondente.
6. Encontrar os blocos que representam notícias, links ou recomendações.
7. Extrair os campos relevantes — normalmente título, URL, resumo, imagem e informações auxiliares quando disponíveis.
8. Limpar e normalizar os campos para produzir uma estrutura consistente.
9. Ignorar elementos que não são conteúdo editorial, como links de descadastro, redes sociais, cabeçalhos, rodapés e chamadas promocionais.

A separação por parser é necessária porque newsletters não têm um formato padronizado. Dois e-mails podem conter cartões com título, descrição e imagem, mas usar tags, classes CSS, links de rastreamento, hierarquia HTML e convenções de texto completamente diferentes.

### 3. Normalização e candidatos

Depois que um parser específico encontra os itens de uma newsletter, o resultado precisa obedecer ao formato comum usado pelo restante do projeto. É essa normalização que permite que `build_candidates.py` trate conteúdos de fontes diferentes de forma uniforme.

O `build_candidates.py` consolida os itens extraídos e prepara os candidatos para a curadoria editorial. Nesta etapa, o foco deixa de ser o HTML original da newsletter e passa a ser o conteúdo já estruturado: títulos, links, resumos e demais atributos disponíveis.

### 4. Edição, imagens e geração

Com os candidatos preparados, `editor_llm.py` executa a etapa editorial assistida por LLM: o conteúdo é avaliado, selecionado e organizado para a edição.

Em paralelo ou nas etapas necessárias da execução, `download_images.py` obtém e processa imagens associadas aos itens que serão publicados. Por fim, `gerar.py` monta a saída final do jornal.

O arquivo `rodar_pipeline.py` concentra a orquestração do fluxo. Use-o como ponto de entrada quando quiser executar a sequência completa, em vez de rodar cada script isoladamente.

## As duas newsletters suportadas

O repositório foi construído em torno de duas newsletters específicas. Cada uma possui regras próprias dentro de `extract_newsletters.py`, pois os respectivos e-mails apresentam formatos distintos.

Consequentemente:

- Marcar um e-mail de uma fonte não suportada com `news` não é suficiente para extraí-lo corretamente.
- Uma alteração no template HTML de qualquer fonte pode exigir ajuste no parser correspondente.
- Parsers devem ser mantidos isolados: uma correção para uma newsletter não deve alterar a leitura da outra.

Ao fazer manutenção, prefira identificar a newsletter por um sinal estável — idealmente o remetente ou domínio — e só então aplicar seletores de HTML específicos. Usar apenas um trecho de texto frágil no corpo do e-mail tende a gerar falsos positivos quando o template muda.

## Como adicionar outra newsletter

Para adaptar o projeto a uma nova fonte, implemente um parser adicional em `extract_newsletters.py` e conecte-o à lógica que identifica a newsletter. O objetivo é converter a estrutura particular dessa fonte para o mesmo formato normalizado já consumido pelas etapas seguintes.

### Passo 1: separar uma amostra real

1. Assine ou receba ao menos uma edição real da nova newsletter.
2. Marque a mensagem com a label `news` no Gmail.
3. Preserve uma amostra do e-mail para testes, de preferência com várias notícias e imagens.
4. Verifique se a mensagem recebida é a versão final da fonte, não um e-mail encaminhado ou uma cópia que possa ter o HTML modificado.

Uma única amostra é útil para começar, mas valide posteriormente com edições de dias diferentes. Templates de newsletter podem variar por edição, seção ou campanha.

### Passo 2: estudar a assinatura da fonte

Defina como o código reconhecerá que determinada mensagem pertence à nova newsletter. Em ordem de preferência, procure sinais estáveis como:

- Endereço ou domínio do remetente.
- Cabeçalhos e identificadores previsíveis da mensagem.
- Prefixo de assunto característico.
- Estrutura HTML exclusiva, como um container, atributo ou classe recorrente.

Evite identificar a fonte usando o título de uma notícia, um nome de autor ou outro texto que muda a cada edição.

### Passo 3: inspecionar o HTML

Analise o corpo HTML e encontre o padrão que se repete para cada item editorial. Para cada bloco de notícia, descubra onde estão:

- O título.
- A URL de destino.
- O resumo ou texto de apoio.
- A URL da imagem, se existir.
- Elementos que indicam se o bloco é conteúdo editorial ou apenas navegação/publicidade.

Também procure links que não devem virar candidatos: `unsubscribe`, preferências de e-mail, redes sociais, versão web, política de privacidade, imagens de tracking e chamadas comerciais.

### Passo 4: criar um parser dedicado

No `extract_newsletters.py`, crie uma função dedicada à nova fonte. Mantenha a responsabilidade da função limitada a interpretar aquela newsletter: ela deve receber os dados ou HTML da mensagem, localizar os blocos corretos, extrair os campos necessários e devolver itens normalizados.

Use nomes explícitos, por exemplo:

```python
def extract_minha_newsletter(html: str) -> list[dict]:
    """Extrai itens editoriais da newsletter Minha Newsletter."""
    ...
```

A função deve retornar a mesma estrutura que os demais parsers já devolvem. Antes de escrever uma estrutura nova, compare os retornos das duas implementações existentes e siga o mesmo contrato de dados. Isso evita quebrar `build_candidates.py`, `editor_llm.py` ou `gerar.py`.

### Passo 5: adicionar o roteamento

Depois de implementar o parser, inclua uma condição clara na parte do código que decide qual extrator será usado. A regra deve:

1. Detectar a nova fonte pelo sinal estável escolhido.
2. Chamar somente o parser daquela fonte.
3. Preservar o comportamento das duas newsletters existentes.
4. Registrar ou reportar quando uma mensagem marcada com `news` não corresponder a nenhuma fonte conhecida.

Trate newsletters desconhecidas de forma explícita. É preferível ignorar uma fonte sem parser e registrar o motivo a tentar usar um parser errado, que pode gerar títulos, links ou imagens incorretos silenciosamente.

### Passo 6: normalizar e validar dados

Confira que cada item extraído segue o formato esperado pelo restante do pipeline. Para todos os campos, trate ausências e inconsistências de forma previsível:

- Ignore blocos sem link útil ou sem título editorial.
- Normalize espaços, entidades HTML e quebras de linha.
- Resolva ou descarte URLs de rastreamento quando isso for necessário para preservar o link final.
- Verifique se URLs relativas precisam ser convertidas em URLs absolutas.
- Não use uma imagem decorativa como imagem da notícia.
- Evite duplicar a mesma notícia quando o e-mail contém o mesmo link em mais de um lugar.

### Passo 7: testar em camadas

Teste primeiro a extração isoladamente e só depois o pipeline completo:

1. Rode o extrator com uma mensagem conhecida da nova fonte.
2. Compare os itens retornados com o e-mail original.
3. Verifique títulos, URLs, resumos e imagens.
4. Confirme que rodapés, anúncios e links de descadastro foram excluídos.
5. Execute `build_candidates.py` e confira se os dados são aceitos.
6. Execute a curadoria editorial e a geração final.
7. Repita o teste com outras edições da mesma newsletter.

Se a nova fonte não retornar itens, investigue primeiro a identificação do remetente e os seletores HTML. Se retornar itens errados, verifique se o seletor está abrangendo links de navegação ou blocos promocionais.

## Checklist de adaptação

Antes de considerar uma newsletter integrada, confirme:

- [ ] A mensagem pode ser selecionada com a label `news` no Gmail.
- [ ] A lógica reconhece a fonte por um identificador estável.
- [ ] Existe um parser isolado para a fonte em `extract_newsletters.py`.
- [ ] O parser captura apenas blocos editoriais.
- [ ] Título, URL, resumo e imagem foram extraídos ou tratados quando ausentes.
- [ ] A saída segue exatamente o contrato usado pelos parsers existentes.
- [ ] O fluxo completo funciona sem regressão nas duas newsletters já suportadas.
- [ ] Foram testadas múltiplas edições da nova fonte.

## Execução e manutenção

Para executar o fluxo completo, use `rodar_pipeline.py`, respeitando as dependências definidas em `requirements.txt` e as credenciais/configurações já exigidas pelo projeto. Para depurar uma etapa, execute o script correspondente de forma isolada e inspecione a saída antes de avançar para a etapa seguinte.

Quando uma fonte alterar seu template, comece a investigação em `extract_newsletters.py`: compare o HTML da edição nova com uma edição que funcionava, identifique o seletor ou atributo que mudou e ajuste exclusivamente o parser daquela fonte. Depois, rode a checklist de testes para garantir que a correção não afetou as demais integrações.
