from flask import Flask, request, jsonify
import requests
import json
import os
import logging
import threading
from googleapiclient.discovery import build # Importa para Google Custom Search API

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__) # CORRIGIDO: __name__ com dois underscores

# Chaves de API vindas das variáveis de ambiente
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
ULTRAMSG_TOKEN = os.environ.get("ULTRAMSG_TOKEN")

# --- CORRIGIDO E PADRONIZADO: Variáveis para a API do Google Custom Search ---
# Os nomes usados aqui DEVEM ser EXATAMENTE iguais aos nomes configurados no Render.com (case-sensitive)
SEARCH_API_KEY = os.environ.get("Search_API_KEY") # Agora sem "_VAR"
SEARCH_CX = os.environ.get("Search_CX")         # Agora sem "_VAR"
# --- FIM DA CORREÇÃO ---

if not OPENROUTER_KEY:
    logging.error("❌ OPENROUTER_KEY não definida. Defina como variável de ambiente para que o app funcione.")
    exit(1)

if not ULTRAMSG_TOKEN:
    logging.error("❌ ULTRAMSG_TOKEN não definida. Defina como variável de ambiente para que o app funcione.")
    exit(1)

# --- CORRIGIDO: Verificação das chaves do Google Search (sem erro de sintaxe) ---
if not SEARCH_API_KEY or not SEARCH_CX: # <-- CORRIGIDO: espaço entre a variável e 'or'
    logging.error("❌ Variáveis Search_API_KEY ou Search_CX não definidas. A pesquisa web não funcionará.")
    exit(1)


# Função para realizar a pesquisa web com Google Custom Search
def perform_google_custom_search(query):
    try:
        # --- CORRIGIDO: Usando a variável corretamente definida ---
        service = build("customsearch", "v1", developerKey=SEARCH_API_KEY)
        res = service.cse().list(q=query, cx=SEARCH_CX, num=3).execute() # num=3 para 3 resultados
        
        snippets = []
        if 'items' in res:
            for item in res['items']:
                if 'snippet' in item:
                    title = item.get('title', 'Título indisponível')
                    link = item.get('link', 'Link indisponível')
                    snippet_text = item['snippet']
                    snippets.append(f"- {title}: {snippet_text} (Fonte: {link})")
        return snippets
    except Exception as e:
        logging.error(f"❌ Erro ao realizar pesquisa com Google Custom Search API: {e}", exc_info=True)
        return []


# Função para processar a mensagem em segundo plano
def processar_mensagem_em_segundo_plano(ultramsg_data, numero, msg):
    logging.info(f"📩 [Processamento em Segundo Plano] Mensagem recebida de {numero}: '{msg}'")
    resposta_final = ""

    try:
        # Se a mensagem contém termos relacionados a fragrâncias/produtos
        if any(p in msg for p in ["fragrância", "fragrancia", "produto", "tem com", "contém", "cheiro", "com"]):
            try:
                # Timeout ajustado para 100 segundos
                r = requests.get("https://oracle-teste-1.onrender.com/produtos", timeout=100)
                r.raise_for_status()
                produtos = r.json()
                logging.info("✔️ Produtos consultados com sucesso da API externa.")
            except requests.exceptions.RequestException as e:
                logging.error(f"❌ Erro ao consultar produtos da API externa: {e}", exc_info=True)
                resposta_final = "Oh-oh! 😟 Parece que não consegui acessar nossos produtos agora. O universo das fragrâncias está um pouquinho tímido! Que tal tentar de novo mais tarde, ou me contar mais sobre o que você procura? Estou aqui pra ajudar! ✨"
                enviar_resposta_ultramsg(numero, resposta_final)
                return # Sai da função de segundo plano

            palavras_chave = [p for p in msg.split() if len(p) > 2]
            achados = []

            for prod in produtos:
                descricao = prod.get("PRO_ST_DESCRICAO", "").lower()
                codigo = prod.get("PRO_IN_CODIGO", "")
                if any(termo in descricao for termo in palavras_chave):
                    achados.append(f"Código: {codigo} - Descrição: {descricao}") # Formato mais claro para IA
                    if len(achados) >= 5:
                        break

            if not achados:
                resposta_final = "Que pena! 😔 Não encontrei nenhuma fragrância com essa descrição. Mas não desanime! Nossos produtos são um universo de aromas! Que tal tentar com outras palavras-chave ou me dar mais detalhes sobre o cheiro que você imagina? Estou pronta para a próxima busca! 🕵️‍♀️💖"
            else:
                prompt = f"""Com base nestes produtos incríveis que encontrei para você:
{chr(10).join(achados)}
Por favor, como a Iris, a assistente virtual super animada da Ginger Fragrances, responda ao cliente de forma **super simpática, vibrante e concisa**, listando os códigos e descrições dos produtos encontrados **apenas uma vez, em um formato divertido e fácil de ler**! Convide-o com entusiasmo a perguntar sobre outras maravilhas perfumadas se ainda não for exatamente o que ele busca! ✨"""
                resposta_final = responder_ia(prompt)
        # Se a mensagem NÃO é sobre fragrâncias/produtos, tenta pesquisa web
        else:
            search_query = msg
            snippets = perform_google_custom_search(search_query) # Chamada à função de pesquisa web
            
            search_results_text = ""
            if snippets:
                search_results_text = "\n".join(snippets)

            if search_results_text:
                prompt = f"""Mensagem do cliente: '{msg}'.
                Informações da web encontradas:
                {search_results_text}
                
                Com base na mensagem do cliente e nas informações da web (se relevantes), como a Iris, a assistente virtual da Ginger Fragrances, responda de forma super simpática, animada e útil. Se a pergunta for geral, use as informações da web para responder de forma concisa. Se for sobre fragrâncias e a pesquisa não ajudar a encontrar um produto específico, convide-o a perguntar sobre notas olfativas ou outros detalhes. Lembre-se de sua personalidade única e responda apenas uma vez! ✨"""
            else:
                prompt = f"Mensagem do cliente: '{msg}'. Responda como a Iris, a assistente virtual da Ginger Fragrances, se apresentando e convidando-o a perguntar sobre fragrâncias específicas ou notas olfativas. Parece que não encontrei informações adicionais na web para isso no momento. 🤔 Que tal explorar o mundo dos cheirinhos? 😊"
            
            resposta_final = responder_ia(prompt)

    except Exception as e:
        logging.error(f"❌ Erro inesperado durante o processamento da mensagem em segundo plano: {e}", exc_info=True)
        resposta_final = "Oh-oh! 🥺 Algo inesperado aconteceu enquanto eu estava buscando a resposta perfeita para você! Mas não se preocupe, o time da Ginger Fragrances já foi avisado e estamos correndo pra resolver isso! Por favor, tente novamente em alguns instantes. Sua satisfação é nosso cheirinho favorito! 😉"

    enviar_resposta_ultramsg(numero, resposta_final)


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    
    logging.info(f"✨ Payload JSON bruto recebido da UltraMsg: {json.dumps(data, indent=2)}")

    if not data:
        logging.warning("⚠️ Requisição sem JSON no corpo. Verifique a configuração do webhook na UltraMsg.")
        return jsonify({"status": "error", "message": "Requisição sem JSON"}), 200 # Alterado para 200 OK para evitar reenvios

    ultramsg_data = data.get("data", {})
    msg = ultramsg_data.get("body", "").strip().lower()
    numero = ultramsg_data.get("from", "").replace("@c.us", "").strip()

    if not msg or not numero:
        logging.warning(f"⚠️ Campos 'body' ou 'from' ausentes ou vazios no payload. Body: '{msg}', From: '{numero}'. Verifique o formato do JSON da UltraMsg.")
        return jsonify({"status": "error", "message": "Campos 'body' ou 'from' ausentes ou vazios"}), 200 


    # Inicia o processamento em um thread separado
    thread = threading.Thread(target=processar_mensagem_em_segundo_plano, args=(ultramsg_data, numero, msg))
    thread.start()

    # Retorna 200 OK imediatamente para a UltraMsg
    return jsonify({"status": "received", "message": "Mensagem recebida e processamento iniciado em segundo plano."}), 200

def enviar_resposta_ultramsg(numero, body):
    try:
        resp = requests.post(
            "https://api.ultramsg.com/instance121153/messages/chat",
            data={
                "token": ULTRAMSG_TOKEN,
                "to": numero,
                "body": body
            },
            timeout=10
        )
        resp.raise_for_status()
        logging.info(f"✅ Resposta enviada para {numero}. UltraMsg retornou: {resp.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Erro ao enviar resposta via UltraMsg para {numero}: {e}", exc_info=True)

def responder_ia(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "google/gemini-2.0-flash-001",
        "messages": [
            {
                "role": "system",
                "content": "🎉 Olá! Eu sou a Iris, a assistente virtual da Ginger Fragrances! ✨ Meu papel é ser sua melhor amiga no mundo dos aromas: sempre educada, prestativa, simpática e com um toque de criatividade! 💖 Fui criada para ajudar nossos incríveis vendedores e funcionários a encontrar rapidinho os códigos das fragrâncias com base nas notas olfativas que os clientes amam, tipo maçã 🍎, bambu 🎋, baunilha 🍦 e muito mais! Além disso, eu posso **realizar pesquisas na web para te ajudar com perguntas mais gerais**! Sempre que alguém descrever um cheirinho ou uma sensação, minha missão é indicar as fragrâncias que mais se aproximam disso, **listando os códigos correspondentes de forma clara, única, rápida e super eficiente, e sendo o mais concisa possível na resposta. Responda apenas uma vez.** Vamos descobrir o aroma perfeito? 😊"
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3 # Ajustado para um equilíbrio entre criatividade e concisão
    }

    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body, timeout=30)
        r.raise_for_status()
        resposta = r.json()

        if "choices" not in resposta or not resposta['choices']:
            logging.error(f"❌ Resposta da IA não contém 'choices' ou está vazia: {json.dumps(resposta, indent=2)}")
            return "Ops! 🤷‍♀️ Não consegui gerar uma resposta agora! Parece que a magia dos aromas está um pouquinho distante. Tente de novo! 😉"

        return resposta['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Erro ao comunicar com a API da OpenRouter: {e}", exc_info=True)
        return "Ah, não! 😩 Estou com um pequeno probleminha pra falar com o universo da inteligência artificial agora. Por favor, me dê um minutinho e tente de novo mais tarde! Prometo caprichar na próxima! ✨"
    except json.JSONDecodeError:
        logging.error(f"❌ Resposta da IA não é um JSON válido. Status: {r.status_code}, Resposta: {r.text}", exc_info=True)
        return "Eita! 😲 Recebi uma resposta estranha do meu cérebro virtual! Será que a internet deu uma embolada? Tenta mais uma vez, por favor! 🙏"
    except Exception as e:
        logging.error(f"❌ Erro inesperado ao processar resposta da IA: {e}", exc_info=True)
        return "Puxa! 😱 Aconteceu um erro inesperado enquanto eu estava pensando na sua resposta! Mas calma, já estou avisando os gênios da Ginger Fragrances pra eles darem um jeitinho! Me manda um 'oi' de novo pra gente tentar! 😉"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"🚀 Servidor iniciado na porta {port}")
    app.run(host="0.0.0.0", port=port)
