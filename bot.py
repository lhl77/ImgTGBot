# -*- coding: utf-8 -*-
import json
import os
import sys
import logging
import requests
import math
import sqlite3
import asyncio
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
    CallbackQueryHandler,
)

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()

def load_config():
    config_path = os.path.join(BASE_DIR, "config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError("❌ config.json 未找到，请创建该文件！")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

BOT_VERSION = "v0.1";
CONFIG = load_config()
BOT_NAME = CONFIG["bot_name"]
BOT_TOKEN = CONFIG["bot_token"]
LSKY_API_BASE = CONFIG["lsky_api_base"]
(
    WAITING_FOR_EMAIL,
    WAITING_FOR_PASSWORD,
) = range(2)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

def api_request(method, endpoint, headers=None, **kwargs):
    url = f"{LSKY_API_BASE}{endpoint}"
    default_headers = {"Accept": "application/json"}
    if headers:
        default_headers.update(headers)
    try:
        resp = requests.request(method, url, headers=default_headers, timeout=15, **kwargs)
        return resp.json() if resp.status_code in (200, 201, 422) else {"status": "error", "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        logger.exception("Request failed")
        return {"status": "error", "message": str(e)}

async def api_call(update, context, method, endpoint, headers=None, **kwargs):
    chat_id = None
    try:
        if getattr(update, "callback_query", None) and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id
        elif getattr(update, "message", None) and update.message.chat:
            chat_id = update.message.chat.id
        elif getattr(update, "effective_chat", None) and update.effective_chat:
            chat_id = update.effective_chat.id
    except Exception:
        chat_id = None

    if chat_id and context:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass

    loop = asyncio.get_running_loop()
    resp = await loop.run_in_executor(None, lambda: api_request(method, endpoint, headers=headers, **kwargs))
    return resp

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📌 欢迎使用 {BOT_NAME}\n"
        "🤖 直接发送图片 — 登录后即可直接上传\n\n"
        "/login — 登录图床\n"
        "/me — 查看账户信息\n"
        "/set_storage — 设置默认存储方案\n"
        "/logout — 退出登录（设置不保存）\n\n"
        f'<a href="https://github.com/lhl77/ImgTGBot">ImgTGBot</a> · {BOT_VERSION} · Made With ♥️',
        parse_mode="HTML",
        disable_web_page_preview=True
    )


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.user_data.get("lsky_token"):
        context.user_data.update(load_user_record(user_id))

    if context.user_data.get("lsky_token"):
        await update.message.reply_text("🔒 您当前已登录。发送 /me 查看账户信息，或发送 /logout 退出登录。")
        return ConversationHandler.END

    await update.message.reply_text("📧 请输入你的邮箱地址：")
    return WAITING_FOR_EMAIL

async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if "@" not in email:
        await update.message.reply_text("⚠️ 邮箱格式无效，请重新输入：")
        return WAITING_FOR_EMAIL
    context.user_data["login_email"] = email
    await update.message.reply_text("🔑 请输入密码：")
    return WAITING_FOR_PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"无法删除密码消息: {e}")

    status_msg = None
    try:
        status_msg = await update.message.reply_text("⚠️ 尝试登录中...")
    except Exception as e:
        logger.warning(f"无法发送状态消息: {e}")

    email = context.user_data.get("login_email")
    
    payload = {
        "email": email,
        "password": password
    }

    resp = await api_call(update, context, "POST", "/tokens", json=payload)

    if status_msg:
        try:
            await status_msg.delete()
        except Exception as e:
            logger.warning(f"无法删除状态消息: {e}")

    if resp.get("status") and "token" in resp.get("data", {}):
        token = resp["data"]["token"]
        context.user_data["lsky_token"] = token
        await update.message.reply_text(
            f"✅ 登录成功！\n\n"
            "现在你可以直接发送图片进行上传了。"
        )

        # 保存到 SQLite：token
        user_id = update.effective_user.id
        save_user_token(user_id, token)

    else:
        msg = resp.get("message", "未知错误")
        errors = resp.get("data", {}).get("errors", {})
        if errors:
            msg = "; ".join([f"{k}: {'; '.join(v)}" for k, v in errors.items()])
        await update.message.reply_text(f"❌ 登录失败：{msg}\n\n请重试 /login")

    return ConversationHandler.END

def format_storage(kb: float) -> str:
    if kb == 0:
        return "0 KB"
    size_names = ["KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(kb, 1024)))
    p = math.pow(1024, i)
    s = round(kb / p, 2)
    return f"{s} {size_names[i]}"

async def me_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.user_data.get("lsky_token"):
        rec = load_user_record(user_id)
        context.user_data.update(rec)

    token = context.user_data.get("lsky_token")
    if not token:
        await update.message.reply_text("🔒 请先登录！发送 /login")
        return

    headers = {"Authorization": f"Bearer {token}"} 

    profile_resp = await api_call(update, context, "GET", "/profile", headers=headers)
    if not profile_resp.get("status"):
        await update.message.reply_text("❌ 获取用户信息失败，请重试。")
        return

    user = profile_resp["data"]
    name = user.get("name", "未知")
    email = user.get("email", "未设置")
    used = user.get("used_capacity", 0)
    total = user.get("capacity", 0)

    message = (
        f"👤 **{name}** 您好!\n"
        f"📧 邮箱: {email}\n\n"
        f"💾 存储: {format_storage(used)} / {format_storage(total)}"
    )

    await update.message.reply_text(message, parse_mode="Markdown")

STORAGE_CALLBACK_PREFIX = "set_storage_"
async def set_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.user_data.get("lsky_token"):
        context.user_data.update(load_user_record(user_id))

    token = context.user_data.get("lsky_token")
    if not token:
        await update.message.reply_text("🔒 请先登录！发送 /login")
        return

    headers = {"Authorization": f"Bearer {token}"}
    resp = await api_call(update, context, "GET", "/strategies", headers=headers)

    if not resp.get("status"):
        await update.message.reply_text("❌ 获取存储列表失败，请重试。")
        return

    storages = resp["data"].get("strategies", [])
    if not storages:
        await update.message.reply_text("📭 当前没有可用的存储方案。")
        return

    storage_map = {s["id"]: s for s in storages}

    current_id = context.user_data.get("lsky_storage_id")
    reply_parts = []

    if current_id is not None and current_id in storage_map:
        current = storage_map[current_id]
        reply_parts.append(
            f"✅ 当前使用存储方案：\n"
            f"`{current['name']}`\n"
        )

    reply_parts.append("请选择要默认使用的存储方案：")

    buttons = []
    for storage in storages:
        text = f"{storage['name']}"
        callback_data = f"{STORAGE_CALLBACK_PREFIX}{storage['id']}"
        buttons.append([InlineKeyboardButton(text, callback_data=callback_data)])
    buttons.append([InlineKeyboardButton("每次询问", callback_data=f"{STORAGE_CALLBACK_PREFIX}default")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "\n".join(reply_parts),
        reply_markup=reply_markup,
        parse_mode="MarkdownV2"
    )
       
async def handle_storage_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith(STORAGE_CALLBACK_PREFIX):
        return
    if data == f"{STORAGE_CALLBACK_PREFIX}default":
        context.user_data.pop("lsky_storage_id", None)  
        user_id = query.from_user.id
        save_user_storage(user_id, None)
        await query.edit_message_text("👌好的！每次上传时会询问您。")
        return

    try:
        storage_id = int(data[len(STORAGE_CALLBACK_PREFIX):])
    except ValueError:
        await query.edit_message_text("⚠️ 无效的存储 ID。")
        return

    context.user_data["lsky_storage_id"] = storage_id

    user_id = query.from_user.id
    save_user_storage(user_id, storage_id)

    token = context.user_data.get("lsky_token")
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        resp = await api_call(update, context, "GET", "/strategies", headers=headers)
        if resp.get("status"):
            storages = {s["id"]: s["name"] for s in resp["data"].get("strategies", [])}
            name = storages.get(storage_id, f"ID {storage_id}")
        else:
            name = f"ID {storage_id}"
    else:
        name = f"ID {storage_id}"

    await query.edit_message_text(f"✅ 已切换存储方案为: `{name}`",parse_mode="Markdown")

# ================== 上传功能 ==================
# 辅助函数
async def _prompt_for_temp_storage(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str, file_bytes: bytearray):
    # 获取可用存储
    headers = {"Authorization": f"Bearer {token}"}
    resp = await api_call(update, context, "GET", "/strategies", headers=headers)

    if not resp.get("status"):
        await update.message.reply_text("❌ 获取存储列表失败，无法上传。")
        return

    storages = resp["data"].get("strategies", [])
    if not storages:
        await update.message.reply_text("📭 无可用存储方案，无法上传。")
        return

    # 暂存图片数据和 token（用于后续上传）
    context.user_data["temp_upload_file"] = file_bytes
    context.user_data["temp_upload_token"] = token

    # 构建按钮
    buttons = []
    for storage in storages:
        text = f"{storage['name']} "
        callback_data = f"{TEMP_STORAGE_PREFIX}{storage['id']}"
        buttons.append([InlineKeyboardButton(text, callback_data=callback_data)])

    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("请选择本次上传的存储方案：", reply_markup=reply_markup)
# 辅助函数
async def _do_upload(update, context: ContextTypes.DEFAULT_TYPE, token: str, file_bytes: bytearray, storage_id: int):
    # ✅ 关键：字段名必须是 storage_id（不是 strategy_id）
    data = {"strategy_id": storage_id}
    files = {"file": ("image.jpg", bytes(file_bytes), "image/jpeg")}

    headers = {"Authorization": f"Bearer {token}"}
    resp = api_request("POST", "/upload", headers=headers, data=data, files=files)

    if resp.get("status"):
        url = resp["data"]["links"]["url"]  # ✅ 注意：是 public_url，不是 links.url

        # 构建按钮：打开链接 + 将链接填入当前聊天输入框以便复制
        buttons = [
            [InlineKeyboardButton("🔗 打开链接", url=url)],
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        # 使用等宽格式输出链接（Markdown 内联代码）
        text = f"✅ 上传成功！\n\n🔗URL:\n`{url}`\n\n📝Markdown:\n`![]({url})`\n\n💬BBCode:\n`[img]{url}[/img]`"

        # 兼容 update 为 Update 或 CallbackQuery 的情况，使用 bot 直接发送消息
        chat_id = None
        try:
            # Update 对象
            chat = getattr(update, "effective_chat", None)
            if chat:
                chat_id = chat.id
        except Exception:
            chat_id = None

        if not chat_id:
            # CallbackQuery 或其它对象，尝试取 message.chat.id
            try:
                chat_id = update.message.chat.id  # type: ignore
            except Exception:
                # 最后退回到 from_user 的 id（私聊场景可用）
                try:
                    chat_id = update.from_user.id  # type: ignore
                except Exception:
                    chat_id = None

        if chat_id:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            # 回退：直接回复（若 update 有 reply 接口）
            try:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")  # type: ignore
            except Exception:
                logger.warning("无法发送上传成功消息到聊天")
    else:
        error_msg = resp.get("message", "未知错误")
        try:
            await update.message.reply_text(f"❌ 上传失败：{error_msg}")  # type: ignore
        except Exception:
            logger.warning("无法发送上传失败消息")

# 临时选择回调前缀（区别于 set_storage 的永久设置）
TEMP_STORAGE_PREFIX = "temp_upload_storage_"

async def upload_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 尝试从 DB 加载（如果 context 里没有）
    user_id = update.effective_user.id
    if not context.user_data.get("lsky_token"):
        context.user_data.update(load_user_record(user_id))

    token = context.user_data.get("lsky_token")
    if not token:
        await update.message.reply_text("🔒 请先登录！")
        return

    # 下载图片（必须提前下载，因为 callback_query 里拿不到原消息）
    photo = await update.message.photo[-1].get_file()
    file_bytes = await photo.download_as_bytearray()

    # 检查是否已设置默认存储
    storage_id = context.user_data.get("lsky_storage_id")

    if storage_id is not None:
        # ✅ 有默认设置，直接上传
        await _do_upload(update, context, token, file_bytes, storage_id)
    else:
        # ❓ 无默认设置，让用户临时选择
        await _prompt_for_temp_storage(update, context, token, file_bytes)

async def handle_temp_storage_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith(TEMP_STORAGE_PREFIX):
        return

    try:
        storage_id = int(data[len(TEMP_STORAGE_PREFIX):])
    except (ValueError, TypeError):
        await query.edit_message_text("⚠️ 无效的存储 ID。")
        return

    # 从 user_data 取回暂存的数据
    file_bytes = context.user_data.pop("temp_upload_file", None)
    token = context.user_data.pop("temp_upload_token", None)

    if not file_bytes or not token:
        await query.edit_message_text("⚠️ 上传上下文已过期，请重新发送图片。")
        return

    # 编辑提示消息为“正在上传...”
    await query.edit_message_text("📤 正在上传中...")

    # 执行上传
    await _do_upload(query, context, token, file_bytes, storage_id)

# ========== SQLite 持久化：用户信息 ==========
DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            token TEXT,
            storage_id INTEGER
        )
        """
    )
    conn.commit()
    conn.close()

def save_user_token(user_id: int, token: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO users(user_id, token) VALUES(?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET token=excluded.token",
        (user_id, token),
    )
    conn.commit()
    conn.close()

def save_user_storage(user_id: int, storage_id: Optional[int]):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if storage_id is None:
        c.execute("UPDATE users SET storage_id=NULL WHERE user_id=?", (user_id,))
    else:
        c.execute(
            "INSERT INTO users(user_id, storage_id) VALUES(?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET storage_id=excluded.storage_id",
            (user_id, storage_id),
        )
    conn.commit()
    conn.close()

def load_user_record(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT token, storage_id FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return {}
    token, storage_id= row
    return {"lsky_token": token, "lsky_storage_id": storage_id}

# 在模块导入时初始化 DB
init_db()

# ================== 主程序 ==================

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/logout — 清除会话缓存并从本地 SQLite 删除用户的 token/storage 信息"""
    user_id = update.effective_user.id

    # 若 context 无 token，尝试从 DB 加载以判断当前是否已登录
    if not context.user_data.get("lsky_token"):
        context.user_data.update(load_user_record(user_id))

    if not context.user_data.get("lsky_token"):
        await update.message.reply_text("ℹ️ 您当前未登录，无法退出。发送 /login 登录。")
        return

    # 清除上下文缓存
    context.user_data.pop("lsky_token", None)
    context.user_data.pop("lsky_storage_id", None)

    # 从数据库清除用户的敏感/设置字段
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET token=NULL, storage_id=NULL WHERE user_id=?",
            (user_id,),
        )
        conn.commit()
    except Exception as e:
        logger.exception("退出时清除 DB 失败")
    finally:
        conn.close()

    await update.message.reply_text("🔓 已退出登录")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # 登录对话流：由 /login 触发
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            WAITING_FOR_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email)],
            WAITING_FOR_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
        },
        fallbacks=[],
    )

    # 注册所有处理器
    app.add_handler(CommandHandler("start", start))
    app.add_handler(login_conv)
    app.add_handler(CommandHandler("me", me_info))
    app.add_handler(MessageHandler(filters.PHOTO, upload_photo))
    app.add_handler(CommandHandler("set_storage", set_storage))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CallbackQueryHandler(handle_storage_selection, pattern=f"^{STORAGE_CALLBACK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(
        handle_temp_storage_selection,
        pattern=f"^{TEMP_STORAGE_PREFIX}"
    ))
    logger.warning("🚀 ImgTGBot 已启动（/start 显示菜单，/login 登录）")
    app.run_polling()

if __name__ == "__main__":
    main()
