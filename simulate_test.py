import os
import json

# Simulação de dados para teste
def mock_get_recent_issues():
    return [
        {
            'key': 'PROJ-123',
            'fields': {
                'summary': 'Bug crítico na tela de login',
                'status': {'name': 'Em Progresso'}
            }
        },
        {
            'key': 'PROJ-456',
            'fields': {
                'summary': 'Refatorar serviço de autenticação',
                'status': {'name': 'Concluído'}
            }
        }
    ]

def simulate_test():
    print("🚀 Iniciando Simulação de Teste...")
    
    # 1. Estado inicial (vazio)
    last_state = {}
    print("1. Estado inicial carregado (vazio).")
    
    recent_issues = mock_get_recent_issues()
    current_state = {}
    alerts = []
    
    # 2. Primeira rodada: Detectando novas tarefas
    print("2. Detectando novas tarefas...")
    for issue in recent_issues:
        key = issue['key']
        summary = issue['fields']['summary']
        status = issue['fields']['status']['name']
        
        alerts.append(f"🆕 **Nova Tarefa:** [{key}] - {summary}\n🔹 **Status:** {status}")
        current_state[key] = {"status": status, "summary": summary}
    
    print(f"   Foram encontradas {len(alerts)} novas tarefas.")
    print("--- Mensagem enviada para o Webhook (Simulada) ---")
    print("🔔 **Resumo Diário do Jira** 🔔\n\n" + "\n\n".join(alerts))
    print("--------------------------------------------------\n")
    
    # 3. Segunda rodada: Simulando mudança de status
    print("3. Simulando mudança de status na próxima execução...")
    old_state = current_state.copy()
    
    # Mudando manualmente PROJ-123 de 'Em Progresso' para 'Em Revisão'
    recent_issues_v2 = [
        {
            'key': 'PROJ-123',
            'fields': {
                'summary': 'Bug crítico na tela de login',
                'status': {'name': 'Em Revisão'} # STATUS MUDOU
            }
        },
        {
            'key': 'PROJ-456',
            'fields': {
                'summary': 'Refatorar serviço de autenticação',
                'status': {'name': 'Concluído'} # STATUS IGUAL
            }
        }
    ]
    
    alerts_v2 = []
    for issue in recent_issues_v2:
        key = issue['key']
        summary = issue['fields']['summary']
        status = issue['fields']['status']['name']
        
        if key in old_state:
            old_status = old_state[key]['status']
            if old_status != status:
                alerts_v2.append(f"🔄 **Status Atualizado:** [{key}] - {summary}\n🔸 **De:** {old_status} ➡️ **Para:** {status}")
    
    if alerts_v2:
        print("--- Mensagem enviada para o Webhook (Simulada v2) ---")
        print("🔔 **Resumo Diário do Jira** 🔔\n\n" + "\n\n".join(alerts_v2))
        print("--------------------------------------------------")
    
    print("\n✅ Simulação concluída com sucesso! O script real usará a mesma lógica com dados reais do Jira.")

if __name__ == "__main__":
    simulate_test()
