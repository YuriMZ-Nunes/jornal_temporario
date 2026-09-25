# Integração de newsletters

Este guia documenta como o projeto recebe newsletters pelo Gmail, como os extratores específicos funcionam e como adaptar o pipeline para novas fontes.

## Escopo e conceito central

O projeto possui suporte específico para duas newsletters já implementadas. Cada uma requer regras próprias de extração, pois os e-mails podem usar estruturas HTML, remetentes, links de rastreamento e blocos editoriais diferentes.

> A label `news` decide **quais e-mails entram na fila de processamento**. O parser específico decide **como o conteúdo de cada newsletter será interpretado**.

Portanto, aplicar a label `news` a uma fonte nova não a torna automaticamente compatível: é preciso implementar um extrator para ela em `extract_newsletters.py`.

## Fluxo completo

```text
Gmail (label: news)
        │
        ▼
extract_newsletters.py
  ├─ identifica a newsletter
  ├─ usa o parser específico da fonte
  └─ normaliza os itens extraídos
        │
        ▼
build_candidates.py
  └─ consolida os candidatos editoriais
        │
        ▼
editor_llm.py
  └─ seleciona, revisa e organiza o conteúdo
        │
        ├──────────────────► download_images.py
        │                         └─ baixa/trata imagens da edição
        ▼
gerar.py
  └─ monta a saída final

rodar_pipeline.py
  └─ orquestra as etapas
```

## Processo de extração

### 1. Seleção no Gmail

O Gmail é a porta de entrada. A curadoria inicial é manual: marque com a label `news` as edições que devem entrar na próxima execução.

A label não identifica a fonte, não determina a estrutura do e-mail e não transforma o conteúdo em notícia. Antes de rodar o pipeline, confirme que:

- A conta Gmail configurada no projeto tem acesso às mensagens.
- A label usada pelo código corresponde a `news`.
- O e-mail é de uma fonte já suportada ou de uma fonte cujo parser foi implementado.
- A mensagem preserva o HTML original; encaminhamentos podem alterar a estrutura esperada.

### 2. Identificação e parser

`extract_newsletters.py` recebe os e-mails elegíveis e, conceitualmente, executa estas fases:

1. Localiza as mensagens marcadas com `news`.
2. Lê metadados como remetente, assunto e data.
3. Obtém o corpo HTML.
4. Identifica a fonte por sinais conhecidos, como remetente, domínio, assunto ou estrutura HTML.
5. Direciona a mensagem para o parser daquela fonte.
6. Localiza os blocos editoriais repetidos.
7. Extrai título, URL, resumo, imagem e outros atributos disponíveis.
8. Limpa e normaliza a saída em um formato comum.
9. Descarta navegação, redes sociais, rodapés, descadastro e conteúdo promocional.

A divisão por parser é necessária porque não existe um padrão universal para newsletters. Duas fontes podem exibir título, resumo e imagem, mas organizá-los com tags, classes CSS e URLs inteiramente diferentes.

### 3. Dados normalizados e etapas posteriores

Depois da extração, os itens precisam seguir o mesmo contrato de dados esperado pelo restante do pipeline. Isso permite que `build_candidates.py` trate fontes diferentes de maneira uniforme e prepare os itens para a seleção editorial.

Em seguida, `editor_llm.py` realiza a curadoria editorial, `download_images.py` processa as imagens necessárias e `gerar.py` monta a edição final. `rodar_pipeline.py` é o ponto de entrada para executar a sequência completa.

## Adicionando uma newsletter

### Passo 1: obter amostras reais

1. Receba ao menos uma edição real da newsletter.
2. Marque a mensagem com a label `news`.
3. Guarde uma amostra para testes, idealmente com várias notícias e imagens.
4. Use a mensagem original, não um encaminhamento que possa alterar o HTML.

Uma amostra é suficiente para iniciar, mas a integração só deve ser considerada confiável depois de validar várias edições. O template pode mudar por edição, seção ou campanha.

### Passo 2: definir a assinatura da fonte

Defina como o código reconhecerá a nova fonte. Priorize sinais estáveis:

- Endereço ou domínio do remetente.
- Cabeçalhos ou identificadores previsíveis.
- Prefixo característico do assunto.
- Container, classe ou atributo HTML recorrente.

Evite sinais instáveis, como título de matéria, nome de autor ou texto que varia a cada edição.

### Passo 3: analisar o HTML

Inspecione o corpo HTML da mensagem e encontre o padrão repetido para cada item editorial. Para cada bloco, identifique:

- Título.
- URL de destino.
- Resumo ou texto de apoio.
- URL da imagem, quando houver.
- Indicadores de que o bloco é editorial, e não publicidade ou navegação.

Mapeie também o conteúdo que deve ser excluído: `unsubscribe`, preferências de e-mail, redes sociais, versão web, política de privacidade, pixels de tracking e chamadas promocionais.

### Passo 4: implementar o parser

Em `extract_newsletters.py`, crie uma função isolada para a nova newsletter. A função deve interpretar apenas a estrutura daquela fonte e devolver itens no mesmo formato usado pelos parsers existentes.

```python
def extract_minha_newsletter(html: str) -> list[dict]:
    """Extrai itens editoriais da newsletter Minha Newsletter."""
    ...
```

Antes de definir novos campos ou mudar formatos, compare o retorno das duas implementações existentes. `build_candidates.py`, `editor_llm.py` e `gerar.py` dependem do contrato de dados já estabelecido.

### Passo 5: registrar o roteamento

Adicione a nova fonte à lógica que escolhe qual parser executar. A regra deve:

1. Detectar a fonte pela assinatura estável escolhida.
2. Chamar apenas o parser correspondente.
3. Não alterar o funcionamento dos parsers existentes.
4. Informar ou registrar quando uma mensagem marcada com `news` não pertencer a nenhuma fonte conhecida.

É melhor ignorar uma newsletter sem parser e registrar o motivo do que processá-la com o parser errado e produzir dados silenciosamente incorretos.

### Passo 6: normalizar e validar

Confira que a saída segue o contrato esperado. Em especial:

- Ignore blocos sem título editorial ou URL útil.
- Normalize espaços, entidades HTML e quebras de linha.
- Resolva ou descarte URLs de rastreamento quando necessário.
- Converta URLs relativas em absolutas, caso a fonte as utilize.
- Não associe imagens decorativas à matéria.
- Evite duplicar a mesma matéria se o e-mail repetir o link.

### Passo 7: testar por camadas

Teste primeiro a extração isolada, depois o pipeline completo:

1. Execute o extrator com uma mensagem conhecida da nova fonte.
2. Compare os itens retornados com o e-mail original.
3. Valide títulos, URLs, resumos e imagens.
4. Garanta que anúncios, rodapés e descadastro não viraram candidatos.
5. Execute `build_candidates.py` e valide a estrutura resultante.
6. Execute a curadoria editorial e a geração da edição.
7. Repita os testes com várias edições da mesma newsletter.

Se nenhum item for extraído, revise primeiro a identificação da fonte e os seletores HTML. Se forem extraídos itens errados, verifique se o seletor está incluindo menus, links de navegação ou conteúdo promocional.

## Checklist

Antes de considerar a integração concluída, confirme:

- [ ] O e-mail é selecionado pela label `news`.
- [ ] A fonte é reconhecida por um identificador estável.
- [ ] Há um parser isolado em `extract_newsletters.py`.
- [ ] O parser captura somente conteúdo editorial.
- [ ] Título, URL, resumo e imagem são extraídos ou tratados quando ausentes.
- [ ] A saída mantém o contrato usado pelos parsers existentes.
- [ ] As duas newsletters já suportadas continuam funcionando.
- [ ] Foram testadas várias edições da nova fonte.

## Manutenção

Quando uma newsletter alterar seu template, comece por `extract_newsletters.py`. Compare o HTML de uma edição que falhou com uma edição que funcionava, identifique o seletor, atributo ou estrutura que mudou e altere somente o parser daquela fonte. Depois, refaça os testes da checklist para evitar regressões nas integrações existentes.
