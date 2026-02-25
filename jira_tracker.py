import os
import json
import requests

# Configurações via variáveis de ambiente
JIRA_DOMAIN_RAW = os.environ.get("JIRA_DOMAIN", "")
# Trata o domínio caso o usuário tenha colado a URL completa
JIRA_DOMAIN = JIRA_DOMAIN_RAW.replace("https://", "").replace("http://", "").replace(".atlassian.net", "").strip("/")

JIRA_EMAIL = os.environ.get("JIRA_EMAIL")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "SIGLA")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

LAST_STATE_FILE = "last_state.json"

def get_recent_issues():
    """Busca as issues modificadas nas últimas 24h usando a API do Jira."""
    
    # Endpoint atual do Jira Cloud (/search foi depreciado e retorna 410)
    url = f"https://{JIRA_DOMAIN}.atlassian.net/rest/api/3/search/jql"
    
    # Sem aspas no project key para JQL simples
    jql = f"project = {JIRA_PROJECT_KEY} AND updated >= -1d ORDER BY updated DESC"
    
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    payload = {
        "jql": jql,
        "fields": ["summary", "status"],
        "maxResults": 100
    }
    
    response = requests.post(url, headers=headers, json=payload, auth=auth)
    response.raise_for_status()
    
    return response.json().get('issues', [])

def load_last_state():
    """Carrega o estado anterior das tarefas do arquivo JSON."""
    if os.path.exists(LAST_STATE_FILE):
        with open(LAST_STATE_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_current_state(state):
    """Salva o estado atual das tarefas no arquivo JSON."""
    with open(LAST_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)

def build_slack_payload(new_issues, updated_issues):
    """Constrói um payload rico usando Slack Block Kit."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y às %H:%Mh UTC")

    total = len(new_issues) + len(updated_issues)
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🔔 Resumo Diário do Jira", "emoji": True}
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"📅 {now}  |  *{total} alteração(ões) detectada(s)*"}]
        },
        {"type": "divider"}
    ]

    # Seção: Novas Tarefas
    if new_issues:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🆕 Novas Tarefas ({len(new_issues)})*"}
        })
        for issue in new_issues:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*<{issue['link']}|{issue['key']}>* — {issue['summary']}\n🔹 Status: `{issue['status']}`"
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Abrir no Jira", "emoji": True},
                    "url": issue['link'],
                    "action_id": f"open_{issue['key']}"
                }
            })
        blocks.append({"type": "divider"})

    # Seção: Atualizações de Status
    if updated_issues:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🔄 Status Atualizados ({len(updated_issues)})*"}
        })
        for issue in updated_issues:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*<{issue['link']}|{issue['key']}>* — {issue['summary']}\n🔸 `{issue['old_status']}` ➡️ `{issue['status']}`"
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Abrir no Jira", "emoji": True},
                    "url": issue['link'],
                    "action_id": f"open_{issue['key']}"
                }
            })
        blocks.append({"type": "divider"})

    # Rodapé
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "_Monitoramento automático via GitHub Actions_"}]
    })

    return {
        "text": f"🔔 Resumo Diário do Jira — {total} alteração(ões)",  # fallback para notificações
        "blocks": blocks
    }


def send_alert(payload):
    """Envia o payload Block Kit ao Webhook do Slack."""
    if not WEBHOOK_URL:
        print("WEBHOOK_URL não configurado. Imprimindo alerta no console:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    try:
        response = requests.post(WEBHOOK_URL, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"Erro ao enviar webhook: {e}")

def main():
    if not all([JIRA_DOMAIN, JIRA_EMAIL, JIRA_API_TOKEN]):
        print("Erro: Variáveis de ambiente do Jira ausentes. Verifique JIRA_DOMAIN, JIRA_EMAIL e JIRA_API_TOKEN.")
        return

    try:
        recent_issues = get_recent_issues()
    except Exception as e:
        print(f"Erro ao buscar issues no Jira: {e}")
        return

    last_state = load_last_state()
    current_state = dict(last_state) # Começa com o estado anterior
    
    new_issues = []
    updated_issues = []

    for issue in recent_issues:
        key = issue['key']
        summary = issue['fields'].get('summary', 'Sem resumo')
        status = issue['fields'].get('status', {}).get('name', 'Desconhecido')
        issue_link = f"https://{JIRA_DOMAIN}.atlassian.net/browse/{key}"

        issue_data = {"key": key, "summary": summary, "status": status, "link": issue_link}

        if key not in last_state:
            new_issues.append(issue_data)
        else:
            old_status = last_state[key].get('status')
            if old_status != status:
                updated_issues.append({**issue_data, "old_status": old_status})

        current_state[key] = {"status": status, "summary": summary}

    if new_issues or updated_issues:
        payload = build_slack_payload(new_issues, updated_issues)
        send_alert(payload)
        print(f"Alertas enviados: {len(new_issues)} nova(s), {len(updated_issues)} atualização(ões).")
    else:
        print("Nenhuma mudança de status ou nova tarefa detectada nas últimas 24h.")

    save_current_state(current_state)
    print("Estado atualizado no last_state.json")

if __name__ == "__main__":
    main()
