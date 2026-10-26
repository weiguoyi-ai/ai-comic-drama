# 🎬 AI 漫剧工坊 (AI Comic Drama Studio)

一个开源的 **AI 漫剧（漫画短剧）制作工具**：输入故事或剧本，AI 自动生成分镜脚本、每幕画面、角色配音与字幕，一键合成为完整短视频。

![流程](https://img.shields.io/badge/流程-剧本→分镜→生图→配音→成片-4f5df0)

## ✨ 功能

| 模块 | 说明 |
|---|---|
| 📝 剧本转分镜 | 调用 LLM 把小说/剧本改编为结构化分镜（标题/旁白/台词/画面描述） |
| 🖼 分镜生图 | 火山方舟豆包 Seedream 出图，可用首图作参考保持角色形象一致 |
| 🎙 AI 配音 | edge-tts 免费语音合成，多种中文音色可选 |
| 🎬 视频合成 | ffmpeg 自动合成：Ken Burns 动效 + SRT 字幕烧录 → 竖屏 720×1280 / 横屏 1280×720 |
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

## 💰 零积分 / 零费用运行（三种模式自动切换）

`config.json` 的 `"mode"` 决定运行方式，**没有 Key 也能出真图**：

| mode | 行为 | 费用 | 联网 | 速度 |
|---|---|---|---|---|
| `auto`（默认） | 有云端 Key 走云端，没 Key 自动落本地，本地没模型才用占位图 | 0 | 按需 | 快/慢自适应 |
| `local` | 强制全本地：本地 SD 生图 + 本地 Qwen 写分镜 + 本地 Piper 配音 | **永久 0 元** | **完全不用** | 慢（约 1 分钟/图） |
| `cloud` | 强制走火山方舟 | 按量计费（有免费额度） | 需要 | 快、画质最好 |

### 开通「全本地免费模式」

```bash
# 1. 安装本地推理依赖（torch 用 CPU 专用源，只有 124MB）
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-local.txt

# 2. 下载本地模型（约 5GB，一次性；优先走 ModelScope 国内源）
python download_models.py

# 3. 启动（会自动检测到本地模型并切过去）
python server.py
```

然后把 `config.json` 里的 `"mode"` 改成 `"local"`，即可**断网使用、不花一分钱**。

- 生图：SD1.5（可替换为 DreamShaper/Anything 等任意 SD1.5 动漫模型）+ LCM 加速，512×896 → 放大到 720×1280，
  在 i5-1135G7 纯 CPU 实测约 **3–6 分钟/张**（无独显的物理上限；有 NVIDIA 显卡会快 20 倍以上）
- 分镜：Qwen2.5-1.5B-Instruct，纯 CPU 实测约 **1–1.5 分钟**
- 配音：Piper 离线声线（秒级；模型缺失时自动用 edge-tts）
- 想换更二次元的画风：把任意 SD1.5 动漫模型文件替换进 `models/sd-base/` 即可

> 本地模式是「不花钱」的代价换「慢 + 画质中等」。追求参考视频那种质感，仍推荐云端 Seedream。

## 🔑 接入云端模型（可选，火山方舟 · 一个 Key 搞定全流程）

本项目默认对接**火山方舟**：豆包 Seedream 负责出图、豆包 Seed 负责分镜文案，配音用免费的 edge-tts。

### 第 1 步：获取 API Key（约 3 分钟）

1. 打开 [火山方舟控制台](https://console.volcengine.com/ark)，用手机号注册并完成实名认证
2. 左侧菜单进入 **开通管理**，开通这两个模型：
   - `Doubao-Seedream-4.0`（图像生成）
   - `Doubao-Seed-1.6-flash`（文本，用于分镜）
3. 左侧菜单进入 **API Key 管理** → **创建 API Key**，复制生成的 Key（形如 `xxxxxxxx-xxxx-...`）

> 各模型有一定免费额度，超出后按量计费；具体以控制台价格页为准。

### 第 2 步：填入配置

打开项目根目录的 `config.json`，把 Key 填进 `llm.api_key` 和 `image.api_key`（两处都要填，或设置环境变量 `ARK_API_KEY`）：

```json
{
  "llm":   { "api_key": "你的Key", "model": "doubao-seed-1-6-flash-250828" },
  "image": { "api_key": "你的Key", "model": "doubao-seedream-4-0-250828",
             "size_portrait": "1152x2048", "size_landscape": "2048x1152" }
}
```

### 第 3 步：刷新页面

保存配置后刷新 http://127.0.0.1:8000 ，顶部出现绿色横幅「已接入火山方舟」即成功。
没填 Key 时自动降级为占位图模式，不会报错。

### 换成其他模型

任何 **OpenAI 兼容接口** 都能接，只改 `base_url` / `model` / `api_key` 即可：

| 用途 | 可选方案 |
|---|---|
| 分镜文案 | 豆包 Seed、智谱 glm-4-flash、DeepSeek、Kimi |
| 文生图 | 豆包 Seedream 4.0/5.0、智谱 cogview、通义万相、Flux |
| 配音 | edge-tts（内置免费）、火山语音合成 |

### 🧚 画风与尺寸

- 内置 6 种画风预设，其中 **「仙侠玄幻·唯美写实」** 为抖音爆款漫剧画风（冰蓝色调、仙气光效、飘逸长发）
- 支持 **9:16 竖屏**（720×1280）与 16:9 横屏（1280×720）
- 勾选 **角色一致性** 后，第 2 幕起会以首张图作参考图（Seedream 图生图），人物形象更统一

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
