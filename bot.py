import os
import json
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import google.generativeai as genai
import base64
import re
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

client = MongoClient(os.environ.get("MONGODB_URL"))
db = client["despesas"]
col = db["registos"]

def get_next_id():
    ultimo = col.find_one(sort=[("id", -1)])
    if ultimo:
        return ultimo["id"] + 1
    return 1

def analyze_with_gemini(text):
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
    response = model.generate_content(prompt)
    text_response = response.text.strip()
    text_response = re.sub(r'```json\n?', '', text_response)
    text_response = re.sub(r'```\n?', '', text_response)
    return json.loads(text_response)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ola! Sou o teu bot de despesas!\n\n"
        "Podes enviar:\n"
        "Texto: ex: Gastei 4 euros no cafe\n"
        "Audio: fala a tua despesa\n"
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
    resultado = analyze_with_gemini(update.message.text)
    await save_and_reply(update, resultado)

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("
