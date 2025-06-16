from flask import Flask, request, jsonify
import requests
import json
import os
import logging

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Chaves de API vindas das variáveis de ambiente
# É fundamental que estas variáveis estejam definidas no ambiente onde o app roda
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
ULTRAMSG_TOKEN = os.environ.get("ULTRAMSG_TOKEN")

if not OPENROUTER_KEY:
    logging.error("❌ OPENROUTER_KEY não definida. Defina como variável de ambiente para que o app funcione.")
    exit(1) # Sai se a chave essencial não estiver presente

if not ULTRAMSG_TOKEN:
    logging.error("❌ ULTRAMSG_TOKEN não definida. Defina como variável de ambiente para que o app funcione.")
    exit(1) # Sai se a chave essencial não estiver presente

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    
    # --- MUDANÇA CRÍTICA AQUI ---
    # Loga o payload JSON bruto recebido para depuração
    logging.info(f"✨ Payload JSON bruto recebido da UltraMsg: {json.dumps(data, indent=2)}")
    # --- FIM DA MUDANÇA CRÍTICA ---

    if not data:
        logging.warning("⚠️ Requisição sem JSON no corpo. Verifique a configuração do webhook na UltraMsg.")
        return jsonify({"status": "error", "message": "Requisição sem JSON"}), 400

    # --- POTENCIAL PONTO DE AJUSTE APÓS VERIFICAR O LOG ---
    # Adapte estas linhas com base no 'Payload JSON bruto recebido' no seu log.
    # Se 'body' e 'from' estiverem dentro de um dicionário 'data' (ex: data['data']['body']),
    # você precisaria fazer: data_content = data.get("data", {}); msg = data_content.get("body", "")
    # Os exemplos abaixo assumem que 'body' e 'from' estão no nível raiz do JSON.
    msg = data.get("body", "").strip().lower()
    numero = data.get("from", "").strip()
    # --- FIM DO POTENCIAL PONTO DE AJUSTE ---

    if not msg or not numero:
        logging.warning(f"⚠️ Campos 'body' ou 'from' ausentes ou vazios no payload. Body: '{msg}', From: '{numero}'. Verifique o formato do JSON da UltraMsg.")
        return jsonify({"status": "error", "message": "Campos 'body' ou 'from' ausentes ou vazios"}), 400

    logging.info(f"📩 Mensagem recebida de {numero}: '{msg}'")
    resposta_final = ""

    try:
        # Verifica se a mensagem contém termos relacionados a fragrâncias/produtos
        if any(p in msg for p in ["fragrância", "fragrancia", "produto", "tem com", "contém", "cheiro", "com"]):
            try:
                # Timeout adicionado para a requisição de produtos
                r = requests.get("https://oracle-teste.onrender.com/produtos", timeout=10)
                r.raise_for_status() # Lança um erro para status HTTP 4xx/5xx
                produtos = r.json()
                logging.info("✔️ Produtos consultados com sucesso da API externa.")
            except requests.exceptions.RequestException as e:
                logging.error(f"❌ Erro ao consultar produtos da API externa: {e}", exc_info=True)
                resposta_final = "Desculpe, não consegui consultar nossos produtos no momento. Por favor, tente novamente mais tarde!"
                enviar_resposta_ultramsg(numero, resposta_final)
                return jsonify({"status": "ok"}) # Retorna após enviar a mensagem de erro ao usuário

            palavras_chave = [p for p in msg.split() if len(p) > 2]
            achados = []

            for prod in produtos:
                descricao = prod.get("PRO_ST_DESCRICAO", "").lower()
                codigo = prod.get("PRO_IN_CODIGO", "")
                if any(termo in descricao for termo in palavras_chave):
                    achados.append(f"{codigo} - {descricao}")
                    # Limita a busca aos 5 primeiros resultados para o prompt da IA
                    if len(achados) >= 5:
                        break

            if not achados:
                resposta_final = "Nenhum produto encontrado com base na sua descrição. Você gostaria de tentar com outras palavras-chave ou nos dar mais detalhes?"
            else:
                # Usamos chr(10) para uma nova linha no prompt da IA
                prompt = f"Com base nesses produtos:\n{chr(10).join(achados)}\nResponda ao cliente de forma simpática e resumida, dizendo o que foi encontrado e convidando-o a perguntar sobre outros produtos se não encontrar o que busca."
                resposta_final = responder_ia(prompt)
        else:
            # Se não for uma pergunta sobre fragrâncias/produtos, a IA responde de forma geral
            prompt = f"Mensagem do cliente: '{msg}'. Responda como se fosse um atendente simpático de uma loja de fragrâncias, convidando o cliente a perguntar sobre produtos ou fragrâncias específicas."
            resposta_final = responder_ia(prompt)

    except Exception as e:
        logging.error(f"❌ Erro inesperado durante o processamento da mensagem: {e}", exc_info=True)
        resposta_final = "Desculpe, ocorreu um erro interno inesperado. Nossos atendentes já foram notificados e em breve resolveremos!"

    # Envia a resposta final via UltraMsg
    enviar_resposta_ultramsg(numero, resposta_final)
    return jsonify({"status": "ok"})

def enviar_resposta_ultramsg(numero, body):
    """
    Função auxiliar para enviar respostas via UltraMsg.
    """
    try:
        resp = requests.post(
            "https://api.ultramsg.com/instance121153/messages/chat",
            data={
                "token": ULTRAMSG_TOKEN,
                "to": numero,
                "body": body
            },
            timeout=10 # Timeout para a requisição UltraMsg
        )
        resp.raise_for_status() # Lança um erro para status HTTP 4xx/5xx
        logging.info(f"✅ Resposta enviada para {numero}. UltraMsg retornou: {resp.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Erro ao enviar resposta via UltraMsg para {numero}: {e}", exc_info=True)
        # Não precisa retornar mensagem para o usuário aqui, pois já foi tratada no webhook principal

def responder_ia(prompt):
    """
    Função auxiliar para interagir com a API da OpenRouter (IA).
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openai/gpt-3.5-turbo", # Ou outro modelo da OpenRouter de sua preferência (e.g., 'mistralai/mistral-7b-instruct-v0.1')
        "messages": [
            {"role": "system", "content": "Você é um atendente educado, prestativo e simpático de uma loja de fragrâncias, focado em ajudar clientes a encontrar o que precisam de forma concisa e amigável."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7 # Ajuste a temperatura para controlar a criatividade da IA (0.0 a 1.0)
    }

    try:
        # Timeout para a requisição da IA
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body, timeout=30)
        r.raise_for_status() # Lança um erro para status HTTP 4xx/5xx
        resposta = r.json()

        if "choices" not in resposta or not resposta['choices']:
            logging.error(f"❌ Resposta da IA não contém 'choices' ou está vazia: {json.dumps(resposta, indent=2)}")
            return "Desculpe, não consegui gerar uma resposta clara da inteligência artificial no momento."

        return resposta['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Erro ao comunicar com a API da OpenRouter: {e}", exc_info=True)
        return "Desculpe, estou com dificuldades para me comunicar com a inteligência artificial agora. Por favor, tente novamente mais tarde!"
    except json.JSONDecodeError:
        logging.error(f"❌ Resposta da API da OpenRouter não é um JSON válido. Status: {r.status_code}, Resposta: {r.text}", exc_info=True)
        return "Desculpe, recebi uma resposta inválida da inteligência artificial."
    except Exception as e:
        logging.error(f"❌ Erro inesperado ao processar resposta da IA: {e}", exc_info=True)
        return "Ocorreu um problema ao gerar resposta da inteligência artificial."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"🚀 Servidor iniciado na porta {port}")
    app.run(host="0.0.0.0", port=port)
