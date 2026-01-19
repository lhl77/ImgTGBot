# LHL's Images Bot (ImgTGBot)

轻量的 Telegram 图床机器人，用于在聊天中快速上传图片并返回可直接使用的链接（Plain / Markdown / BBCode）。  
基于 python-telegram-bot + requests，支持 SQLite 本地持久化用户 token。

## 功能简介
- 登录（支持邮箱+密码获取 Token，或直接粘贴 Bearer Token —— 视实现版本而定）
- 查看账户信息 (/me)
- 设置默认存储策略（或每次选择）
- 发送图片自动上传并返回：
  - Plain 链接
  - Markdown 格式
  - BBCode 格式
- 购买/下单（通过平台接口）
- 本地 SQLite 存储用户 token 与默认策略

## 要求
- Python 3.9+
- 依赖请参见 `requirements.txt`

安装依赖：
```bash
python3 -m pip install -r requirements.txt
```

## 配置（config.json 示例）
在项目根目录创建 `config.json`，示例：
```json
{
  "bot_name": "ImgTGBot",
  "bot_token": "xxxx:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "lsky_api_base": "https://YOUR_DOMAIN/api/v1"
}
```
说明：
- bot_token: Telegram Bot Token
- lsky_api_base: 图床 API 基址（例如 https://img2.lhl.one/api/v1）
- allowed_group_ids: 若需要限定权限，填写允许的组 ID 列表（可为空）

## 运行
在项目目录下：
```bash
python bot.py
```
若打包为可执行文件，请确保 `config.json` 与可执行文件同目录。

## 常用命令（聊天内）
- /start — 显示欢迎与帮助
- /login — 登录（当前实现为邮箱+密码获取 Token；某些分支支持粘贴 Bearer Token）
- /me — 查看账户信息（容量、已用、组等）
- /set_storage — 设置默认上传存储策略（或选择“每次询问”）
- /logout — 退出登录（清除本地 token）
- 发送图片 — 自动上传（若未设置默认策略，机器人会让你选择本次使用的策略）

上传成功后机器人会以回复方式（尽量回复原图消息）返回：
- Plain 链接
- Markdown 用法示例（`![](<url>)` 或服务端返回的 markdown）
- BBCode 用法示例（`[img]<url>[/img]` 或服务端返回的 bbcode）

## 数据持久化
本项目使用 SQLite（`users.db`）保存用户 token 与默认策略。数据库在模块导入时自动初始化。

## 接口相关
默认使用 Lsky 风格 REST API（`/upload`、`/profile`、`/strategies` 等）。请确保 `lsky_api_base` 指向正确的 API 基址，并根据你的 API 返回结构（例如 `data.links.url`、`data.url`、`markdown`、`bbcode` 等字段）进行兼容性调整。

## 开发与调试
- 日志级别可在源码中调整（logging.basicConfig）
- 若要改为只接受 Bearer Token 登录，参考仓库中 `lsky_bot copy.py` 分支实现（`/login` 对话改为接收 Token 并调用 `/profile` 验证）

## 许可证
按仓库原始许可证使用（请在仓库根加入 LICENSE 文件）。

欢迎在 Issues 中反馈问题或提交 PR。
