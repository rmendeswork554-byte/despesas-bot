import os
import json
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import google.generativeai as genai
import base64
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

DATA_FILE = "despesas.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"registos": []}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def analyze_with_gemini(text):
    prompt = f"""Analisa esta mensagem e extrai informação financeira.
Mensagem: "{text}"
Responde APENAS com um JSON válido neste formato exato:
{{
  "tipo": "despesa" ou "ganho",
  "valor": numero,
  "categoria": "Alimentação" ou "Transporte" ou "Saúde" ou "Lazer" ou "Casa" ou "Investimentos" ou "Salário" ou "Outros",
  "descricao": "descrição curta",
  "encontrado": true ou false
}}
Se não encontrares informação financeira, põe "encontrado": false."""
    response = model.generate_content(prompt)
    text_response = response.text.strip()
    text_response = re.sub(r'```json\n?', '', text_response)
    text_response = re.sub(r'```\n?', '', text_response)
    return json.loads(text_response)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Sou o teu bot de despesas!\n\n"
        "Podes enviar:\n"
        "💬 Texto — ex: Gastei 4€ no café\n"
        "🎤 Áudio — fala a tua despesa\n"
        "📷 Foto — foto de um recibo\n\n"
        "Comandos:\n"
        "/resumo — Resumo do mês atual\n"
        "/ano — Resumo anual\n"
        "/lista — Últimos registos"
    )

async def save_and_reply(update: Update, resultado: dict):
    if not resultado.get('encontrado'):
        await update.message.reply_text("❌ Não identifiquei despesa ou ganho. Tenta ser mais específico!")
        return
    data = load_data()
    registo = {
        "id": len(data["registos"]) + 1,
        "tipo": resultado["tipo"],
        "valor": float(resultado["valor"]),
        "categoria": resultado["categoria"],
        "descricao": resultado["descricao"],
        "data": datetime.now().strftime("%Y-%m-%d"),
        "mes": datetime.now().strftime("%Y-%m"),
        "ano": datetime.now().strftime("%Y")
    }
    data["registos"].append(registo)
    save_data(data)
    emoji = "💸" if resultado["tipo"] == "despesa" else "💰"
    tipo_str = "Despesa" if resultado["tipo"] == "despesa" else "Ganho"
    await update.message.reply_text(
        f"{emoji} {tipo_str} registado!\n\n"
        f"💶 Valor: {resultado['valor']:.2f}€\n"
        f"📂 Categoria: {resultado['categoria']}\n"
        f"📝 {resultado['descricao']}\n"
        f"📅 {registo['data']}"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    resultado = analyze_with_gemini(update.message.text)
    await save_and_reply(update, resultado)

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎤 A processar o áudio...")
    if update.message.voice:
        file = await update.message.voice.get_file()
    else:
        file = await update.message.audio.get_file()
    audio_data = await file.download_as_bytearray()
    audio_b64 = base64.b64encode(audio_data).decode()
    prompt = """Transcreve este áudio e extrai informação financeira.
Responde APENAS com JSON:
{
  "tipo": "despesa" ou "ganho",
  "valor": numero,
  "categoria": "Alimentação" ou "Transporte" ou "Saúde" ou "Lazer" ou "Casa" ou "Investimentos" ou "Salário" ou "Outros",
  "descricao": "descrição curta",
  "encontrado": true ou false,
  "transcricao": "texto transcrito"
}"""
    response = model.generate_content([prompt, {"mime_type": "audio/ogg", "data": audio_b64}])
    text_response = re.sub(r'```json\n?', '', response.text.strip())
    text_response = re.sub(r'```\n?', '', text_response)
    resultado = json.loads(text_response)
    if resultado.get('transcricao'):
        await update.message.reply_text(f"🎤 Transcrição: {resultado['transcricao']}")
    await save_and_reply(update, resultado)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📷 A analisar a foto...")
    photo = update.message.photo[-1]
    file = await photo.get_file()
    photo_data = await file.download_as_bytearray()
    photo_b64 = base64.b64encode(photo_data).decode()
    prompt = """Analisa este recibo e extrai o valor total e tipo de despesa.
Responde APENAS com JSON:
{
  "tipo": "despesa",
  "valor": numero,
  "categoria": "Alimentação" ou "Transporte" ou "Saúde" ou "Lazer" ou "Casa" ou "Investimentos" ou "Outros",
  "descricao": "descrição do recibo",
  "encontrado": true ou false
}"""
    response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": photo_b64}])
    text_response = re.sub(r'```json\n?', '', response.text.strip())
    text_response = re.sub(r'```\n?', '', text_response)
    resultado = json.loads(text_response)
    await save_and_reply(update, resultado)

async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    mes_atual = datetime.now().strftime("%Y-%m")
    registos_mes = [r for r in data["registos"] if r["mes"] == mes_atual]
    if not registos_mes:
        await update.message.reply_text("📊 Ainda não tens registos este mês!")
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
    nomes_meses = {"01":"Janeiro","02":"Fevereiro","03":"Março","04":"Abril","05":"Maio","06":"Junho","07":"Julho","08":"Agosto","09":"Setembro","10":"Outubro","11":"Novembro","12":"Dezembro"}
    nome_mes = nomes_meses[mes_atual.split("-")[1]]
    msg = f"📊 Resumo de {nome_mes}\n\n"
    msg += f"💰 Ganhos: {total_ganhos:.2f}€\n"
    msg += f"💸 Despesas: {total_despesas:.2f}€\n"
    msg += f"{'✅' if saldo >= 0 else '❌'} Saldo: {saldo:.2f}€\n\n"
    msg += "📂 Por categoria:\n"
    for cat, valores in categorias.items():
        if valores["despesa"] > 0:
            msg += f"  • {cat}: -{valores['despesa']:.2f}€\n"
        if valores["ganho"] > 0:
            msg += f"  • {cat}: +{valores['ganho']:.2f}€\n"
    await update.message.reply_text(msg)

async def ano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    ano_atual = datetime.now().strftime("%Y")
    registos_ano = [r for r in data["registos"] if r["ano"] == ano_atual]
    if not registos_ano:
        await update.message.reply_text(f"📊 Ainda não tens registos em {ano_atual}!")
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
    nomes_meses = {"01":"Janeiro","02":"Fevereiro","03":"Março","04":"Abril","05":"Maio","06":"Junho","07":"Julho","08":"Agosto","09":"Setembro","10":"Outubro","11":"Novembro","12":"Dezembro"}
    msg = f"📊 Resumo Anual {ano_atual}\n\n"
    msg += f"💰 Total Ganhos: {total_ganhos:.2f}€\n"
    msg += f"💸 Total Despesas: {total_despesas:.2f}€\n"
    msg += f"{'✅' if saldo >= 0 else '❌'} Saldo: {saldo:.2f}€\n\n"
    msg += "📅 Por mês:\n"
    for mes in sorted(meses.keys()):
        nome_mes = nomes_meses[mes.split("-")[1]]
        saldo_mes = meses[mes]["ganho"] - meses[mes]["despesa"]
        emoji = "✅" if saldo_mes >= 0 else "❌"
        msg += f"  {emoji} {nome_mes}: {saldo_mes:+.2f}€\n"
    await update.message.reply_text(msg)

async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["registos"]:
        await update.message.reply_text("📋 Ainda não tens registos!")
        return
    ultimos = data["registos"][-10:][::-1]
    msg = "📋 Últimos registos:\n\n"
    for r in ultimos:
        emoji = "💸" if r["tipo"] == "despesa" else "💰"
        sinal = "-" if r["tipo"] == "despesa" else "+"
        msg += f"{emoji} {r['data'
