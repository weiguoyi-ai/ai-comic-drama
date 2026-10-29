# 🎬 AI 漫剧工坊 (AI Comic Drama Studio)

<p align="center">
  <img src="docs/preview.jpg" width="720" alt="AI 漫剧工坊效果预览">
</p>

<p align="center">
  <a href="README.en.md">English</a> · <b>简体中文</b>
</p>

<p align="center">
  <a href="https://github.com/weiguoyi-ai/ai-comic-drama/actions/workflows/ci.yml"><img src="https://github.com/weiguoyi-ai/ai-comic-drama/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776ab" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</p>

一个开源的 **AI 漫剧（漫画短剧）制作工具**：输入故事或剧本，AI 自动生成分镜脚本、每幕画面、角色配音与字幕，一键合成为完整短视频。

**支持三种运行模式**：云端 API（画质最佳）/ **全本地离线（永久 0 元、断网可用）** / 自动切换。

## ✨ 功能

| 模块 | 说明 |
|---|---|
| 📝 剧本转分镜 | 调用 LLM 把小说/剧本改编为结构化分镜（标题/旁白/台词/**说话角色**/画面描述） |
| 🖼 分镜生图 | 火山方舟豆包 Seedream 出图，可用首图作参考保持角色形象一致 |
| 🎭 多角色配音 | **按角色名自动分配音色**，同一角色全程一致、不同角色不撞音；支持逐幕手动指定 |
| 🎵 背景音乐 | 把音乐丢进 `assets/bgm/`，合成时自动随机挑选并混音（音量 12%、结尾淡出） |
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

- 生图：SD1.5（可替换为 DreamShaper/Anything 等任意 SD1.5 动漫模型）+ LCM 4 步加速 + channels_last 优化，
  在 i5-1135G7 纯 CPU 实测 **约 3~3.7 分钟/张**（`quality: fast` 约 3.2 分钟，`normal` 约 3.7 分钟；
  无独显的物理上限，有 NVIDIA 显卡会快 20 倍以上）
- 分镜：Qwen2.5-1.5B-Instruct，纯 CPU 实测约 **1~1.5 分钟**
- 配音：Piper 或 Windows SAPI 中文语音（完全离线、秒级）；都不可用时自动回退 edge-tts（需联网）
- 画质档位（`config.json → local.quality`）：`fast`（448×768）/ `normal`（512×896，默认）/ `high`（576×1024）
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

## 🎭 多角色配音

分镜阶段 AI 会给每句台词标注 **说话角色（speaker）**，配音时按角色自动分配音色：

- **同一角色全程一个音色**、不同角色尽量不撞音（分配结果记录在该项目的 `_voices.json` 里）
- 音色池：晓晓 / 晓伊 / 云希 / 云夏 / 云健 / 晓北，可在界面「本幕音色」逐幕覆盖
- 想固定某角色的声音，改 `config.json`：

```json
"tts": {
  "voice": "zh-CN-XiaoxiaoNeural",
  "voice_map": {
    "旁白": { "voice": "zh-CN-XiaoxiaoNeural", "rate": -4 },
    "女主": { "voice": "zh-CN-XiaoyiNeural", "rate": 0 }
  }
}
```

> `voice_map` 支持「完全匹配」和「模糊包含」（如 `女主` 可命中 `女主林晚`）；
> 未登记的角色会按字母顺序分配一个尚未占用的音色。
> 本地 SAPI 模式只有一个中文声线，会用 ±语速（`rate`）来区分角色。

## 🎵 背景音乐

把 `.mp3` / `.wav` / `.m4a` 放进 **`assets/bgm/`**，合成时自动随机挑一首并混音：

```json
"bgm": { "enabled": true, "path": "", "volume": 0.12 }
```

- `path` 留空 = 从 `assets/bgm/` 随机选；填文件名 = 固定用那首；`enabled: false` = 关闭
- `volume` 建议 0.05~0.2，人声不会被盖住；结尾自动 2 秒淡出
- 界面第三步的「自动加背景音乐」可以临时开关
- 仓库自带的 `sample_ambient.mp3` 是用 ffmpeg 合成的原创铺底音，可自由使用

## 📁 项目结构

```
ai-comic-drama/
├── server.py           # FastAPI 后端 + API
├── providers.py        # AI Provider 适配层（auto/local/cloud 三模式 + 音色分配）
├── compose.py          # ffmpeg 视频合成管线（Ken Burns + 字幕烧录 + BGM 混音）
├── local_image.py      # 本地生图（SD1.5 + LCM，纯 CPU）
├── local_llm.py        # 本地分镜（Qwen2.5-1.5B）
├── local_tts.py        # 本地配音（Piper / Windows SAPI）
├── download_models.py  # 本地模型一键下载（ModelScope 国内源）
├── check_ark.py        # 云端 API Key 自检脚本
├── static/index.html   # 网页前端
├── assets/bgm/         # 背景音乐目录（自带一首原创示例）
├── config.example.json # 模型配置模板
├── requirements.txt / requirements-local.txt
├── 启动.bat            # Windows 一键启动
└── projects/           # 每个项目的图片、音频、成片输出
```

## ❓ 常见问题

- **piper-tts 1.8.0 的 Windows 轮子有已知 bug**（espeak 数据路径编译期写死，中文合成出空音频），
  本项目已自动处理：检测到空音频会切换到 Windows SAPI 离线语音，无需干预
- **视频合成在中文用户名路径下失败**？已修复：concat/字幕阶段在项目目录内以相对路径执行
- 本地生图慢？把 `config.json` 里 `local.quality` 改为 `"fast"`、`steps` 改为 `3`，约 2.5 分钟/张

## 🗺 Roadmap

- [x] 竖屏 9:16 输出适配抖音/快手
- [x] 零费用全本地离线模式（SD + Qwen + Piper/SAPI）
- [x] 角色一致性（Seedream 参考图图生图）
- [x] 多角色多音色配音（按角色自动分配）
- [x] 背景音乐自动混音
- [ ] 背景音乐按情绪自动匹配（分镜情感 → 曲目）
- [ ] IP-Adapter 本地角色一致性
- [ ] 一键批量生成多集连播

## License

[MIT](LICENSE) © 2026 魏果毅 (Wei Guoyi)
