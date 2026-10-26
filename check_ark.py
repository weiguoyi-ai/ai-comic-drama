# -*- coding: utf-8 -*-
"""一键自检：验证 config.json 里的火山方舟 Key 是否可用。

用法： python check_ark.py
"""

import os
import sys

import providers

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    cfg = providers.load_config()
    llm, img = cfg["llm"], cfg["image"]

    print("=" * 56)
    print("配置检查")
    print("=" * 56)
    print("分镜模型 : %s  [%s]" % (llm.get("model"), "已配置Key" if providers._has_key(llm) else "未配置"))
    print("生图模型 : %s  [%s]" % (img.get("model"), "已配置Key" if providers._has_key(img) else "未配置"))

    if not providers._has_key(img):
        print("\n⚠️ 还没有填写 API Key。")
        print("请在 config.json 的 llm.api_key / image.api_key 填入火山方舟 Key，")
        print("或设置环境变量 ARK_API_KEY 后重试。")
        return 1

    out_dir = os.path.join(ROOT, "projects", "_selftest")
    os.makedirs(out_dir, exist_ok=True)

    print("\n[1/2] 测试分镜模型（doubao chat）…")
    try:
        r = providers.gen_storyboard("少女在雪山遇见白狐。", "仙侠玄幻·唯美写实", 2)
        print("      ✅ 成功，返回 %d 个分镜；第一幕：%s"
              % (len(r["scenes"]), r["scenes"][0].get("title")))
    except Exception as e:
        print("      ❌ 失败：%s" % str(e)[:400])
        print("      常见原因：模型未在「开通管理」里开通，或 Key 无权限。")

    print("\n[2/2] 测试生图模型（Seedream，9:16）…")
    try:
        name, is_mock = providers.gen_image(
            "冰蓝色调，雪山之巅，白衣少女回眸", out_dir, "仙侠玄幻·唯美写实", "9:16")
        if is_mock:
            print("      ⚠️ 仍处于占位图模式，请检查 Key 是否填入")
        else:
            print("      ✅ 成功，图片已保存：%s" % os.path.join(out_dir, name))
    except Exception as e:
        print("      ❌ 失败：%s" % str(e)[:400])

    print("\n自检结束。若都成功，刷新网页即可生成真实 AI 漫剧。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
