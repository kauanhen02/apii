from flask import Flask, request, jsonify
import requests
import json
import os

app = Flask(__name__)

GEMINI_API_KEY = "AIzaSyAvtuZM5nOQFHZvxTjhxUWfB6bkIX4XEb4"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    msg = data.get("body", "").lower()
    numero = data.get("from", "")

    print(f"Mensagem recebida de {numero}: {msg}")

    try:
        if any(p in msg for p in ["fragrância", "fragrancia", "produto", "tem com", "contém", "com cheiro de", "com"]):
            # Consulta produtos
            r = requests.get("https://oracle-teste.onrender.com/produtos")
            produtos = r.json()

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
                resposta_final = responder_com_gemini(prompt)
        else:
            prompt = f"Mensagem recebida: '{msg}'. Responda como se fosse um atendente simpático em uma loja de fragrâncias."
            resposta_final = responder_com_gemini(prompt)

    except Exception as e:
        print("Erro ao processar mensagem:", str(e))
        resposta_final = f"Erro interno: {e}"

    # Enviar resposta via UltraMsg
    try:
        resp = requests.post("https://api.ultramsg.com/instance121153/messages/chat", data={
            "token": "ndr63qqkzknmazd4",
            "to": numero,
            "body": resposta_final
        })

        print("Resposta enviada via UltraMsg:", resp.text)
    except Exception as e:
        print("Erro ao enviar resposta via UltraMsg:", str(e))

    return jsonify({"status": "ok"})


def responder_com_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"

    headers = { "Content-Type": "application/json" }
    body = {
        "contents": [
            {
                "parts": [{ "text": prompt }]
            }
        ]
    }

    response = requests.post(url, headers=headers, json=body)

    try:
        resposta = response.json()
        return resposta["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print("Erro na resposta do Gemini:", resposta)
        return "Desculpe, houve um problema ao responder."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
