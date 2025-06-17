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
    logging.error("❌ OPENROUTER_KEY não definida. Defina como variável de ambiente para que o app funcione.")
    exit(1)

if not ULTRAMSG_TOKEN:
    logging.error("❌ ULTRAMSG_TOKEN não definida. Defina como variável de ambiente para que o app funcione.")
    exit(1)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    
    # Loga o payload JSON bruto recebido para depuração (MANTENHA ESTA LINHA!)
    logging.info(f"✨ Payload JSON bruto recebido da UltraMsg: {json.dumps(data, indent=2)}")

    if not data:
        logging.warning("⚠️ Requisição sem JSON no corpo. Verifique a configuração do webhook na UltraMsg.")
        return jsonify({"status": "error", "message": "Requisição sem JSON"}), 400

    # --- MUDANÇA ESSENCIAL AQUI ---
    # Primeiro, acesse o objeto 'data' dentro do payload principal
    ultramsg_data = data.get("data", {}) # Se 'data' não existir, retorna um dicionário vazio
    
    # Agora, acesse 'body' e 'from' DENTRO de 'ultramsg_data'
    msg = ultramsg_data.get("body", "").strip().lower()
    # O número vem como "5519993480072@c.us". Vamos remover o "@c.us" para ficar só o número.
    numero = ultramsg_data.get("from", "").replace("@c.us", "").strip()
    # --- FIM DA MUDANÇA ESSENCIAL ---

    if not msg or not numero:
        logging.warning(f"⚠️ Campos 'body' ou 'from' ausentes ou vazios no payload. Body: '{msg}', From: '{numero}'. Verifique o formato do JSON da UltraMsg.")
        return jsonify({"status": "error", "message": "Campos 'body' ou 'from' ausentes ou vazios"}), 400

    logging.info(f"📩 Mensagem recebida de {numero}: '{msg}'")
    resposta_final = ""

    try:
        if any(p in msg for p in ["fragrância", "fragrancia", "produto", "tem com", "contém", "cheiro", "com"]):
            try:
                r = requests.get("https://oracle-teste-1.onrender.com/produtos", timeout=100)
                r.raise_for_status()
                produtos = r.json()
                logging.info("✔️ Produtos consultados com sucesso da API externa.")
            except requests.exceptions.RequestException as e:
                logging.error(f"❌ Erro ao consultar produtos da API externa: {e}", exc_info=True)
                resposta_final = "Desculpe, não consegui consultar nossos produtos no momento. Por favor, tente novamente mais tarde!"
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
                resposta_final = "Nenhum produto encontrado com base na sua descrição. Você gostaria de tentar com outras palavras-chave ou nos dar mais detalhes?"
            else:
                prompt = f"Com base nesses produtos:\n{chr(10).join(achados)}\nResponda ao cliente de forma simpática e resumida, dizendo o que foi encontrado e convidando-o a perguntar sobre outros produtos se não encontrar o que busca."
                resposta_final = responder_ia(prompt)
        else:
            prompt = f"Mensagem do cliente: '{msg}'. Responda como se fosse um atendente simpático de uma casa de fragrâncias."
            resposta_final = responder_ia(prompt)

    except Exception as e:
        logging.error(f"❌ Erro inesperado durante o processamento da mensagem: {e}", exc_info=True)
        resposta_final = "Desculpe, ocorreu um erro interno inesperado. Nossos atendentes já foram notificados e em breve resolveremos!"

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
        logging.info(f"✅ Resposta enviada para {numero}. UltraMsg retornou: {resp.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Erro ao enviar resposta via UltraMsg para {numero}: {e}", exc_info=True)

def responder_ia(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [
           {
  "role": "system",
  "content": "Você é a Iris, a assistente virtual da Ginger Fragrances. Seu papel é ser uma atendente educada, prestativa e simpática, sempre pronta para ajudar de forma concisa e acolhedora. Você foi criada para auxiliar os vendedores e funcionários da Ginger Fragrances a encontrarem o código correto das fragrâncias com base nas notas olfativas desejadas, como maçã, bambu, baunilha, entre outras. Sempre que alguém descrever um cheiro ou sensação, sua missão é indicar as fragrâncias que mais se aproximam disso, de forma clara, rápida e eficiente."
},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }

    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body, timeout=30)
        r.raise_for_status()
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
