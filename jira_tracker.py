import os
import json
import requests

# Configurações via variáveis de ambiente
JIRA_DOMAIN = os.environ.get("JIRA_DOMAIN")  # ex: "minha-empresa" (de https://minha-empresa.atlassian.net)
JIRA_EMAIL = os.environ.get("JIRA_EMAIL")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "SIGLA")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

LAST_STATE_FILE = "last_state.json"

def get_recent_issues():
    """Busca as issues modificadas nas últimas 24h usando a API do Jira."""
    
    # Trata o domínio caso o usuário tenha colado a URL completa
    domain = JIRA_DOMAIN.replace("https://", "").replace("http://", "").replace(".atlassian.net", "").strip("/")
    
    # Mudando para v2 que é mais compatível em diversas instâncias
    url = f"https://{domain}.atlassian.net/rest/api/2/search"
    
    jql = f"project = '{JIRA_PROJECT_KEY}' AND updated >= '-24h'"
    
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    query = {
        'jql': jql,
        'fields': 'summary,status',
        'maxResults': 100
    }
    
    response = requests.get(url, headers=headers, params=query, auth=auth)
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

def send_alert(message):
    """Envia um alerta através do Webhook configurado (Slack/Discord)."""
    if not WEBHOOK_URL:
        print("WEBHOOK_URL não configurado. Imprimindo alerta no console:")
        print(message)
        return

    # Payload compatível com Slack
    payload_slack = {
        "text": message
    }
    
    # Payload para Discord
    payload_discord = {
        "content": message
    }
    
    try:
        # Tenta enviar como Discord primeiro
        response = requests.post(WEBHOOK_URL, json=payload_discord)
        
        # Se falhar (ex: endpoint diferente ou Bad Request do Slack), tenta formato Slack
        if response.status_code >= 400:
            response = requests.post(WEBHOOK_URL, json=payload_slack)
            
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
    
    alerts = []
    
    for issue in recent_issues:
        key = issue['key']
        summary = issue['fields'].get('summary', 'Sem resumo')
        status = issue['fields'].get('status', {}).get('name', 'Desconhecido')
        
        issue_link = f"https://{JIRA_DOMAIN}.atlassian.net/browse/{key}"
        
        # Verifica se é uma tarefa nova para o script (não estava no last_state.json)
        if key not in last_state:
            alerts.append(f"🆕 **Nova Tarefa:** [{key}]({issue_link}) - {summary}\n🔹 **Status:** {status}")
        else:
            # Tarefa já existe, verifica mudança de status
            old_status = last_state[key].get('status')
            if old_status != status:
                alerts.append(f"🔄 **Status Atualizado:** [{key}]({issue_link}) - {summary}\n🔸 **De:** {old_status} ➡️ **Para:** {status}")
        
        # Atualiza o estado da tarefa para ser salvo no final
        current_state[key] = {
            "status": status,
            "summary": summary
        }

    if alerts:
        alert_message = "🔔 **Resumo Diário do Jira** 🔔\n\n" + "\n\n".join(alerts)
        send_alert(alert_message)
        print("Alertas enviados com sucesso!")
    else:
        print("Nenhuma mudança de status ou nova tarefa detectada nas últimas 24h.")
        
    save_current_state(current_state)
    print("Estado atualizado no last_state.json")

if __name__ == "__main__":
    main()
