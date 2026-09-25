# 📰 Jornal do Yuri: Diário de Notícias & Planejamento Pessoal

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Local AI](https://img.shields.io/badge/Ollama-Local_LLM-orange?logo=ollama&logoColor=white)](https://ollama.com/)
[![Google Cloud](https://img.shields.io/badge/Google_APIs-Gmail_|_Calendar_|_Tasks-red?logo=google&logoColor=white)](https://console.cloud.google.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Este repositório contém uma aplicação completa e automatizada para a geração de um **jornal impresso diário personalizado (formato A4)**. 

O projeto combina **integrações reais com APIs**, **Inteligência Artificial rodando localmente (LLMs)** e **geração procedural de conteúdo** com diagramação automatizada estilo jornal clássico utilizando a biblioteca **ReportLab**.

O resultado final é um arquivo PDF elegante, de alta fidelidade visual, contendo suas notícias preferidas resumidas por IA, seus compromissos e tarefas do dia, a imagem astronômica do dia da NASA e um puzzle de Sudoku diário exclusivo para começar bem o dia.

---

## ✨ Recursos do Jornal

- 📥 **Integração Real com Gmail API:** Extração automática de newsletters digitais (como a *Filipe Deschamps Newsletter* e *The News*) diretamente da caixa de entrada do usuário.
- 🤖 **Curadoria & Resumos com IA Local (Ollama):** Atua como o "editor-chefe" do jornal. Processa as notícias extraídas utilizando modelos locais (como o `qwen2.5:1.5b`), filtrando as mais importantes, traduzindo, resumindo e gerando manchetes impactantes.
- 📅 **Integração com Google Calendar & Tasks:** Insere automaticamente na barra lateral do jornal a sua agenda de amanhã, tarefas pendentes de hoje e os próximos grandes compromissos da semana.
- 🌌 **Imagem Astronômica da NASA (APOD API):** Consome a API pública da NASA para baixar a foto espacial diária e seus metadados, apresentando-a como imagem principal do jornal com sua respectiva legenda técnica traduzida.
- 🧩 **Sudoku Diário Procedural:** Gera um puzzle de Sudoku exclusivo do dia de forma determinística usando o algoritmo SHA-256 alimentado pela data de hoje, garantindo que o jogo seja novo a cada dia e resolvível sem depender de APIs externas.
- 🎨 **Diagramação Profissional (ReportLab):** Organização clássica de colunas, fontes tipográficas tradicionais de jornais (`Times-Roman` / `Helvetica`), cálculo dinâmico de redimensionamento de imagens (PIL/Pillow), linhas divisórias milimétricas e excelente fidelidade visual pronta para impressão.
- 🚀 **Orquestração em Comando Único:** Um script central robusto que unifica todo o pipeline com controle de erros, medição de tempo por etapa e propagação de parâmetros de linha de comando.

---

## 🛠️ Arquitetura do Sistema e Pipeline

A geração do jornal ocorre em um pipeline sequencial de 5 etapas, onde cada script desempenha um papel único e as saídas de um servem de entrada para o próximo:

```
[ Gmail API ] ──> 1. extract_newsletters.py ──> [ newsletter_input.json ]
                                                             │
[ JSON formatado ] <── 2. build_candidates.py <──────────────┘
       │
       └──> 3. editor_llm.py (Ollama Local LLM) ──> [ stories.json ] ───┐
                                                                       │
[ NASA APOD API ] ──> 4. nasa_apod.py ──> [ Imagens & Metadados ] ──────┼─> [ 5. gerar.py ] ──> 📄 jornal_Yuri.pdf
                                                                       │       ▲
[ Google APIs & Sudoku Procedural ] ───────────────────────────────────┘       │
      - Google Agenda (Compromissos) ───────────────────────────────────────────┤
      - Google Tasks (Tarefas pendentes) ───────────────────────────────────────┘
```

1. **`extract_newsletters.py`:** Acessa a API do Gmail via OAuth 2.0, busca mensagens recentes marcadas com a tag/marcador específica de notícias, faz o parsing do HTML/texto e gera o arquivo temporário `output/newsletter_input.json`.
2. **`build_candidates.py`:** Limpa os dados brutos e as tags HTML, isola links e imagens das newsletters, estruturando os artigos em `output/candidates.json`.
3. **`editor_llm.py`:** Envia as notícias candidatas para o Ollama local. O modelo traduz artigos do inglês se necessário, condensa textos longos, escolhe as matérias de destaque de tecnologia/mundo e gera a base `output/stories.json`.
4. **`nasa_apod.py`:** Faz a chamada HTTP para a API da NASA, escolhe a resolução apropriada da Imagem Astronômica do Dia, realiza o download seguro e salva os metadados textuais explicativos.
5. **`gerar.py`:** O núcleo de design do projeto. Coleta todas as fontes de dados, consulta as APIs do Google Calendar e do Google Tasks para colher a agenda pessoal, gera e formata o layout físico do jornal A4 com precisão milimétrica, incluindo o passatempo de Sudoku na contracapa, e renderiza o PDF final.
6. **`rodar_pipeline.py`:** Nosso orquestrador central que executa cada um dos scripts sequencialmente com feedback em tempo real e tratamento de falhas.

---

## 📂 Estrutura do Projeto

```
jornal-pessoal/
├── .gitignore               # Configurações de arquivos ignorados pelo Git (tokens, PDFs, outputs)
├── requirements.txt         # Dependências do ecossistema Python
├── rodar_pipeline.py        # Orquestrador do pipeline de comando único
├── extract_newsletters.py   # Etapa 1: Conexão e extração do Gmail
├── build_candidates.py      # Etapa 2: Parsing e estruturação das newsletters
├── editor_llm.py            # Etapa 3: Inteligência Artificial (Ollama)
├── nasa_apod.py             # Etapa 4: Download da imagem espacial diária da NASA
├── gerar.py                 # Etapa 5: Geração da agenda, Sudoku e renderização do PDF
├── download_images.py       # Módulo utilitário opcional de download de mídias adicionais
└── output/                  # Pasta gerada automaticamente (notícias, imagens, JSONs e PDFs)
```

---

## 🚀 Como Executar o Seu Próprio Jornal

Siga os passos abaixo para configurar o ambiente e rodar o pipeline na sua máquina local:

### 1. Pré-requisitos
- **Python 3.10 ou superior** instalado.
- **Ollama** instalado ([ollama.com](https://ollama.com/)).
  - Baixe o modelo padrão do projeto rodando no terminal:
    ```bash
    ollama run qwen2.5:1.5b
    ```
- **Conta Google Cloud Developer Platform:**
  - Crie um projeto no console do Google Cloud.
  - Ative as APIs: **Gmail API**, **Google Calendar API**, e **Google Tasks API**.
  - Configure a tela de consentimento do OAuth (OAuth Consent Screen) em modo de Teste e adicione o seu e-mail como usuário de teste.
  - Crie uma credencial do tipo **ID do cliente OAuth 2.0** (aplicativo de desktop).
  - Faça o download do arquivo JSON das credenciais e salve-o na raiz do projeto com o nome **`credentials.json`**.

### 2. Configurando o Ambiente Virtual
Clone este repositório para a sua máquina:
```bash
git clone https://github.com/seu-usuario/jornal-pessoal.git
cd jornal-pessoal
```

Crie e ative um ambiente virtual:
```bash
# No Linux/macOS:
python3 -m venv .venv
source .venv/bin/bin/activate

# No Windows:
python -m venv .venv
.venv\Scripts\activate
```

Instale as dependências:
```bash
pip install -r requirements.txt
```

### 3. Executando o Pipeline Completo

O projeto vem com o **`rodar_pipeline.py`**, o orquestrador unificado que simplifica a execução sequencial:

```bash
python3 rodar_pipeline.py
```

*Nota: Na primeira execução, o script abrirá automaticamente uma janela no seu navegador solicitando autorização da sua conta Google para ler os emails com marcador "News", calendário e tarefas. Após aceitar, um arquivo `token.json` será guardado localmente de forma segura para logins futuros automáticos.*

#### Opções de Linha de Comando do Orquestrador:
Você pode personalizar seu jornal através de parâmetros:

- **Mudar a Edição (Manhã vs Noite):**
  ```bash
  python3 rodar_pipeline.py --edition noite
  ```
- **Utilizar um Modelo de LLM diferente no Ollama:**
  ```bash
  python3 rodar_pipeline.py --model llama3:8b
  ```

---

## 🎨 Layout e Estética Técnica

O arquivo gerado é otimizado para **folhas A4** e desenhado com atenção à simetria visual:
- **Capa:** Logotipo tradicional centralizado, dados de cabeçalho (data, dia da semana, número da edição), manchete principal de impacto, imagem espacial da NASA com legenda, e duas notícias curadas ao lado.
- **Barra Lateral Integrada:** Mostra os compromissos de amanhã do Google Agenda de forma sequencial com horários e uma seção de checklist com suas tarefas ativas coletadas do Google Tasks.
- **Contracapa / Passatempos:** Uma página dedicada ao entretenimento matinal clássico, exibindo o **Sudoku do Dia** centralizado em escala perfeita de cinza com grade elegante de alta visibilidade pronto para caneta/lápis.

---

## 🛡️ Segurança

- O arquivo **`credentials.json`** (baixado do Google Cloud) e o token gerado **`token.json`** são estritamente pessoais e estão configurados no `.gitignore` para que **nunca** sejam expostos ou commitados no GitHub.
- As chamadas de IA rodam **100% de forma local** via Ollama, garantindo a privacidade absoluta de suas newsletters e rotina diária sem tráfego de dados para servidores externos corporativos.

---

## 📄 Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

*Desenvolvido com carinho para otimizar sua rotina e seu tempo de tela, trazendo o prazer do jornal impresso de volta para as manhãs modernas!*