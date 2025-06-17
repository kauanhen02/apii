from flask import Flask, request, jsonify
import requests
import json
import os
import logging
import threading
import re # Importa para usar expressões regulares
from googleapiclient.discovery import build # Importa para Google Custom Search API
import psycopg2 # <-- NOVO: Importa para PostgreSQL
from psycopg2 import extras # <-- NOVO: Para funcionalidades extras do psycopg2, embora não usemos execute_values aqui, é boa prática

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__) # Corrigido: __name__ com dois underscores

# Chaves de API vindas das variáveis de ambiente
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
ULTRAMSG_TOKEN = os.environ.get("ULTRAMSG_TOKEN")

# Variáveis para a API do Google Custom Search
SEARCH_API_KEY = os.environ.get("Search_API_KEY") 
SEARCH_CX = os.environ.get("Search_CX")          

# --- NOVO: Variáveis para a conexão direta com o PostgreSQL (Neon.tech) ---
PG_DB_USER = os.environ.get("PG_DB_USER")
PG_DB_PASSWORD = os.environ.get("PG_DB_PASSWORD")
PG_DB_HOST = os.environ.get("PG_DB_HOST")
PG_DB_PORT = os.environ.get("PG_DB_PORT", "5432") 
PG_DB_NAME = os.environ.get("PG_DB_NAME")
# --- FIM NOVO ---

# --- VERIFICAÇÕES DE VARIÁVEIS DE AMBIENTE ---
if not OPENROUTER_KEY:
    logging.error("❌ OPENROUTER_KEY não definida. Defina como variável de ambiente para que o app funcione.")
    exit(1)

if not ULTRAMSG_TOKEN:
    logging.error("❌ ULTRAMSG_TOKEN não definida. Defina como variável de ambiente para que o app funcione.")
    exit(1)

if not SEARCH_API_KEY or not SEARCH_CX:
    logging.error("❌ Variáveis Search_API_KEY ou Search_CX não definidas. A pesquisa web não funcionará.")
    exit(1)

# --- NOVO: Verificação das variáveis do PostgreSQL para o BOT PRINCIPAL ---
if not all([PG_DB_USER, PG_DB_PASSWORD, PG_DB_HOST, PG_DB_NAME]):
    logging.error("❌ Variáveis de ambiente do PostgreSQL (PG_DB_USER, PG_DB_PASSWORD, PG_DB_HOST, PG_DB_NAME) não definidas para o bot principal. A busca de produtos não funcionará.")
    exit(1)
# --- FIM NOVO ---


# --- FUNÇÕES AUXILIARES ---

# NOVO: Função para consultar produtos diretamente do PostgreSQL
def get_products_from_pg(product_code=None, search_term=None):
    pg_conn = None
    pg_cursor = None
    try:
        pg_conn = psycopg2.connect(
            host=PG_DB_HOST,
            database=PG_DB_NAME,
            user=PG_DB_USER,
            password=PG_DB_PASSWORD,
            port=PG_DB_PORT,
            sslmode='require' # Neon.tech geralmente exige SSL
        )
        pg_cursor = pg_conn.cursor()

        query = "SELECT pro_in_codigo, pro_st_descricao, re_custo FROM produtos"
        params = []
        
        if product_code:
            query += " WHERE UPPER(pro_in_codigo) = %s"
            params.append(product_code.upper())
            logging.info(f"DB Query: Buscando produto pelo código: {product_code}")
        elif search_term:
            query += " WHERE LOWER(pro_st_descricao) LIKE %s" 
            params.append(f"%{search_term.lower()}%")
            logging.info(f"DB Query: Buscando produtos por termo: {search_term}")
            query += " LIMIT 50" # Limita a 50 resultados para evitar sobrecarga da resposta da IA
        
        pg_cursor.execute(query, params)
        
        columns = [desc[0] for desc in pg_cursor.description]
        rows = []
        for row_data in pg_cursor.fetchall():
            rows.append(dict(zip(columns, row_data)))
        
        logging.info(f"DB Query retornou {len(rows)} linhas.")
        return rows
    except psycopg2.Error as e:
        logging.error(f"❌ Erro ao consultar PostgreSQL DB diretamente: {e}", exc_info=True)
        return []
    finally:
        if pg_cursor: pg_cursor.close()
        if pg_conn: pg_conn.close()

# Função para realizar a pesquisa web com Google Custom Search
def perform_google_custom_search(query):
    try:
        service = build("customsearch", "v1", developerKey=SEARCH_API_KEY)
        res = service.cse().list(q=query, cx=SEARCH_CX, num=3).execute() 
        
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

# Função para enviar resposta via UltraMsg
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

# Função para responder via IA (OpenRouter)
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
                "content": """🎉 Olá! Eu sou a Iris, a assistente virtual da Ginger Fragrances! ✨ Meu papel é ser sua melhor amiga no mundo dos aromas: sempre educada, prestativa, simpática e com um toque de criatividade! 💖 Fui criada para ajudar nossos incríveis vendedores e funcionários a encontrar rapidinho os códigos das fragrâncias com base nas notas olfativas que os clientes amam, tipo maçã 🍎, bambu 🎋, baunilha 🍦 e muito mais! 
                Além disso, eu posso **realizar pesquisas na web para te ajudar com perguntas mais gerais**, **informar o custo de uma fragrância específica pelo código OU nome** e, se você precisar, posso **calcular o preço de venda das nossas fragrâncias** com o markup que você me disser!
                
                **Nossos Valores na Ginger Fragrances são:**
                * **FOCO NO RESULTADO / COLABORAÇÃO / EMPATIA**
                * **PAIXÃO E CRIATIVIDADE / EXCELÊNCIA NA EXECUÇÃO**
                * **RESPEITO ÀS PESSOAS E AO MEIO AMBIENTE**
                
                Sempre que alguém descrever um cheirinho ou uma sensação, minha missão é indicar as fragrâncias que mais se aproximam disso, **listando os códigos correspondentes de forma clara, única, rápida e super eficiente, e sendo o mais concisa possível na resposta. Responda apenas uma vez.** Vamos descobrir o aroma perfeito? 😊"""
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


# Função principal de processamento da mensagem (executada em segundo plano)
def processar_mensagem_em_segundo_plano(ultramsg_data, numero, msg):
    logging.info(f"📩 [Processamento em Segundo Plano] Mensagem recebida de {numero}: '{msg}'")
    resposta_final = ""

    try:
        # --- Lógica para responder sobre os valores da empresa ---
        if any(p in msg for p in ["valores", "nossos valores", "quais os valores", "cultura da empresa", "missao", "princípios"]):
            resposta_final = """🎉 Olá! Que ótimo que você se interessa pelos nossos valores na Ginger Fragrances! ✨ Eles são o coração da nossa empresa e guiam tudo o que fazemos:

* **FOCO NO RESULTADO:** Buscamos sempre a excelência e o impacto positivo.
* **COLABORAÇÃO:** Acreditamos que juntos somos mais fortes.
* **EMPATIA:** Nos colocamos no lugar do outro para entender e ajudar.
* **PAIXÃO E CRIATIVIDADE:** Amamos o que fazemos e sempre inovamos!
* **EXCELÊNCIA NA EXECUÇÃO:** Fazemos tudo com o máximo de cuidado e qualidade.
* **RESPEITO ÀS PESSOAS E AO MEIO AMBIENTE:** Cuidamos do nosso time e do nosso planeta.

Seja bem-vindo(a) à nossa essência! 😊 Quer saber mais sobre nossas fragrâncias incríveis!"""
            enviar_resposta_ultramsg(numero, resposta_final)
            return

        # --- NOVO: Lógica para informar o custo de uma PR por CÓDIGO OU NOME ---
        # Regex para capturar "prXXXXX" OU uma frase que pode ser um nome
        # Grupo 1: captura o código (pr\d+)
        # Grupo 2: captura o nome (qualquer coisa depois de "custo da " que não seja pr\d+)
        match_custo = re.search(r"(?:qual o|qual é o|preço de)?\s*custo da\s+(pr\d+)", msg)
        match_custo_nome = re.search(r"(?:qual o|qual é o|preço de)?\s*custo da\s+(.+)", msg)

        product_code_requested = None
        product_name_requested = None

        if match_custo:
            product_code_requested = match_custo.group(1).upper()
        elif match_custo_nome and not match_custo_nome.group(1).strip().upper().startswith("PR"): # Garante que não pegue "PR" como nome
            product_name_requested = match_custo_nome.group(1).strip()
            
        if product_code_requested or product_name_requested:
            produtos_encontrados = []
            if product_code_requested:
                produtos_encontrados = get_products_from_pg(product_code=product_code_requested)
                logging.info(f"DEBUG (Custo por Código): Buscou {product_code_requested}, encontrou {len(produtos_encontrados)}.")
            elif product_name_requested:
                produtos_encontrados = get_products_from_pg(search_term=product_name_requested)
                logging.info(f"DEBUG (Custo por Nome): Buscou '{product_name_requested}', encontrou {len(produtos_encontrados)}.")

            if len(produtos_encontrados) == 1:
                prod = produtos_encontrados[0]
                cost_value = prod.get("re_custo") 
                logging.info(f"DEBUG: Valor de re_custo para {product_code_requested or product_name_requested} antes da conversão (custo direto): '{cost_value}' (Tipo: {type(cost_value)})") 
                
                found_product_cost = None
                if cost_value is not None:
                    try:
                        found_product_cost = float(cost_value)
                    except (ValueError, TypeError):
                        logging.warning(f"Custo inválido (não numérico) para {product_code_requested or product_name_requested} (custo direto): '{cost_value}'") 
            
                if found_product_cost is not None:
                    prompt = f"""O cliente perguntou 'qual o custo da {product_code_requested or product_name_requested}'.
                    O custo encontrado para '{product_code_requested or product_name_requested}' é R$ {found_product_cost:.2f}.
                    
                    Como a Iris, a assistente virtual da Ginger Fragrances, informe o custo encontrado de forma simpática, clara e objetiva. Mencione o código/nome do produto e o custo. Use emojis!"""
                    resposta_final = responder_ia(prompt)
                else:
                    resposta_final = f"Ah, que pena! 😕 Não consegui encontrar o custo para a fragrância {product_code_requested or product_name_requested} nos nossos registros ou o custo é inválido. Você digitou o código/nome certinho? Tente novamente! ✨"
            elif len(produtos_encontrados) > 1:
                list_of_products = []
                for i, prod in enumerate(produtos_encontrados[:5]): # Limita a lista para a IA
                    list_of_products.append(f"{i+1}. Código: {prod.get('pro_in_codigo', 'N/A')} - Descrição: {prod.get('pro_st_descricao', 'N/A')}")
                
                prompt = f"""O cliente perguntou sobre o custo de '{product_name_requested}', mas encontrei múltiplas fragrâncias com nomes ou descrições similares:
{chr(10).join(list_of_products)}

Como a Iris, a assistente virtual da Ginger Fragrances, explique que encontrou mais de um produto e peça para o cliente especificar qual ele deseja, fornecendo o código exato (PRXXXXX). Seja simpática e útil. ✨"""
                resposta_final = responder_ia(prompt)

            else: # Nenhuma PR encontrada por código ou nome
                resposta_final = f"Que pena! 😔 Não encontrei nenhuma fragrância com o código ou nome '{product_code_requested or product_name_requested}' nos nossos registros. Você digitou o código/nome certinho? Tente novamente com outro termo. Estou aqui para ajudar! 🕵️‍♀️💖"
            
            enviar_resposta_ultramsg(numero, resposta_final)
            return # Finaliza o processamento para esta intenção

        # --- Lógica para calcular preço de venda ---
        match_preco = re.search(r"(?:qual o|calcule o)?\s*preço de venda da (pr\d+)\s+com o markup\s+(\d+(?:[.,]\d+)?)", msg)
        
        if match_preco:
            product_code_requested = match_preco.group(1).upper() # Ex: PR11410
            markup_str = match_preco.group(2).replace(',', '.') # Ex: "3" ou "3.5"
            
            try:
                markup = float(markup_str)
                fixed_divisor = 0.7442

                produtos_encontrados = get_products_from_pg(product_code=product_code_requested)

                found_product_cost = None
                if produtos_encontrados:
                    prod = produtos_encontrados[0] 
                    cost_value = prod.get("re_custo") 
                    logging.info(f"DEBUG: Valor de re_custo para {product_code_requested} antes da conversão: '{cost_value}' (Tipo: {type(cost_value)})") 

                    if cost_value is not None:
                        try:
                            found_product_cost = float(cost_value)
                        except (ValueError, TypeError):
                            logging.warning(f"Custo inválido (não numérico) para {product_code_requested}: '{cost_value}'") 

                if found_product_cost is not None:
                    selling_price = (markup * found_product_cost) / fixed_divisor
                    
                    prompt = f"""O cliente pediu para calcular o preço de venda da fragrância '{product_code_requested}' com um markup de {markup}.
                    O custo encontrado para '{product_code_requested}' foi de R$ {found_product_cost:.2f}.
                    O preço de venda calculado é R$ {selling_price:.2f}.
                    
                    Como a Iris, a assistente virtual da Ginger Fragrances, informe o preço de venda calculado de forma simpática, clara e objetiva. Mencione o código do produto, o markup usado e o preço final. Use emojis! Não explique a fórmula. Exemplo: 'Olá! Para a fragrância [código], com markup [x], o preço de venda é de R$ [valor]! ✨'"""
                    resposta_final = responder_ia(prompt)
                else:
                    resposta_final = f"Ah, que pena! 😕 Não consegui encontrar o custo para a fragrância {product_code_requested} nos nossos registros. Você digitou o código certinho? Tente novamente ou me diga sobre qual fragrância você gostaria de calcular o preço de venda! ✨"
            except ValueError:
                resposta_final = "Ops! 🧐 O markup que você informou não parece um número válido. Por favor, use um número (ex: '3' ou '3.5')."
            except Exception as e: 
                logging.error(f"❌ Erro ao calcular preço/consultar DB: {e}", exc_info=True)
                resposta_final = "Desculpe, tive um problema ao calcular o preço agora. Nossos sistemas estão um pouco tímidos! Tente novamente mais tarde! 😥"

            enviar_resposta_ultramsg(numero, resposta_final)
            return

        # Lógica para busca de fragrâncias por descrição (se o cliente não pediu cálculo nem valores)
        elif any(p in msg for p in ["fragrância", "fragrancia", "produto", "tem com", "contém", "cheiro", "com"]):
            # --- MUDANÇA AQUI: Chamar get_products_from_pg diretamente ---
            # Extrair termo de busca da mensagem do cliente para passar para a função
            search_term_for_db = " ".join([p for p in msg.split() if len(p) > 2]) 
            produtos = get_products_from_pg(search_term=search_term_for_db)

            palavras_chave = [p for p in msg.split() if len(p) > 2] 

            achados = []
            for prod in produtos: 
                descricao = prod.get("pro_st_descricao", "").lower() 
                codigo = prod.get("pro_in_codigo", "")             
                if any(termo in descricao for termo in palavras_chave):
                    achados.append(f"Código: {codigo} - Descrição: {descricao}")
                    if len(achados) >= 5: 
                        break

            if not achados:
                resposta_final = "Que pena! 😔 Não encontrei nenhuma fragrância com essa descrição. Mas não desanime! Nossos produtos são um universo de aromas! Que tal tentar com outras palavras-chave ou me dar mais detalhes sobre o cheiro que você imagina? Estou pronta para a próxima busca! 🕵️‍♀️💖"
            else:
                prompt = f"""Com base nestes produtos incríveis que encontrei para você:
{chr(10).join(achados)}
Por favor, como a Iris, a assistente virtual super animada da Ginger Fragrances, responda ao cliente de forma **super simpática, vibrante e concisa**, listando os códigos e descrições dos produtos encontrados **apenas uma vez, em um formato divertido e fácil de ler**! Convide-o com entusiasmo a perguntar sobre outras maravilhas perfumadas se ainda não for exatamente o que ele busca! ✨"""
                resposta_final = responder_ia(prompt)
        # Lógica para pesquisa web (perguntas gerais)
        else: 
            search_query = msg
            snippets = perform_google_custom_search(search_query) 
            
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
    # CORRIGIDO AQUI: ultramsg_data.get para 'from'
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
            "https://api.ultramsg.com/instance126332/messages/chat",
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"🚀 Servidor iniciado na porta {port}")
    app.run(host="0.0.0.0", port=port)
