# movie-ticket-monitor

Bot do Telegram que busca sessões de cinema no Ingresso.com e pode monitorar
um filme até ele abrir sessão, avisando automaticamente quando isso acontece.
Inclui também um notebook (`teste.ipynb`) pra testar a busca manualmente,
sem precisar do Telegram.

## Sumário

- [Visão geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Como funciona (fluxos)](#como-funciona-fluxos)
- [Estrutura de arquivos](#estrutura-de-arquivos)
- [Requisitos e onde baixar](#requisitos-e-onde-baixar)
- [Arquivos que não são versionados (segurança)](#arquivos-que-não-são-versionados-segurança)
- [Passo a passo para rodar em casa](#passo-a-passo-para-rodar-em-casa)
- [Parâmetros configuráveis](#parâmetros-configuráveis)
- [Comandos do bot](#comandos-do-bot)
- [Operação do dia a dia](#operação-do-dia-a-dia)
- [Notebook de teste](#notebook-de-teste)

## Visão geral

Manda o nome de um filme pro bot e ele devolve as datas com sessão (a partir
de hoje, em ordem crescente); escolhendo uma data, ele lista os cinemas e
horários. Se o filme ainda não tiver nenhuma sessão (pré-venda ou ainda não
estreou), dá pra pedir `/alerta <filme>` — o bot guarda esse pedido e fica
verificando em segundo plano, avisando no chat assim que abrir.

O acesso é restrito por uma lista de usuários autorizados (`TELEGRAM_ALLOWED_USER_IDS`
no `.env`), então mesmo que alguém encontre o bot, não consegue usá-lo.

## Arquitetura

```
Telegram  <-- long polling -->  main.py
                                   |
                                   |-- registra os handlers ---> bot/handlers.py
                                   |-- registra o job periódico -> bot/monitor.py
                                   |
bot/handlers.py  ---------------> bot/ingresso.py  ---------> API do Ingresso.com
      |                                 |                      + Playwright/Chromium
      |                                 |
      +----> bot/storage.py <-----------+
                   |
                   v
           data/alerts.json
```

- **`main.py`** — ponto de entrada. Lê o `.env`, monta a aplicação do
  `python-telegram-bot`, registra os comandos/callbacks (`bot/handlers.py`) e
  o job periódico de alertas (`bot/monitor.py`), e começa o long polling
  (o bot puxa as mensagens do Telegram; nenhuma porta fica exposta).
- **`bot/ingresso.py`** — fonte de verdade da lógica de busca. Consulta a API
  pública do Ingresso.com pra achar o filme, e usa o Playwright (Chromium
  headless) pra abrir a página do filme e capturar, via interceptação de
  requisições de rede, as URLs de sessão de cada data disponível. Não tem
  nenhuma dependência do Telegram — por isso o `teste.ipynb` também importa
  direto daqui.
- **`bot/handlers.py`** — comandos e botões do Telegram (`/start`, `/help`,
  `/alerta`, `/alertas`, texto livre, cliques em botão). É a camada que
  decide *o que* o bot responde e formata as mensagens; não sabe nada sobre
  como a busca é feita internamente.
- **`bot/storage.py`** — persistência simples dos alertas em
  `data/alerts.json`, com um lock (`asyncio.Lock`) pra evitar corrida entre
  o job de monitoramento e os comandos do usuário, já que os dois rodam no
  mesmo processo.
- **`bot/monitor.py`** — roda periodicamente (intervalo configurável) e, pra
  cada alerta pendente, checa se já existe sessão disponível. Se existir,
  manda uma mensagem no chat e marca o alerta como resolvido (é um aviso
  único, não fica repetindo).
- **`teste.ipynb`** — notebook Jupyter que importa `bot/ingresso.py` e roda o
  mesmo fluxo de busca de forma interativa, via `input()`, sem precisar de
  Telegram nem Docker. Útil pra testar rapidamente se a busca ainda está
  funcionando (o site pode mudar a estrutura a qualquer momento).

## Como funciona (fluxos)

**Busca (texto livre ou uma data já com sessão em `/alerta`)**
1. Usuário manda o nome do filme.
2. `find_movies()` busca na API do Ingresso.com e filtra pelos títulos que
   batem com todas as palavras digitadas. Se houver mais de um resultado,
   o bot mostra botões pra escolher.
3. `find_sessions()` abre a página do filme com Playwright, percorre o
   seletor de datas do site e captura as URLs de sessão de cada dia,
   filtrando só as datas de hoje em diante e ordenando de forma crescente.
4. O bot mostra um botão por data disponível. Ao escolher uma,
   `fetch_theaters()` busca a API daquela data e o bot lista cinema, sala,
   tipo de sessão e horário.

**Alerta (`/alerta <filme>`)**
1. Mesma busca acima. Se já existir sessão, o bot mostra as datas (não cria
   alerta redundante).
2. Se não existir nenhuma sessão ainda, o pedido é salvo em
   `data/alerts.json` com status `pending`.
3. A cada `ALERT_CHECK_INTERVAL_MINUTES` minutos, `bot/monitor.py` roda
   `find_sessions()` de novo pra cada alerta pendente. Assim que encontrar
   sessão, manda a mensagem no chat e marca o alerta como `resolved`.

## Estrutura de arquivos

```
movie-ticket-monitor/
├── bot/
│   ├── __init__.py
│   ├── ingresso.py       # busca de filme e sessões (Playwright + API pública)
│   ├── storage.py        # persistência dos alertas (data/alerts.json)
│   ├── monitor.py        # job periódico que checa os alertas pendentes
│   └── handlers.py       # comandos e botões do Telegram
├── data/
│   ├── .gitkeep           # mantém a pasta versionada mesmo vazia
│   └── alerts.json         # criado em tempo de execução (NÃO versionado)
├── main.py                  # ponto de entrada do bot
├── teste.ipynb                # notebook de teste manual da busca
├── requirements.txt             # dependências Python
├── Dockerfile                     # imagem do bot
├── docker-compose.yml               # orquestra o container + volume de dados
├── .env.example                       # modelo das variáveis de ambiente
├── .env                                 # suas variáveis reais (NÃO versionado)
├── .gitignore
└── README.md
```

## Requisitos e onde baixar

Baixe sempre pelas fontes oficiais abaixo:

| Requisito | Necessário para | Onde baixar (oficial) |
|---|---|---|
| Python 3.13+ | Rodar local (sem Docker), ou usar o `teste.ipynb` | https://www.python.org/downloads/ |
| Docker Desktop | Rodar o bot em container (recomendado) | https://www.docker.com/products/docker-desktop/ |
| WSL2 (só Windows, exigido pelo Docker Desktop) | Backend do Docker Desktop no Windows | https://learn.microsoft.com/pt-br/windows/wsl/install (ou `wsl --install` no PowerShell como administrador) |
| Conta e app do Telegram | Criar/falar com o bot | https://telegram.org/ |
| @BotFather | Criar o bot e pegar o token | https://t.me/BotFather (bot oficial do Telegram, dentro do próprio app) |
| Git (opcional) | Clonar/versionar o projeto | https://git-scm.com/downloads |

As dependências Python (`requirements.txt`) são instaladas via `pip` e vêm
todas do [PyPI](https://pypi.org/) oficial — não precisa baixar nada manual:

- `playwright` — controla o Chromium headless que abre a página do filme.
- `requests` — chamadas HTTP pra API do Ingresso.com.
- `python-telegram-bot[job-queue]` — biblioteca oficial recomendada pra bots
  do Telegram em Python, com suporte a job periódico.
- `python-dotenv` — carrega o `.env` quando roda sem Docker.

Se for rodar **sem Docker**, depois de instalar as dependências também é
preciso baixar o navegador do Playwright (não é um download manual, é um
comando que baixa direto dos servidores oficiais do Playwright):

```powershell
python -m playwright install chromium
```

## Arquivos que não são versionados (segurança)

Esses arquivos existem no projeto rodando, mas **não vão pro git** (estão no
`.gitignore`) porque contêm segredos ou dados gerados em tempo de execução.
Cada pessoa que for rodar o bot precisa criar o próprio `.env` — ele nunca é
compartilhado nem sobe pro repositório.

| Arquivo | Por quê não versionar | Como criar |
|---|---|---|
| `.env` | Contém o token do bot — quem tiver esse arquivo controla o bot | Copie `.env.example` e preencha (veja o passo a passo abaixo) |
| `data/alerts.json` | Gerado automaticamente com os alertas de cada instalação; não faz sentido compartilhar entre ambientes diferentes | Criado sozinho na primeira vez que um alerta é salvo |
| `__pycache__/`, `*.pyc` | Bytecode compilado do Python, específico de cada máquina | Gerado automaticamente ao rodar |
| `.venv/`, `venv/` | Ambiente virtual Python local | Criado por você se optar por usar `venv` |

### Estrutura do `.env`

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
ALERT_CHECK_INTERVAL_MINUTES=30
```

- `TELEGRAM_BOT_TOKEN` — token que o @BotFather te dá ao criar o bot.
  **Nunca** compartilhe esse valor nem cole em lugar público (chat, print,
  issue do GitHub etc.) — quem tiver o token controla o bot inteiro.
- `TELEGRAM_ALLOWED_USER_IDS` — ver a tabela de [parâmetros](#parâmetros-configuráveis)
  abaixo.
- `ALERT_CHECK_INTERVAL_MINUTES` — idem.

## Passo a passo para rodar em casa

### 1. Instalar os requisitos

- Instale o [Docker Desktop](https://www.docker.com/products/docker-desktop/)
  (recomendado) **ou** o [Python 3.13+](https://www.python.org/downloads/)
  se preferir rodar sem Docker.
- No Windows, o Docker Desktop pede o WSL2. Se ele reclamar de
  "virtualisation support wasn't detected" ao abrir, abra o **PowerShell
  como Administrador** e rode `wsl --install`, depois reinicie o
  computador.

### 2. Criar o bot no Telegram

1. Abra o Telegram e fale com [@BotFather](https://t.me/BotFather).
2. Mande `/newbot`, escolha um nome e um username (precisa terminar em `bot`).
3. Guarde o token que ele devolver — você vai usar no `.env`.

### 3. Descobrir seu ID de usuário do Telegram

Fale com [@userinfobot](https://t.me/userinfobot) (ou qualquer bot
equivalente) — ele te devolve seu ID numérico. Você vai usar esse número
pra travar o bot só pro seu uso.

### 4. Baixar o projeto

Copie a pasta `movie-ticket-monitor` pra máquina onde o bot vai rodar (ou
clone via Git, se o projeto estiver num repositório remoto).

### 5. Criar o `.env`

Copie o modelo e preencha:

```powershell
copy .env.example .env
```

Edite o `.env` com o token do passo 2 e seu ID do passo 3:

```dotenv
TELEGRAM_BOT_TOKEN=coloque_o_token_aqui
TELEGRAM_ALLOWED_USER_IDS=coloque_seu_id_aqui
ALERT_CHECK_INTERVAL_MINUTES=30
```

### 6. Subir o bot

**Opção recomendada — Docker:**

```powershell
docker compose up -d --build
```

O `docker-compose.yml` monta `./data` como volume, então os alertas
sobrevivem a rebuilds/restarts do container.

**Alternativa — sem Docker:**

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

### 7. Testar

No Telegram, mande `/start` pro seu bot, depois `/help` pra ver os
comandos, e o nome de um filme em cartaz pra conferir a busca.

## Parâmetros configuráveis

Todos ficam no `.env` (ou nas variáveis de ambiente do container, se preferir
configurar direto no `docker-compose.yml`):

| Variável | O que faz | Padrão | Exemplo |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token do bot, dado pelo @BotFather | *(obrigatório, sem padrão)* | `8926034628:AAFUJg...` |
| `TELEGRAM_ALLOWED_USER_IDS` | IDs de usuário do Telegram autorizados a usar o bot, separados por vírgula. **Se ficar vazio, qualquer pessoa que achar o bot pode usá-lo** (cada busca abre um Chromium headless, então isso tem custo de recursos) | *(vazio = sem restrição)* | `383108252` ou `383108252,111222333` |
| `ALERT_CHECK_INTERVAL_MINUTES` | De quantos em quantos minutos o job de alertas verifica se abriram sessões novas | `30` | `10` (checagem mais frequente) |

Outros pontos que dá pra ajustar direto no código, se precisar:

- **Cidade da busca**: `get_sessions()`/`find_sessions()` em
  `bot/ingresso.py` recebem `city='sao-paulo'` como padrão — é o slug da
  cidade usado na URL do Ingresso.com. Pra outra cidade, troque esse valor
  (ou exponha como parâmetro do comando, se quiser evoluir o bot).
- **Limite de resultados da busca de filme**: `search_movie(query, limit=10)`
  em `bot/ingresso.py`.

## Comandos do bot

- Manda o nome de um filme (texto livre) — busca as sessões.
- `/alerta <filme>` — cria um alerta de monitoramento (ou mostra as datas se
  o filme já tiver sessão).
- `/alertas` — lista seus alertas ativos, com botão pra cancelar.
- `/help` — mostra a lista de comandos.
- `/start` — mensagem de boas-vindas.

## Operação do dia a dia

Com o bot rodando via Docker:

```powershell
docker compose logs -f          # acompanhar os logs em tempo real
docker compose restart          # reiniciar o bot (ex: depois de mudar o .env)
docker compose up -d --build    # reconstruir e subir depois de mudar o código
docker compose down             # parar e remover o container (os dados em ./data permanecem)
```

## Notebook de teste

`teste.ipynb` importa direto de `bot/ingresso.py`, então serve como um jeito
rápido de testar a busca sem precisar do Telegram nem do Docker:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Depois é só rodar a célula e responder aos `input()` (nome do filme, e depois
o número da data escolhida).
