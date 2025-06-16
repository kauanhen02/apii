from flask import Flask, request, jsonify
import requests
import json
import os
import logging # Importa a biblioteca de logging

# Configuração básica de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Carrega chaves de API de variáveis de ambiente
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
ULTRAMSG_TOKEN = os.environ.get("ULTRAMSG_TOKEN")

# Verifica se as chaves foram carregadas
if not OPENROUTER_KEY:
    logging.error("OPENROUTER_KEY não definida como variável de ambiente. O servidor não iniciará.")
    exit(1) # Sai se a chave essencial não estiver presente
if not ULTRAMSG_TOKEN:
    logging.error("ULTRAMSG_TOKEN não definida como variável de ambiente. O servidor não iniciará.")
    exit(1) # Sai se a chave essencial não estiver presente

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        logging.warning("Requisição recebida sem JSON no corpo.")
        return jsonify({"status": "error", "message": "Requisição sem JSON"}), 400

    msg = data.get("body", "").lower()
    numero = data.get("from", "")

    if not msg or not numero:
        logging.warning(f"Dados essenciais ausentes na requisição. Body: '{msg}', From: '{numero}'")
        return jsonify({"status": "error", "message": "Dados essenciais (body ou from) ausentes"}), 400

    logging.info(f"Mensagem recebida de {numero}: '{msg}'")

    resposta_final = ""

    try:
        # Verifica se a mensagem contém termos relacionados a fragrâncias/produtos
        if any(p in msg for p in ["fragrância", "fragrancia", "produto", "tem com", "contém", "com cheiro de", "com"]):
            try:
                r = requests.get("https://oracle-teste.onrender.com/produtos")
                r.raise_for_status()  # Lança um erro para status 4xx/5xx
                produtos = r.json()
                logging.info("Produtos consultados com sucesso da API externa.")
            except requests.exceptions.RequestException as e:
                logging.error(f"Erro ao consultar produtos da API externa: {e}")
                resposta_final = "Desculpe, não consegui consultar nossos produtos no momento. Por favor, tente novamente mais tarde!"
                # Envia esta resposta e retorna para evitar processamento adicional
                enviar_resposta_ultramsg(numero, resposta_final)
                return jsonify({"status": "ok"})

            palavras_chave = [p for p in msg.split() if len(p) > 2]
            achados = []
            for prod in produtos:
                descricao = prod.get("PRO_ST_DESCRICAO", "").lower()
                codigo = prod.get("PRO_IN_CODIGO", "")
                for termo in palavras_chave:
                    if termo in descricao:
                        achados.append(f"{codigo} - {descricao}")
                        break # Encontrou um termo, passa para o próximo produto

            if not achados:
                resposta_final = "Nenhum produto encontrado com base na sua descrição. Você gostaria de tentar com outras palavras-chave?"
            else:
                # Limita a 5 produtos para o prompt da IA
                prompt = f"Com base nesses produtos:\n{achados[:5]}\nResponda ao cliente de forma simpática e resumida, dizendo o que foi encontrado e convidando-o a perguntar sobre outros produtos se não encontrar o que busca."
                resposta_final = responder_ia(prompt)
        else:
            # Se não for uma pergunta sobre fragrâncias, a IA responde de forma geral
            prompt = f"Mensagem recebida: '{msg}'. Responda como se fosse um atendente simpático em uma loja de fragrâncias, convidando o cliente a perguntar sobre produtos ou fragrâncias específicas."
            resposta_final = responder_ia(prompt)

    except Exception as e:
        logging.error(f"Erro inesperado durante o processamento da mensagem: {e}", exc_info=True)
        resposta_final = "Desculpe, houve um erro interno inesperado. Nossos atendentes já foram notificados e em breve resolveremos!"

    # Enviar resposta via UltraMsg
    enviar_resposta_ultramsg(numero, resposta_final)

    return jsonify({"status": "ok"})

def enviar_resposta_ultramsg(numero, body):
    try:
        resp = requests.post("https://api.ultramsg.com/instance121153/messages/chat", data={
            "token": ULTRAMSG_TOKEN,
            "to": numero,
            "body": body
        })
        resp.raise_for_status() # Levanta um erro para respostas 4xx/5xx

        logging.info(f"Resposta enviada via UltraMsg para {numero}. Status: {resp.status_code}, Resposta: {resp.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao enviar resposta via UltraMsg para {numero}: {e}", exc_info=True)

def responder_ia(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openai/gpt-3.5-turbo", # Ou outro modelo da OpenRouter de sua preferência
        "messages": [
            {"role": "system", "content": "Você é um assistente atencioso e prestativo em uma loja de fragrâncias, focado em ajudar clientes a encontrar o que precisam de forma concisa e amigável."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7 # Ajuste a temperatura para controlar a criatividade da IA
    }

    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body, timeout=30) # Adiciona timeout
        r.raise_for_status() # Levanta um erro para respostas 4xx/5xx
        resposta = r.json()

        if "choices" not in resposta or not resposta['choices']:
            logging.error(f"Resposta da IA não contém 'choices' ou está vazia: {json.dumps(resposta, indent=2)}")
            return "Desculpe, não consegui gerar uma resposta clara da IA no momento."

        return resposta['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao comunicar com a API da OpenRouter: {e}", exc_info=True)
        return "Desculpe, estou com dificuldades para me comunicar com a inteligência artificial agora. Por favor, tente novamente mais tarde!"
    except json.JSONDecodeError:
        logging.error(f"Resposta da API da OpenRouter não é um JSON válido. Status: {r.status_code}, Resposta: {r.text}", exc_info=True)
        return "Desculpe, recebi uma resposta inválida da inteligência artificial."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"🚀 Servidor iniciado na porta {port}")
    app.run(host="0.0.0.0", port=port)
