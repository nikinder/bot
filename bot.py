import os
import io
import logging
import google.generativeai as genai
from datetime import datetime
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Проверка обязательных переменных
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не установлен!")
    print("❌ TELEGRAM_TOKEN не установлен! Добавьте в переменные окружения.")
    exit(1)

if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY не установлен!")
    print("❌ GEMINI_API_KEY не установлен! Добавьте в переменные окружения.")
    exit(1)

# Настройка Gemini
genai.configure(api_key=GEMINI_API_KEY)

# Хранилище данных пользователей
user_data = {}

def get_user_data(user_id: int):
    if user_id not in user_data:
        user_data[user_id] = {
            'requests_today': 0,
            'last_request_date': None,
            'subscription_active': False
        }
    return user_data[user_id]

def can_make_request(user_id: int):
    user = get_user_data(user_id)
    today = datetime.now().date()
    
    if user['last_request_date'] != today:
        user['requests_today'] = 0
        user['last_request_date'] = today
    
    if user['subscription_active']:
        return True, ""
    
    if user['requests_today'] < 3:
        return True, ""
    else:
        return False, """❌ Вы исчерпали лимит бесплатных запросов на сегодня (3/3)

💎 Приобретите подписку для неограниченного анализа!"""

async def analyze_with_gemini(image_data: bytes) -> str:
    """Анализирует изображение через Google Gemini API"""
    try:
        # Подготовка изображения
        image = Image.open(io.BytesIO(image_data))
        
        # Пробуем разные модели
        models_to_try = [
            'gemini-1.0-pro-vision',
            'gemini-pro-vision',
            'gemini-1.5-flash',
            'gemini-1.0-pro'
        ]
        
        for model_name in models_to_try:
            try:
                model = genai.GenerativeModel(model_name)
                
                prompt = """Ты - профессиональный диетолог. Проанализируй изображение еды и дай точную оценку калорийности.

Верни ответ в формате:
🍽 **Название блюда:** [название]

📊 **ОБЩАЯ КАЛОРИЙНОСТЬ:** ~X ккал

🍎 **ПИТАТЕЛЬНЫЙ СОСТАВ:**
• Белки: X г
• Жиры: X г  
• Углеводы: X г

📝 **СОСТАВ БЛЮДА:**
- [ингредиент 1]
- [ингредиент 2]

💡 **РЕКОМЕНДАЦИИ:** [советы]"""
                
                logger.info(f"Пробуем модель: {model_name}")
                response = model.generate_content([prompt, image])
                
                logger.info(f"Успешный ответ от модели {model_name}")
                return response.text
                
            except Exception as e:
                logger.warning(f"Модель {model_name} не сработала: {e}")
                continue
        
        # Если ни одна модель не сработала
        return "❌ Все модели Gemini API недоступны. Проверьте квоты и настройки billing."
            
    except Exception as e:
        logger.error(f"Error in analyze_with_gemini: {e}")
        return f"❌ Ошибка Gemini API: {str(e)}"

async def handle_photo(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    
    # Проверяем лимит запросов
    can_request, message = can_make_request(user.id)
    if not can_request:
        keyboard = [
            [InlineKeyboardButton("💎 Приобрести подписку", callback_data="subscribe")],
            [InlineKeyboardButton("📊 Статистика", callback_data="stats")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup)
        return
    
    # Показываем что бот работает
    processing_msg = await update.message.reply_text(
        "🔍 *Анализирую изображение...*\n\n"
        "Определяю блюдо и рассчитываю калории... ⏳", 
        parse_mode='Markdown'
    )
    
    try:
        # Получаем фото
        photo_file = await update.message.photo[-1].get_file()
        image_data = await photo_file.download_as_bytearray()
        
        # Анализируем изображение
        analysis_result = await analyze_with_gemini(bytes(image_data))
        
        # Обновляем счетчик запросов
        user_data_obj = get_user_data(user.id)
        user_data_obj['requests_today'] += 1
        
        # Добавляем информацию о использованных запросах
        requests_info = f"\n\n📊 Использовано запросов сегодня: {user_data_obj['requests_today']}/3"
        if user_data_obj['requests_today'] >= 3 and not user_data_obj['subscription_active']:
            requests_info += "\n❌ Лимит исчерпан - приобретите подписку для продолжения"
        
        full_response = analysis_result + requests_info
        
        # Удаляем сообщение о обработке
        await processing_msg.delete()
        
        # Отправляем результат
        if len(full_response) > 4000:
            full_response = full_response[:4000] + "\n\n... (сообщение обрезано)"
        
        await update.message.reply_text(full_response)
        
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        try:
            await processing_msg.delete()
        except:
            pass
        await update.message.reply_text("❌ Произошла ошибка при обработке фото. Попробуйте еще раз.")

async def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    
    welcome_text = f"""
✨ **Добро пожаловать в CalorieAI!** ✨

Привет, {user.first_name}! 🎉

Я - твой персональный диетолог с искусственным интеллектом! 📸🤖

**🎯 Что я умею:**
• Точное распознавание блюд по фото
• Анализ калорий и БЖУ (белки, жиры, углеводы)
• Определение состава ингредиентов
• Персональные рекомендации по питанию

**📊 Тарифы:**
• 🆓 Бесплатно: 3 анализа в сутки
• 💎 Премиум: неограниченно

Просто отправь мне фото еды и я всё проанализирую! 📸
    """
    
    keyboard = [
        [InlineKeyboardButton("📸 Анализировать фото", callback_data="analyze")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def stats(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    user_info = get_user_data(user.id)
    
    stats_text = f"""
📊 **Ваша статистика**

👤 Пользователь: {user.first_name}
📅 Запросов сегодня: {user_info['requests_today']}/3
💎 Статус подписки: {'Активна ✅' if user_info['subscription_active'] else 'Неактивна ❌'}

{'🎉 У вас неограниченный доступ!' if user_info['subscription_active'] else '💎 Приобретите подписку для неограниченного анализа!'}
    """
    
    keyboard = []
    if not user_info['subscription_active']:
        keyboard.append([InlineKeyboardButton("💎 Приобрести подписку", callback_data="subscribe")])
    keyboard.append([InlineKeyboardButton("📸 Анализировать фото", callback_data="analyze")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == "subscribe":
        await subscribe_info(query)
    elif query.data == "stats":
        await stats(update, context)
    elif query.data == "analyze":
        await query.edit_message_text(
            "📸 Отправьте фото еды для анализа калорий!\n\n"
            "Совет: сделайте четкое фото при хорошем освещении для лучшего результата."
        )

async def subscribe_info(query):
    subscribe_text = """
💎 **Премиум подписка**

Получите неограниченный доступ к анализу калорий!

**🎁 Преимущества:**
• ♾️ Неограниченное количество анализов
• 🚀 Приоритетная обработка
• 📈 Детальная статистика
• 🔔 Персональные рекомендации

**💳 Стоимость:** 299₽/месяц

⚠️ *Оплата временно недоступна. Мы работаем над интеграцией платежной системы.*
    """
    
    keyboard = [
        [InlineKeyboardButton("📊 Моя статистика", callback_data="stats")],
        [InlineKeyboardButton("📸 Анализировать фото", callback_data="analyze")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(subscribe_text, reply_markup=reply_markup, parse_mode='Markdown')

async def help_command(update: Update, context: CallbackContext) -> None:
    help_text = """
🆘 **Помощь по боту**

**📸 Как использовать:**
1. Отправьте фото еды в чат
2. Дождитесь анализа (10-30 секунд)
3. Получите детальную информацию о калориях и БЖУ

**🎯 Советы для лучшего анализа:**
• Снимайте при хорошем освещении
• Располагайте еду в центре кадра
• Избегайте размытых фото
• Показывайте все ингредиенты

**📊 Лимиты:**
• Бесплатно: 3 анализа в сутки
• С подпиской: неограниченно
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

def main() -> None:
    """Запуск бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Запускаем бота
    logger.info("🚀 Бот запущен с Google Gemini API!")
    print("=" * 50)
    print("🤖 CalorieAI Bot запущен!")
    print("📍 Хостинг: Railway")
    print("🧠 AI: Google Gemini")
    print("✅ Токен: Настроен")
    print("🔑 Gemini API: Настроен")
    print("📧 Команды: /start, /stats, /help")
    print("📸 Отправьте фото еды для анализа")
    print("=" * 50)
    
    application.run_polling()

if __name__ == "__main__":
    main()


