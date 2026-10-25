# 🎬 AI 漫剧工坊 (AI Comic Drama Studio)

一个开源的 **AI 漫剧（漫画短剧）制作工具**：输入故事或剧本，AI 自动生成分镜脚本、每幕画面、角色配音与字幕，一键合成为完整短视频。

![流程](https://img.shields.io/badge/流程-剧本→分镜→生图→配音→成片-4f5df0)

## ✨ 功能

| 模块 | 说明 |
|---|---|
| 📝 剧本转分镜 | 调用 LLM 把小说/剧本改编为结构化分镜（标题/旁白/台词/画面描述） |
| 🖼 分镜生图 | 调用文生图模型生成每幕画面，带角色外貌提示保持形象一致 |
| 🎙 AI 配音 | edge-tts 免费语音合成，多种中文音色可选 |
| 🎬 视频合成 | ffmpeg 自动合成：Ken Burns 动效 + SRT 字幕烧录 → 1280×720 mp4 |
| 🧪 Mock 模式 | 不配置任何 API Key 也能跑通全流程（占位图 + 静音），方便开发调试 |

## 🚀 快速开始

```bash
# 1. 安装依赖（Python 3.10+）
pip install -r requirements.txt

# 2. 启动
python server.py

# 3. 打开浏览器
# http://127.0.0.1:8000
```

默认使用 **Mock 模式**，无需任何 Key 即可体验完整流程。

## 🔑 接入真实模型

复制 `config.example.json` 为 `config.json`，填入你的 API Key，并把对应 `"mock"` 改为 `false`：

```json
{
  "llm": {
    "mock": false,
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "api_key": "你的KEY",
    "model": "glm-4-flash"
  },
  "image": {
    "mock": false,
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "api_key": "你的KEY",
    "model": "cogview-3-flash",
    "size": "1344x768"
  }
}
```

只要是 **OpenAI 兼容接口** 都能接，推荐组合（国内可访问）：

| 用途 | 推荐 | 备注 |
|---|---|---|
| LLM 分镜 | 智谱 glm-4-flash | 有免费额度 |
| 文生图 | 智谱 cogview-3-flash / 阿里通义万相 | cogview-3-flash 免费 |
| 配音 | edge-tts | 完全免费，无需 Key |

其他可替换：DeepSeek、Kimi、豆包（LLM）；Flux、SD（图）等。

## 📁 项目结构

```
ai-comic-drama/
├── server.py          # FastAPI 后端 + API
├── providers.py       # AI Provider 适配层（LLM/生图/TTS，mock 与真实可切换）
├── compose.py         # ffmpeg 视频合成管线
├── static/index.html  # 网页前端
├── config.example.json# 模型配置模板
├── requirements.txt
└── projects/          # 每个项目的图片、音频、成片输出
```

## 🗺 Roadmap

- [ ] 角色一致性增强（参考图 / IP-Adapter）
- [ ] 多角色多音色配音分配
- [ ] 背景音乐自动混音
- [ ] 竖屏 9:16 输出适配抖音/快手

## License

MIT
