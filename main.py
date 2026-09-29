import asyncio
import html
import logging
import os
import re
from urllib.parse import quote
from aiohttp import ClientSession, web
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ======================= [ 발급 키 설정 ] =======================
TELEGRAM_BOT_TOKEN = "8730961288:AAGVNFJP4XV4f71ftC6A5yzJIIpaO8gdIdU"
NAVER_CLIENT_ID = "qrTlfL1IhNvxcDsy6JMP"
NAVER_CLIENT_SECRET = "p6kobEIYLf"

CHECK_INTERVAL_SECONDS = 60
# =============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

user_keywords = {}
sent_links = set()


def clean_html(raw_html: str) -> str:
    cleantext = re.sub(r"<.*?>", "", raw_html)
    return html.unescape(cleantext)


async def fetch_news(session: ClientSession, keyword: str):
    # 한글 키워드 인코딩 처리
    encoded_kw = quote(keyword.strip())
    url = f"https://openapi.naver.com/v1/search/news.json?query={encoded_kw}&display=10&sort=date"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    try:
        async with session.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("items", []), None
            else:
                err_text = await resp.text()
                logging.error(f"[{keyword}] 네이버 API 에러 ({resp.status}): {err_text}")
                return [], f"API 에러코드 {resp.status}"
    except Exception as e:
        logging.error(f"[{keyword}] 통신 실패: {e}")
        return [], str(e)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_keywords:
        user_keywords[chat_id] = set()

    guide_text = (
        "📈 <b>주식·시황 실시간 뉴스 알림봇</b>\n\n"
        "<b>[명령어 안내]</b>\n"
        "• <code>/add [종목/키워드]</code> : 키워드 추가\n"
        "  (예: <code>/add 삼성전자</code>, <code>/add 코스피</code>)\n"
        "• <code>/del [단어]</code> : 등록된 키워드 삭제\n"
        "• <code>/list</code> : 현재 감시 중인 키워드 목록\n"
        "• <code>/help</code> : 사용 안내"
    )
    await update.message.reply_text(guide_text, parse_mode="HTML")


async def add_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("사용법: <code>/add [종목명/키워드]</code>", parse_mode="HTML")
        return

    keyword = " ".join(context.args).strip()
    if chat_id not in user_keywords:
        user_keywords[chat_id] = set()

    if keyword in user_keywords[chat_id]:
        await update.message.reply_text(f"⚠️ '<b>{keyword}</b>'은(는) 이미 등록되어 있습니다.", parse_mode="HTML")
        return

    async with ClientSession() as session:
        items, err = await fetch_news(session, keyword)

    # API 에러 발생 시 즉각 사용자에게 알림
    if err:
        await update.message.reply_text(
            f"❌ <b>네이버 API 호출 실패:</b> {err}\n\n"
            f"네이버 개발자 센터에서 '검색' 서비스가 활성화되어 있는지 확인해 주세요.",
            parse_mode="HTML",
        )
        return

    user_keywords[chat_id].add(keyword)
    await update.message.reply_text(f"✅ '<b>{keyword}</b>' 등록 완료!\n새 뉴스가 나오면 실시간으로 전달합니다.", parse_mode="HTML")

    # 기존 최신 기사는 중복 전송 방지를 위해 기록하고, 가장 최근 기사 1개를 샘플로 즉시 전송
    latest_item = None
    for idx, item in enumerate(items):
        link = item.get("originallink") or item.get("link")
        if link:
            sent_links.add(link)
            if idx == 0:
                latest_item = item

    if latest_item:
        title = clean_html(latest_item.get("title", ""))
        desc = clean_html(latest_item.get("description", ""))
        link = latest_item.get("originallink") or latest_item.get("link")
        sample_msg = (
            f"🔔 <b>[{keyword} 최신 기사 테스트]</b>\n\n"
            f"📰 <b>{title}</b>\n"
            f"{desc[:90]}...\n\n"
            f"🔗 <a href='{link}'>기사 원문 보기</a>"
        )
        await update.message.reply_text(sample_msg, parse_mode="HTML")
    else:
        await update.message.reply_text(f"ℹ️ '{keyword}' 관련 현재 검색된 최근 뉴스가 없습니다.", parse_mode="HTML")


async def remove_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("사용법: <code>/del [단어]</code>", parse_mode="HTML")
        return

    keyword = " ".join(context.args).strip()
    if chat_id in user_keywords and keyword in user_keywords[chat_id]:
        user_keywords[chat_id].remove(keyword)
        await update.message.reply_text(f"🗑️ '<b>{keyword}</b>' 감시가 취소되었습니다.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"등록되지 않은 키워드입니다: <b>{keyword}</b>", parse_mode="HTML")


async def list_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    keywords = user_keywords.get(chat_id, set())

    if not keywords:
        await update.message.reply_text("현재 등록된 키워드가 없습니다.\n<code>/add [단어]</code>로 등록하세요.", parse_mode="HTML")
        return

    kw_list_str = "\n".join([f"• {kw}" for kw in sorted(keywords)])
    await update.message.reply_text(f"📋 <b>감시 중인 키워드 ({len(keywords)}개):</b>\n\n{kw_list_str}", parse_mode="HTML")


async def background_monitoring(app: Application):
    await asyncio.sleep(5)
    while True:
        try:
            if user_keywords:
                all_unique_keywords = set()
                for kw_set in user_keywords.values():
                    all_unique_keywords.update(kw_set)

                if all_unique_keywords:
                    async with ClientSession() as session:
                        for kw in all_unique_keywords:
                            items, _ = await fetch_news(session, kw)

                            for item in reversed(items):
                                link = item.get("originallink") or item.get("link")
                                if not link or link in sent_links:
                                    continue

                                title = clean_html(item.get("title", ""))
                                desc = clean_html(item.get("description", ""))
                                if len(desc) > 90:
                                    desc = desc[:90] + "..."

                                message = (
                                    f"🚨 <b>[{kw} 새 뉴스 알림]</b>\n\n"
                                    f"📰 <b>{title}</b>\n"
                                    f"{desc}\n\n"
                                    f"🔗 <a href='{link}'>기사 원문 보기</a>"
                                )

                                for chat_id, kws in user_keywords.items():
                                    if kw in kws:
                                        try:
                                            await app.bot.send_message(
                                                chat_id=chat_id,
                                                text=message,
                                                parse_mode="HTML",
                                            )
                                            await asyncio.sleep(0.1)
                                        except Exception as e:
                                            logging.error(f"전송 실패: {e}")

                                sent_links.add(link)

                            await asyncio.sleep(0.3)

            if len(sent_links) > 3000:
                sent_links.clear()

        except Exception as e:
            logging.error(f"모니터링 오류: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def handle_ping(request):
    return web.Response(text="Stock Bot Live!")


async def run_web_server():
    server = web.Application()
    server.router.add_get("/", handle_ping)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"웹서버 구동 (Port {port})")


async def post_init(application: Application):
    asyncio.create_task(background_monitoring(application))
    asyncio.create_task(run_web_server())


def main():
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("add", add_keyword))
    application.add_handler(CommandHandler("del", remove_keyword))
    application.add_handler(CommandHandler("list", list_keywords))

    print("🚀 봇이 정상 실행되었습니다.")
    application.run_polling()


if __name__ == "__main__":
    main()
