import os
import json
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configurações via variáveis de ambiente
# ---------------------------------------------------------------------------
JIRA_DOMAIN_RAW = os.environ.get("JIRA_DOMAIN", "")
JIRA_DOMAIN = (
    JIRA_DOMAIN_RAW.replace("https://", "")
    .replace("http://", "")
    .replace(".atlassian.net", "")
    .strip("/")
)
JIRA_EMAIL = os.environ.get("JIRA_EMAIL")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "SIGLA")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")  # Opcional

LAST_STATE_FILE = "last_state.json"

# Campo de story points varia por instância; tentamos os dois mais comuns
STORY_POINTS_FIELDS = ["story_points", "customfield_10016", "customfield_10028"]

# ---------------------------------------------------------------------------
# Busca de Issues no Jira
# ---------------------------------------------------------------------------

def _search(jql: str) -> list:
    """Executa uma busca JQL e retorna a lista de issues."""
    url = f"https://{JIRA_DOMAIN}.atlassian.net/rest/api/3/search/jql"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    payload = {
        "jql": jql,
        "fields": [
            "summary", "status", "assignee",
            "story_points", "customfield_10016", "customfield_10028",
            "customfield_10020",   # sprint info
            "issuetype", "priority"
        ],
        "maxResults": 200,
    }
    response = requests.post(url, headers=headers, json=payload, auth=auth)
    response.raise_for_status()
    return response.json().get("issues", [])


def get_all_issues() -> list:
    """
    Retorna issues da sprint ativa + backlog modificado nas últimas 24h.
    Evita duplicatas usando o issue key como chave.
    """
    issues_map = {}

    # Sprint ativa (todos os cards, independente de quando foram atualizados)
    try:
        sprint_issues = _search(
            f"project = {JIRA_PROJECT_KEY} AND sprint in openSprints() ORDER BY updated DESC"
        )
        for i in sprint_issues:
            issues_map[i["key"]] = i
    except Exception as e:
        print(f"Aviso: erro ao buscar sprint ativa — {e}")

    # Backlog: sem sprint, modificado ontem ou hoje
    try:
        backlog_issues = _search(
            f"project = {JIRA_PROJECT_KEY} AND sprint is EMPTY AND updated >= -1d ORDER BY updated DESC"
        )
        for i in backlog_issues:
            issues_map[i["key"]] = i
    except Exception as e:
        print(f"Aviso: erro ao buscar backlog — {e}")

    return list(issues_map.values())


# ---------------------------------------------------------------------------
# Extração de campos
# ---------------------------------------------------------------------------

def extract_story_points(fields: dict):
    """Tenta extrair story points de vários campos customizados."""
    for field in STORY_POINTS_FIELDS:
        val = fields.get(field)
        if val is not None:
            return val
    return None


def extract_sprint_name(fields: dict):
    """Extrai o nome da sprint ativa a partir do campo customfield_10020."""
    sprint_data = fields.get("customfield_10020")
    if not sprint_data:
        return None
    # Pode vir como lista
    if isinstance(sprint_data, list):
        sprint_data = sprint_data[-1]
    if isinstance(sprint_data, dict):
        return sprint_data.get("name")
    return None


def normalize_issue(issue: dict) -> dict:
    """Extrai e normaliza os campos relevantes de um issue bruto do Jira."""
    fields = issue.get("fields", {})
    assignee = fields.get("assignee")
    sprint_name = extract_sprint_name(fields)
    return {
        "key": issue["key"],
        "summary": fields.get("summary", "Sem resumo"),
        "status": fields.get("status", {}).get("name", "Desconhecido"),
        "assignee": assignee.get("displayName") if assignee else None,
        "story_points": extract_story_points(fields),
        "sprint": sprint_name,
        "link": f"https://{JIRA_DOMAIN}.atlassian.net/browse/{issue['key']}",
    }


# ---------------------------------------------------------------------------
# Estado persistido
# ---------------------------------------------------------------------------

def load_last_state() -> dict:
    if os.path.exists(LAST_STATE_FILE):
        with open(LAST_STATE_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_current_state(state: dict):
    with open(LAST_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Detecção de mudanças
# ---------------------------------------------------------------------------

def detect_changes(current: dict, previous: dict) -> list:
    """
    Compara o estado atual com o anterior de um card e retorna uma lista
    de strings descrevendo cada mudança detectada.
    """
    changes = []

    if current["status"] != previous.get("status"):
        changes.append(
            f"🔄 *Status:* `{previous.get('status', '?')}` ➡️ `{current['status']}`"
        )

    curr_assignee = current["assignee"]
    prev_assignee = previous.get("assignee")
    if curr_assignee != prev_assignee:
        if not prev_assignee:
            changes.append(f"👤 *Atribuído a:* `{curr_assignee}`")
        elif not curr_assignee:
            changes.append(f"👤 *Responsável removido* (era `{prev_assignee}`)")
        else:
            changes.append(f"👤 *Responsável:* `{prev_assignee}` ➡️ `{curr_assignee}`")

    curr_sp = current["story_points"]
    prev_sp = previous.get("story_points")
    if curr_sp != prev_sp:
        if prev_sp is None:
            changes.append(f"🎯 *Story Points definidos:* `{curr_sp}`")
        elif curr_sp is None:
            changes.append(f"🎯 *Story Points removidos* (eram `{prev_sp}`)")
        else:
            changes.append(f"🎯 *Story Points:* `{prev_sp}` ➡️ `{curr_sp}`")

    curr_sprint = current["sprint"]
    prev_sprint = previous.get("sprint")
    if curr_sprint != prev_sprint:
        if curr_sprint and not prev_sprint:
            changes.append(f"📌 *Entrou na sprint:* `{curr_sprint}`")
        elif not curr_sprint and prev_sprint:
            changes.append(f"📌 *Saiu da sprint* `{prev_sprint}` → backlog")
        else:
            changes.append(
                f"📌 *Sprint:* `{prev_sprint}` ➡️ `{curr_sprint}`"
            )

    return changes


# ---------------------------------------------------------------------------
# Sumário via Gemini AI (opcional)
# ---------------------------------------------------------------------------

def generate_ai_summary(changes_text: str) -> str | None:
    """Chama o Gemini 2.5 Flash para gerar um sumário executivo da daily."""
    if not GEMINI_API_KEY:
        return None
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "Você é um Scrum Master experiente. Com base nas mudanças abaixo no Jira, "
            "gere um resumo executivo curto para a daily em português (máximo 5 tópicos). "
            "Destaque riscos, bloqueios e avanços relevantes. Seja direto e objetivo.\n\n"
            f"Mudanças:\n{changes_text}"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-04-17",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        print(f"Aviso: erro ao chamar Gemini — {e}")
        return None


# ---------------------------------------------------------------------------
# Formatação Slack Block Kit
# ---------------------------------------------------------------------------

def _issue_block(issue: dict, detail_lines: list) -> dict:
    """Cria um bloco Slack para um card com suas mudanças."""
    detail_text = "\n".join(detail_lines) if detail_lines else ""
    assignee_text = f"  👤 `{issue['assignee']}`" if issue["assignee"] else ""
    sp_text = f"  🎯 `{issue['story_points']} pts`" if issue["story_points"] else ""
    meta = (assignee_text + sp_text).strip()

    text = f"*<{issue['link']}|{issue['key']}>* — {issue['summary']}"
    if meta:
        text += f"\n{meta}"
    if detail_text:
        text += f"\n{detail_text}"

    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text},
        "accessory": {
            "type": "button",
            "text": {"type": "plain_text", "text": "Abrir", "emoji": True},
            "url": issue["link"],
            "action_id": f"open_{issue['key']}",
        },
    }


def build_slack_payload(
    new_sprint: list,
    new_backlog: list,
    changed: list,
    ai_summary: str | None,
) -> dict:
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y às %H:%Mh UTC")
    total = len(new_sprint) + len(new_backlog) + len(changed)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🔔 Resumo Diário do Jira", "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"📅 {now}  |  *{total} alteração(ões) detectada(s)*",
                }
            ],
        },
        {"type": "divider"},
    ]

    # Bloco de IA
    if ai_summary:
        blocks += [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🤖 Análise da Daily (Gemini)*\n{ai_summary}"},
            },
            {"type": "divider"},
        ]

    # Novos cards — Sprint
    if new_sprint:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🆕 Novos na Sprint ({len(new_sprint)})*"},
        })
        for item in new_sprint:
            blocks.append(_issue_block(item["issue"], [f"🔹 Status: `{item['issue']['status']}`"]))
        blocks.append({"type": "divider"})

    # Novos cards — Backlog
    if new_backlog:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*📋 Novos no Backlog ({len(new_backlog)})*"},
        })
        for item in new_backlog:
            blocks.append(_issue_block(item["issue"], [f"🔹 Status: `{item['issue']['status']}`"]))
        blocks.append({"type": "divider"})

    # Cards com mudanças
    if changed:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🔄 Atualizações ({len(changed)})*"},
        })
        for item in changed:
            blocks.append(_issue_block(item["issue"], item["changes"]))
        blocks.append({"type": "divider"})

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "_Monitoramento automático via GitHub Actions_"}],
    })

    return {
        "text": f"🔔 Resumo Diário do Jira — {total} alteração(ões)",
        "blocks": blocks,
    }


# ---------------------------------------------------------------------------
# Envio do Webhook
# ---------------------------------------------------------------------------

# Limite seguro de blocos por mensagem do Slack (máx permitido: 50)
SLACK_MAX_BLOCKS = 48


def _chunk_blocks(blocks: list, header_blocks: list) -> list[list]:
    """
    Divide uma lista de blocos em páginas que respeitam SLACK_MAX_BLOCKS.
    O header_blocks é repetido no início de cada página.
    Retorna uma lista de listas de blocos.
    """
    pages = []
    # Blocos que não são o cabeçalho
    content = blocks[len(header_blocks):]
    page = list(header_blocks)
    for block in content:
        if len(page) + 1 > SLACK_MAX_BLOCKS:
            pages.append(page)
            page = list(header_blocks)
        page.append(block)
    if page:
        pages.append(page)
    return pages


def send_alert(payload: dict):
    """Envia o payload Block Kit ao Webhook do Slack, paginando se necessário."""
    if not WEBHOOK_URL:
        print("WEBHOOK_URL não configurado. Imprimindo payload no console:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    blocks = payload.get("blocks", [])
    # Identifica o cabeçalho (primeiros 3 blocos: header, context, divider)
    header_blocks = blocks[:3]

    if len(blocks) <= SLACK_MAX_BLOCKS:
        pages = [payload]
    else:
        chunked = _chunk_blocks(blocks, header_blocks)
        pages = []
        for i, chunk in enumerate(chunked):
            pages.append({
                "text": payload["text"] + (f" (parte {i+1}/{len(chunked)})" if len(chunked) > 1 else ""),
                "blocks": chunk
            })

    for i, page_payload in enumerate(pages):
        try:
            response = requests.post(WEBHOOK_URL, json=page_payload)
            response.raise_for_status()
        except Exception as e:
            print(f"Erro ao enviar webhook (página {i+1}): {e}")



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not all([JIRA_DOMAIN, JIRA_EMAIL, JIRA_API_TOKEN]):
        print("Erro: Variáveis de ambiente do Jira ausentes. Verifique JIRA_DOMAIN, JIRA_EMAIL e JIRA_API_TOKEN.")
        return

    print("Buscando issues no Jira (sprint ativa + backlog)...")
    try:
        raw_issues = get_all_issues()
    except Exception as e:
        print(f"Erro ao buscar issues no Jira: {e}")
        return

    print(f"{len(raw_issues)} issue(s) encontrada(s).")

    last_state = load_last_state()
    current_state = {}

    new_sprint = []     # Cards novos que estão na sprint ativa
    new_backlog = []    # Cards novos que estão no backlog
    changed = []        # Cards existentes com alguma mudança

    for raw in raw_issues:
        issue = normalize_issue(raw)
        key = issue["key"]

        # Persiste estado atual
        current_state[key] = {
            "status": issue["status"],
            "summary": issue["summary"],
            "assignee": issue["assignee"],
            "story_points": issue["story_points"],
            "sprint": issue["sprint"],
        }

        if key not in last_state:
            # Card novo — decide se está na sprint ou no backlog
            if issue["sprint"]:
                new_sprint.append({"issue": issue})
            else:
                new_backlog.append({"issue": issue})
        else:
            # Card existente — detecta mudanças
            diffs = detect_changes(issue, last_state[key])
            if diffs:
                changed.append({"issue": issue, "changes": diffs})

    if not (new_sprint or new_backlog or changed):
        print("Nenhuma mudança detectada.")
        save_current_state(current_state)
        print("Estado atualizado no last_state.json")
        return

    # Gera sumário via Gemini (se configurado)
    ai_summary = None
    if GEMINI_API_KEY:
        print("Gerando sumário com Gemini...")
        lines = []
        for item in new_sprint:
            lines.append(f"[NOVO na SPRINT] {item['issue']['key']}: {item['issue']['summary']} — {item['issue']['status']}")
        for item in new_backlog:
            lines.append(f"[NOVO no BACKLOG] {item['issue']['key']}: {item['issue']['summary']}")
        for item in changed:
            lines.append(f"[ATUALIZADO] {item['issue']['key']}: {item['issue']['summary']}")
            lines += [f"  {c}" for c in item["changes"]]
        ai_summary = generate_ai_summary("\n".join(lines))

    payload = build_slack_payload(new_sprint, new_backlog, changed, ai_summary)
    send_alert(payload)

    print(
        f"Alertas enviados: {len(new_sprint)} novo(s) na sprint, "
        f"{len(new_backlog)} novo(s) no backlog, "
        f"{len(changed)} atualização(ões)."
    )

    save_current_state(current_state)
    print("Estado atualizado no last_state.json")


if __name__ == "__main__":
    main()
