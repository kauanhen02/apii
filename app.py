from flask import Flask, request, jsonify
import requests
import json
import os
import logging

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Chaves de API vindas das variáveis de ambiente
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
ULTRAMSG_TOKEN = os.environ.get("ULTRAMSG_TOKEN")

if not OPENROUTER_KEY:
    logging.error("❌ OPENROUTER_KEY não definida. Defina como variável de ambiente.")
    exit(1)

if not ULTRAMSG_TOKEN:
    logging.error("❌ ULTRAMSG_TOKEN não definida. Defina como variável de ambiente.")
    exit(1)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        logging.warning("⚠️ Requisição sem JSON no corpo.")
        return jsonify({"status": "error", "message": "Requisição sem JSON"}), 400

    msg = data.get("body", "").strip().lower()
    numero = data.get("from", "").strip()

    if not msg or not numero:
        logging.warning(f"⚠️ Campos 'body' ou 'from' ausentes. Body: '{msg}', From: '{numero}'")
        return jsonify({"status": "error", "message": "Campos 'body' ou 'from' ausentes"}), 400

    logging.info(f"📩 Mensagem de {numero}: '{msg}'")
    resposta_final = ""

    try:
        if any(p in msg for p in ["fragrância", "fragrancia", "produto", "tem com", "contém", "cheiro", "com"]):
            try:
                r = requests.get("https://oracle-teste.onrender.com/produtos", timeout=10)
                r.raise_for_status()
                produtos = r.json()
            except requests.exceptions.RequestException as e:
                logging.error(f"❌ Erro ao consultar produtos: {e}")
                resposta_final = "Desculpe, não consegui consultar nossos produtos no momento. Tente novamente em breve."
                enviar_resposta_ultramsg(numero, resposta_final)
                return jsonify({"status": "ok"})

            palavras_chave = [p for p in msg.split() if len(p) > 2]
            achados = []

            for prod in produtos:
                descricao = prod.get("PRO_ST_DESCRICAO", "").lower()
                codigo = prod.get("PRO_IN_CODIGO", "")
                if any(termo in descricao for termo in palavras_chave):
                    achados.append(f"{codigo} - {descricao}")
                    if len(achados) >= 5:
                        break

            if not achados:
                resposta_final = "Nenhum produto encontrado com base na sua descrição. Tente usar palavras mais específicas."
            else:
                prompt = f"Com base nesses produtos:\n{chr(10).join(achados)}\nResponda de forma simpática e resumida ao cliente."
                resposta_final = responder_ia(prompt)
        else:
            prompt = f"Mensagem do cliente: '{msg}'. Responda como se fosse um atendente simpático de loja de fragrâncias."
            resposta_final = responder_ia(prompt)

    except Exception as e:
        logging.error(f"❌ Erro inesperado: {e}", exc_info=True)
        resposta_final = "Desculpe, ocorreu um erro interno. Tente novamente em breve."

    enviar_resposta_ultramsg(numero, resposta_final)
    return jsonify({"status": "ok"})

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
        logging.info(f"✅ Resposta enviada para {numero}: {resp.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Erro ao enviar via UltraMsg: {e}", exc_info=True)

def responder_ia(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "Você é um atendente educado e prestativo de uma loja de fragrâncias."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }

    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body, timeout=30)
        r.raise_for_status()
        resposta = r.json()
        return resposta.get("choices", [{}])[0].get("message", {}).get("content", "Desculpe, não consegui gerar uma resposta.")
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Erro na IA: {e}", exc_info=True)
        return "Desculpe, não consegui responder agora. Por favor, tente novamente mais tarde."
    except Exception as e:
        logging.error(f"❌ Erro inesperado ao processar resposta da IA: {e}", exc_info=True)
        return "Ocorreu um problema ao gerar resposta da inteligência artificial."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"🚀 Servidor iniciado na porta {port}")
    app.run(host="0.0.0.0", port=port)
