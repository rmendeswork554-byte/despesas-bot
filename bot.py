import os
import json
import logging
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import base64
import re
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

client = MongoClient(os.environ.get("MONGODB_URL"))
db = client["despesas"]
col = db["registos"]

def get_next_id():
    ultimo = col.find_one(sort=[("id", -1)])
    if ultimo:
        return ultimo["id"] + 1
    return 1

def call_gemini(prompt):
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    response = requests.post(GEMINI_URL, json=body)
    result = response.json()
    text = result["candidates"][0]["content"]["parts"][0]["text"]
    text = re.sub(r'```json\n?', '', text.strip())
    text = re.sub(r'```\n?', '', text)
    return json.loads(text.strip())

def analyze_text(text):
    prompt = f"""Analisa esta mensagem e extrai informacao financeira.
Mensagem: "{text}"
Responde APENAS com um JSON valido neste formato exato:
{{
  "tipo": "despesa" ou "ganho",
  "valor": numero,
  "categoria": "Alimentacao" ou "Transporte" ou "Saude" ou "Lazer" ou "Casa" ou "Investimentos" ou "Salario" ou "Outros",
  "descricao": "descricao curta",
  "encontrado": true ou false
}}
Se nao encontrares informacao financeira, poe "encontrado": false."""
    return call_gemini(prompt)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ola! Sou o teu bot de despesas!\n\n"
        "Podes enviar:\n"
        "Texto: ex: Gastei 4 euros no cafe\n"
        "Foto: foto de um recibo\n\n"
        "Comandos:\n"
        "/resumo - Resumo do mes atual\n"
        "/ano - Resumo anual\n"
        "/lista - Ultimos registos\n"
        "/apagar - Apagar um registo"
    )

async def save_and_reply(update: Update, resultado: dict):
    if not resultado.get('encontrado'):
        await update.message.reply_text("Nao identifiquei despesa ou ganho. Tenta ser mais especifico!")
        return
    registo = {
        "id": get_next_id(),
        "tipo": resultado["tipo"],
        "valor": float(resultado["valor"]),
        "categoria": resultado["categoria"],
        "descricao": resultado["descricao"],
        "data": datetime.now().strftime("%Y-%m-%d"),
        "mes": datetime.now().strftime("%Y-%m"),
        "ano": datetime.now().strftime("%Y")
    }
    col.insert_one(registo)
    tipo_str = "Despesa" if resultado["tipo"] == "despesa" else "Ganho"
    await update.message.reply_text(
        tipo_str + " registado! (ID: " + str(registo["id"]) + ")\n\n"
        "Valor: " + str(resultado["valor"]) + " euros\n"
        "Categoria: " + resultado["categoria"] + "\n"
        "Descricao: " + resultado["descricao"] + "\n"
        "Data: " + registo["data"]
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    resultado = analyze_text(update.message.text)
    await save_and_reply(update, resultado)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("A analisar a foto...")
    photo = update.message.photo[-1]
    file = await photo.get_file()
    photo_data = await file.download_as_bytearray()
    photo_b64 = base64.b64encode(photo_data).decode()
    prompt = """Analisa este recibo e extrai o valor total e tipo de despesa.
Responde APENAS com JSON:
{
  "tipo": "despesa",
  "valor": numero,
  "categoria": "Alimentacao" ou "Transporte" ou "Saude" ou "Lazer" ou "Casa" ou "Investimentos" ou "Outros",
  "descricao": "descricao do recibo",
  "encontrado": true ou false
}"""
    body = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": photo_b64}}]}]}
    response = requests.post(GEMINI_URL, json=body)
    result = response.json()
    text = result["candidates"][0]["content"]["parts"][0]["text"]
    text = re.sub(r'```json\n?', '', text.strip())
    text = re.sub(r'```\n?', '', text)
    resultado = json.loads(text.strip())
    await save_and_reply(update, resultado)

async def apagar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        ultimos = list(col.find().sort("id", -1).limit(5))
        if not ultimos:
            await update.message.reply_text("Nao tens registos para apagar!")
            return
        msg = "Para apagar usa: /apagar ID\n\nUltimos registos:\n\n"
        for r in ultimos:
            sinal = "-" if r["tipo"] == "despesa" else "+"
            msg += "ID " + str(r["id"]) + ": " + r["data"] + " - " + r["categoria"] + " " + sinal + str(round(r["valor"], 2)) + " euros\n"
        await update.message.reply_text(msg)
        return
    try:
        id_apagar = int(context.args[0])
        registo = col.find_one({"id": id_apagar})
        if not registo:
            await update.message.reply_text("Registo ID " + str(id_apagar) + " nao encontrado!")
            return
        col.delete_one({"id": id_apagar})
        await update.message.reply_text(
            "Registo apagado!\n"
            "ID: " + str(id_apagar) + "\n"
            "Data: " + registo["data"] + "\n"
            "Categoria: " + registo["categoria"] + "\n"
            "Valor: " + str(round(registo["valor"], 2)) + " euros"
        )
    except ValueError:
        await update.message.reply_text("Usa assim: /apagar 5 (onde 5 e o ID do registo)")

async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mes_atual = datetime.now().strftime("%Y-%m")
    registos_mes = list(col.find({"mes": mes_atual}))
    if not registos_mes:
        await update.message.reply_text("Ainda nao tens registos este mes!")
        return
    total_despesas = sum(r["valor"] for r in registos_mes if r["tipo"] == "despesa")
    total_ganhos = sum(r["valor"] for r in registos_mes if r["tipo"] == "ganho")
    saldo = total_ganhos - total_despesas
    categorias = {}
    for r in registos_mes:
        cat = r["categoria"]
        if cat not in categorias:
            categorias[cat] = {"despesa": 0, "ganho": 0}
        categorias[cat][r["tipo"]] += r["valor"]
    nomes_meses = {"01":"Janeiro","02":"Fevereiro","03":"Marco","04":"Abril","05":"Maio","06":"Junho","07":"Julho","08":"Agosto","09":"Setembro","10":"Outubro","11":"Novembro","12":"Dezembro"}
    nome_mes = nomes_meses[mes_atual.split("-")[1]]
    msg = "Resumo de " + nome_mes + "\n\n"
    msg += "Ganhos: " + str(round(total_ganhos, 2)) + " euros\n"
    msg += "Despesas: " + str(round(total_despesas, 2)) + " euros\n"
    msg += "Saldo: " + str(round(saldo, 2)) + " euros\n\n"
    msg += "Por categoria:\n"
    for cat, valores in categorias.items():
        if valores["despesa"] > 0:
            msg += "  " + cat + ": -" + str(round(valores["despesa"], 2)) + " euros\n"
        if valores["ganho"] > 0:
            msg += "  " + cat + ": +" + str(round(valores["ganho"], 2)) + " euros\n"
    await update.message.reply_text(msg)

async def ano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ano_atual = datetime.now().strftime("%Y")
    registos_ano = list(col.find({"ano": ano_atual}))
    if not registos_ano:
        await update.message.reply_text("Ainda nao tens registos em " + ano_atual)
        return
    total_despesas = sum(r["valor"] for r in registos_ano if r["tipo"] == "despesa")
    total_ganhos = sum(r["valor"] for r in registos_ano if r["tipo"] == "ganho")
    saldo = total_ganhos - total_despesas
    meses = {}
    for r in registos_ano:
        mes = r["mes"]
        if mes not in meses:
            meses[mes] = {"despesa": 0, "ganho": 0}
        meses[mes][r["tipo"]] += r["valor"]
    nomes_meses = {"01":"Janeiro","02":"Fevereiro","03":"Marco","04":"Abril","05":"Maio","06":"Junho","07":"Julho","08":"Agosto","09":"Setembro","10":"Outubro","11":"Novembro","12":"Dezembro"}
    msg = "Resumo Anual " + ano_atual + "\n\n"
    msg += "Total Ganhos: " + str(round(total_ganhos, 2)) + " euros\n"
    msg += "Total Despesas: " + str(round(total_despesas, 2)) + " euros\n"
    msg += "Saldo: " + str(round(saldo, 2)) + " euros\n\n"
    msg += "Por mes:\n"
    for mes in sorted(meses.keys()):
        nome_mes = nomes_meses[mes.split("-")[1]]
        saldo_mes = meses[mes]["ganho"] - meses[mes]["despesa"]
        sinal = "+" if saldo_mes >= 0 else ""
        msg += "  " + nome_mes + ": " + sinal + str(round(saldo_mes, 2)) + " euros\n"
    await update.message.reply_text(msg)

async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ultimos = list(col.find().sort("id", -1).limit(10))
    if not ultimos:
        await update.message.reply_text("Ainda nao tens registos!")
        return
    msg = "Ultimos registos:\n\n"
    for r in ultimos:
        sinal = "-" if r["tipo"] == "despesa" else "+"
        msg += "ID " + str(r["id"]) + ": " + r["data"] + " - " + r["categoria"] + "\n"
        msg += sinal + str(round(r["valor"], 2)) + " euros - " + r["descricao"] + "\n\n"
    await update.message.reply_text(msg)

def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("resumo", resumo))
    app.add_handler(CommandHandler("ano", ano))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("apagar", apagar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    logger.info("Bot iniciado!")
    app.run_polling()

if __name__ == "__main__":
    main()
