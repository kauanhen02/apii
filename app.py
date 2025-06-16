from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

OPENROUTER_KEY = "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"  # Substitua pela sua chave real da OpenRouter

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    msg = data.get("body", "").lower()
    numero = data.get("from", "")

    # Se for uma pergunta sobre fragrância
    if any(p in msg for p in ["fragrância", "fragrancia", "produto", "tem com", "contém", "com cheiro de", "com"]):
        try:
            r = requests.get("https://oracle-teste.onrender.com/produtos")
            produtos = r.json()

            # Filtrar produtos com base na descrição
            palavras_chave = [p for p in msg.split() if len(p) > 2]
            achados = []
            for prod in produtos:
                descricao = prod.get("PRO_ST_DESCRICAO", "").lower()
                codigo = prod.get("PRO_IN_CODIGO", "")
                for termo in palavras_chave:
                    if termo in descricao:
                        achados.append(f"{codigo} - {descricao}")
                        break

            if not achados:
                resposta_final = "Nenhum produto encontrado com base na sua descrição."
            else:
                prompt = f"Com base nesses produtos:\n{achados[:5]}\nResponda ao cliente de forma simpática e resumida, dizendo o que foi encontrado."
                resposta_final = responder_ia(prompt)

        except Exception as e:
            resposta_final = f"Erro ao consultar produtos: {e}"
    else:
        # Se for uma conversa genérica ("oi", "tudo bem", etc.), usa IA direto
        prompt = f"Mensagem recebida: '{msg}'. Responda como se fosse um atendente simpático em uma loja de fragrâncias."
        resposta_final = responder_ia(prompt)

    # Enviar resposta para WhatsApp (UltraMsg)
    requests.post("https://api.ultramsg.com/instance121153/messages/chat", data={
        "token": "ndr63qqkzknmazd4",
        "to": numero,
        "body": resposta_final
    })

    return jsonify({"status": "ok"})

def responder_ia(prompt):
    import json
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openai/gpt-3.5-turbo",  # Ou outro modelo válido
        "messages": [
            {"role": "system", "content": "Você é um assistente atencioso que ajuda clientes com fragrâncias."},
            {"role": "user", "content": prompt}
        ]
    }

    r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body)

    try:
        resposta = r.json()
    except Exception:
        return f"Erro: resposta não é JSON. Status: {r.status_code}"

    if "choices" not in resposta:
        # Mostra o erro real vindo da API
        return f"Erro IA: {json.dumps(resposta, indent=2)}"

    return resposta['choices'][0]['message']['content']


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

