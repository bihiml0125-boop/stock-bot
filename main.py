import asyncio
import html
import logging
import re
import aiohttp
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ======================= [ 필수 설정 영역 ] =======================
TELEGRAM_BOT_TOKEN = "8730961288:AAGVNFJP4XV4f71ftC6A5yzJIIpaO8gdIdU"
NAVER_CLIENT_ID = "qrTlfL1IhNvxcDsy6JMP"
NAVER_CLIENT_SECRET = "p6kobEIYLf"

CHECK_INTERVAL_SECONDS = 60  # 기사 확인 주기 (60초)
# =================================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

user_keywords = {}
sent_links = set()


def clean_html(raw_html: str) -> str:
    cleantext = re.sub(r"<.*?>", "", raw_html)
    return html.unescape(cleantext)


async def fetch_news(session: aiohttp.ClientSession, keyword: str):
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": keyword, "display": 5, "sort": "date"}

    try:
        async with session.get(url, headers=headers, params=params, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("items", [])
    except Exception as e:
        logging.error(f"[{keyword}] 뉴스 호출 에러: {e}")
    return []


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_keywords:
        user_keywords[chat_id] = set()

    guide_text = (
        "📈 <b>주식·시황 실시간 뉴스 알림봇</b>\n\n"
        "관심 있는 종목이나 키워드를 등록하면 새 기사가 뜰 때 즉시 알려드립니다.\n\n"
        "<b>[명령어 안내]</b>\n"
        "• <code>/추가 [단어]</code> : 종목/시황 키워드 추가\n"
        "• <code>/삭제 [단어]</code> : 등록된 키워드 삭제\n"
        "• <code>/목록</code> : 현재 감시 중인 키워드 확인"
    )
    await update.message.reply_text(guide_text, parse_mode="HTML")


async def add_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("사용법: <code>/추가 [종목명/키워드]</code>", parse_mode="HTML")
        return

    keyword = " ".join(context.args).strip()
    if chat_id not in user_keywords:
        user_keywords[chat_id] = set()

    if keyword in user_keywords[chat_id]:
        await update.message.reply_text(f"⚠️ '<b>{keyword}</b>'은(는) 이미 등록되어 있습니다.", parse_mode="HTML")
        return

    async with aiohttp.ClientSession() as session:
        items = await fetch_news(session, keyword)
        for item in items:
            link = item.get("originallink") or item.get("link")
            if link:
                sent_links.add(link)

    user_keywords[chat_id].add(keyword)
    await update.message.reply_text(f"✅ '<b>{keyword}</b>' 등록 완료!\n지금부터 새 뉴스가 나오면 알려드립니다.", parse_mode="HTML")


async def remove_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("사용법: <code>/삭제 [단어]</code>", parse_mode="HTML")
        return

    keyword = " ".join(context.args).strip()
    if chat_id in user_keywords and keyword in user_keywords[chat_id]:
        user_keywords[chat_id].remove(keyword)
        await update.message.reply_text(f"🗑️ '<b>{keyword}</b>' 감시가 중단되었습니다.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"등록되지 않은 단어입니다: <b>{keyword}</b>", parse_mode="HTML")


async def list_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    keywords = user_keywords.get(chat_id, set())

    if not keywords:
        await update.message.reply_text("현재 등록된 키워드가 없습니다.\n<code>/추가 [단어]</code>로 등록해보세요.", parse_mode="HTML")
        return

    kw_list_str = "\n".join([f"• {kw}" for kw in sorted(keywords)])
    await update.message.reply_text(f"📋 <b>감시 중인 키워드 ({len(keywords)}개):</b>\n\n{kw_list_str}", parse_mode="HTML")


async def monitor_news_job(context: ContextTypes.DEFAULT_TYPE):
    if not user_keywords:
        return

    all_unique_keywords = set()
    for kw_set in user_keywords.values():
        all_unique_keywords.update(kw_set)

    if not all_unique_keywords:
        return

    async with aiohttp.ClientSession() as session:
        for kw in all_unique_keywords:
            items = await fetch_news(session, kw)

            for item in reversed(items):
                link = item.get("originallink") or item.get("link")
                if not link or link in sent_links:
                    continue

                title = clean_html(item.get("title", ""))
                desc = clean_html(item.get("description", ""))
                if len(desc) > 90:
                    desc = desc[:90] + "..."

                message = (
                    f"🚨 <b>[{kw} 기사 알림]</b>\n\n"
                    f"📰 <b>{title}</b>\n"
                    f"{desc}\n\n"
                    f"🔗 <a href='{link}'>기사 원문 보기</a>"
                )

                for chat_id, kws in user_keywords.items():
                    if kw in kws:
                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode="HTML",
                                disable_web_page_preview=False,
                            )
                            await asyncio.sleep(0.1)
                        except Exception as e:
                            logging.error(f"발송 실패: {e}")

                sent_links.add(link)

            await asyncio.sleep(0.3)

    if len(sent_links) > 3000:
        sent_links.clear()


def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("도움말", start_command))
    application.add_handler(CommandHandler("추가", add_keyword))
    application.add_handler(CommandHandler("삭제", remove_keyword))
    application.add_handler(CommandHandler("목록", list_keywords))

    job_queue = application.job_queue
    job_queue.run_repeating(monitor_news_job, interval=CHECK_INTERVAL_SECONDS, first=10)

    print("🚀 봇이 정상 실행되었습니다.")
    application.run_polling()


if __name__ == "__main__":
    main()
