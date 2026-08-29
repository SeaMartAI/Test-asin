#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Asin - 亚马逊 ASIN Listing 健康度检查 Web 应用
部署后可通过短链接访问，输入亚马逊链接或 ASIN 即可检查。

本地运行：
    pip install flask requests beautifulsoup4
    python test_asin_app.py
    然后访问 http://127.0.0.1:5000

部署示例（Render / Railway / 腾讯云轻量）：
    - 把本文件上传为 Web Service
    - 启动命令：python test_asin_app.py
    - 端口：5000（或按平台要求设置 PORT 环境变量）
"""

import os
import re
import requests
from flask import Flask, request, jsonify, render_template_string
from bs4 import BeautifulSoup

app = Flask(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def extract_asin_and_site(text: str) -> tuple[str | None, str]:
    text = text.strip()
    lower = text.lower()

    if "amazon" in lower:
        m = re.search(r"(?:dp/|gp/product/|asin=)([A-Z0-9]{10})", text, re.I)
        if m:
            asin = m.group(1).upper()
            domain_m = re.search(r"amazon\.([a-z]{2,3}(?:\.[a-z]{2})?)(?:\.|/)", lower)
            site = domain_m.group(1) if domain_m else "com"
            return asin, site
        return None, "com"

    if re.fullmatch(r"[A-Z0-9]{10}", text.upper()):
        return text.upper(), "com"

    return None, "com"


def fetch_page(asin: str, site: str = "com") -> tuple[str | None, int | str]:
    url = f"https://www.amazon.{site}/dp/{asin}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        return r.text, r.status_code
    except Exception as e:
        return None, str(e)


def parse_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "title": "", "titleLength": 0, "brand": "",
        "imageCount": 0, "mainImage": None,
        "bulletCount": 0, "hasDescription": False, "hasAplus": False,
        "category": "", "rating": None, "reviewCount": None, "price": ""
    }

    title_tag = soup.find("span", id="productTitle") or soup.find("h1", id="title") or soup.select_one(".product-title")
    if title_tag:
        data["title"] = title_tag.get_text(strip=True)
        data["titleLength"] = len(data["title"])

    brand = ""
    byline = soup.find("a", id="bylineInfo")
    if byline:
        brand_text = byline.get_text(strip=True)
        m = re.search(r"Visit the\s+(.+?)\s+Store", brand_text, flags=re.I)
        if m:
            brand = m.group(1).strip()
        else:
            brand = re.sub(r"^(Visit the |Brand:)", "", brand_text, flags=re.I).strip()
            brand = re.sub(r"\s+Store$", "", brand, flags=re.I).strip()
    if not brand:
        bb = soup.select_one(".tabular-buybox-text[tabular-attribute-name='Brand']")
        if bb:
            brand = bb.get_text(strip=True)
    if not brand:
        words = data["title"].split()
        if words:
            brand = words[0]
    data["brand"] = brand

    thumbs = soup.select("#altImages .itemThumbnail, #altImages .imageThumbnail, #altImages img, .a-button-thumbnail, #imageBlock_thumbs .a-button")
    data["imageCount"] = len(thumbs) if thumbs else 1

    main_img = soup.select_one("#landingImage, #imgBlkFront")
    if main_img:
        data["mainImage"] = main_img.get("data-old-hires") or main_img.get("src")

    bullets = []
    ul = soup.select_one("#feature-bullets ul, #feature-bullets .a-unordered-list, .a-unordered-list.a-nostyle.a-vertical")
    if ul:
        bullets = [
            li.get_text(" ", strip=True)
            for li in ul.find_all("li")
            if li.get_text(strip=True)
        ]
        bullets = [b for b in bullets if not b.lower().startswith(("make sure", "please be", "check the", "legal disclaimer"))]
    data["bulletCount"] = len(bullets)

    data["hasAplus"] = bool(soup.select_one("#aplus, #aplus_feature_div"))
    data["hasDescription"] = data["hasAplus"] or bool(soup.select_one("#productDescription, #productDescription_feature_div"))

    bc_links = soup.select("#wayfinding-breadcrumbs_container li a, #wayfinding-breadcrumbs_feature_div li a, .a-breadcrumb li a")
    data["category"] = " > ".join([a.get_text(strip=True) for a in bc_links if a.get_text(strip=True)])

    rating_el = soup.select_one("[data-hook='average-star-rating'] .a-icon-alt, .a-icon-alt")
    if rating_el:
        m = re.search(r"([\d.]+) out of", rating_el.get_text())
        if m:
            data["rating"] = float(m.group(1))

    review_el = soup.select_one("[data-hook='total-review-count'], #acrCustomerReviewText")
    if review_el:
        m = re.search(r"([\d,]+)", review_el.get_text())
        if m:
            data["reviewCount"] = int(m.group(1).replace(",", ""))

    price_el = soup.select_one(".a-price .a-offscreen, #priceblock_dealprice, #priceblock_ourprice, .a-price-range")
    if price_el:
        data["price"] = price_el.get_text(strip=True)

    return data


def evaluate(data: dict) -> tuple[float, list, list]:
    score = 0.0
    details = []
    suggestions = []

    if data.get("category"):
        score += 10
        details.append({"item": "分类叶节点", "full": 10, "note": f"已识别：{data['category']}", "ok": True})
    else:
        details.append({"item": "分类叶节点", "full": 10, "note": "未识别（需后台确认）", "ok": False})
        suggestions.append("确认 ASIN 已正确填写分类叶节点（Browse Node）")

    details.append({"item": "搜索关键词", "full": 5, "note": "公开页不可见，需后台补充", "ok": False})
    suggestions.append("在后台 Search Terms 中补充有效搜索关键词")

    if data.get("brand"):
        score += 5
        details.append({"item": "品牌名称", "full": 5, "note": f"已识别：{data['brand']}", "ok": True})
    else:
        details.append({"item": "品牌名称", "full": 5, "note": "未识别", "ok": False})
        suggestions.append("完善品牌名称字段，确保与标题一致")

    if data.get("hasAplus"):
        score += 12.5
        details.append({"item": "A+ 页面", "full": 12.5, "note": "已识别 A+ 内容模块", "ok": True})
    else:
        details.append({"item": "A+ 页面", "full": 12.5, "note": "未识别", "ok": False})
        suggestions.append("建议添加 A+ 页面，可提升转化并增加 12.5 分")

    if data.get("hasDescription"):
        score += 5
        details.append({"item": "商品描述", "full": 5, "note": "已识别", "ok": True})
    else:
        details.append({"item": "商品描述", "full": 5, "note": "未识别", "ok": False})
        suggestions.append("补充 Product Description 内容")

    bc = data.get("bulletCount", 0)
    if bc >= 1:
        score += 5
        details.append({"item": "≥1 条要点", "full": 5, "note": f"识别到 {bc} 条", "ok": True})
    else:
        details.append({"item": "≥1 条要点", "full": 5, "note": "未识别", "ok": False})
        suggestions.append("至少添加 1 条商品要点（Bullet Point）")

    if bc >= 3:
        score += 2.5
        details.append({"item": "≥3 条要点", "full": 2.5, "note": f"识别到 {bc} 条", "ok": True})
    else:
        details.append({"item": "≥3 条要点", "full": 2.5, "note": f"仅识别到 {bc} 条", "ok": False})
        suggestions.append(f"建议写满 5 条要点，目前仅 {bc} 条")

    details.append({"item": "关键属性全部填写", "full": 25, "note": "公开页不可见，需后台 LQD 确认", "ok": False})
    suggestions.append("在 Listing Quality Dashboard 中补齐关键属性（Recommend/Required）")

    tl = data.get("titleLength", 0)
    if 10 <= tl <= 200:
        score += 5
        details.append({"item": "标题长度 10-200 字符", "full": 5, "note": f"当前 {tl} 字符", "ok": True})
    else:
        details.append({"item": "标题长度 10-200 字符", "full": 5, "note": f"当前 {tl} 字符，需调整", "ok": False})
        suggestions.append(f"标题长度调整为 10-200 字符，当前 {tl} 字符")

    title = data.get("title", "")
    brand = data.get("brand", "")
    if brand and title.lower().startswith(brand.lower()):
        score += 5
        details.append({"item": "标题以品牌名开头", "full": 5, "note": "是", "ok": True})
    else:
        details.append({"item": "标题以品牌名开头", "full": 5, "note": f"标题未以品牌名 '{brand}' 开头", "ok": False})
        if brand:
            suggestions.append(f"建议标题以品牌名 '{brand}' 开头")
        else:
            suggestions.append("建议标题以品牌名开头，并完善品牌字段")

    ic = data.get("imageCount", 0)
    if ic >= 4:
        score += 5
        details.append({"item": "≥4 张图片", "full": 5, "note": f"识别到约 {ic} 张", "ok": True})
    else:
        details.append({"item": "≥4 张图片", "full": 5, "note": f"仅识别到约 {ic} 张", "ok": False})
        suggestions.append(f"建议上传至少 4 张图片，当前识别约 {ic} 张")

    if data.get("mainImage"):
        score += 5
        details.append({"item": "主图信息完善", "full": 5, "note": "主图已识别", "ok": True})
        score += 5
        details.append({"item": "主图可缩放（≥1600px）", "full": 5, "note": "主图存在，像素需后台确认", "ok": True})
    else:
        details.append({"item": "主图信息完善", "full": 5, "note": "未识别主图", "ok": False})
        details.append({"item": "主图可缩放（≥1600px）", "full": 5, "note": "未识别主图", "ok": False})
        suggestions.append("确保主图为纯白背景（RGB 255,255,255），最长边≥1600px，占比≥85%")

    return score, details, suggestions


HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Test Asin · 亚马逊 ASIN 健康度检查</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
      background: #f5f6f7;
      margin: 0;
      padding: 16px;
      color: #1d1d1f;
    }
    .container {
      max-width: 720px;
      margin: 0 auto;
      background: #fff;
      border-radius: 12px;
      padding: 24px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    h1 { font-size: 22px; margin: 0 0 8px; }
    .sub { color: #666; font-size: 14px; margin-bottom: 20px; }
    .input-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    input[type="text"] {
      flex: 1;
      min-width: 220px;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      padding: 12px;
      font-size: 15px;
    }
    select {
      border: 1px solid #d1d5db;
      border-radius: 8px;
      padding: 12px;
      font-size: 15px;
      background: #fff;
    }
    .btn {
      margin-top: 12px;
      background: #ff9900;
      color: #fff;
      border: none;
      padding: 12px 24px;
      border-radius: 8px;
      font-size: 16px;
      cursor: pointer;
      width: 100%;
    }
    .btn:hover { background: #e68a00; }
    .btn:disabled { background: #ccc; cursor: not-allowed; }
    .result { margin-top: 24px; }
    .score-box {
      display: flex;
      align-items: baseline;
      gap: 12px;
      margin: 16px 0;
      padding: 16px;
      background: #f9fafb;
      border-radius: 8px;
    }
    .score-num { font-size: 42px; font-weight: 700; color: #ff9900; }
    .score-level { font-size: 18px; font-weight: 600; }
    .section-title { font-size: 16px; font-weight: 600; margin: 20px 0 10px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid #eee; }
    th { background: #f9fafb; font-weight: 600; }
    .ok { color: #16a34a; }
    .no { color: #dc2626; }
    .tips {
      background: #fff7ed;
      border-left: 4px solid #ff9900;
      padding: 12px;
      border-radius: 4px;
      font-size: 14px;
      color: #7c2d12;
    }
    ol.suggestions { padding-left: 20px; }
    ol.suggestions li { margin-bottom: 8px; font-size: 14px; }
    .meta p { margin: 4px 0; font-size: 14px; }
    .hidden { display: none; }
    .error { color: #dc2626; background: #fef2f2; padding: 12px; border-radius: 8px; font-size: 14px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>🩺 Test Asin · 亚马逊 ASIN 健康度检查</h1>
    <div class="sub">输入亚马逊产品链接或 ASIN，后端自动抓取页面并输出 Listing 完整度得分与修改建议。</div>

    <div class="input-row">
      <input type="text" id="urlInput" placeholder="https://www.amazon.com/dp/XXXXX 或 10位 ASIN">
      <select id="siteSelect">
        <option value="auto">自动识别站点</option>
        <option value="com">美国 amazon.com</option>
        <option value="co.uk">英国 amazon.co.uk</option>
        <option value="de">德国 amazon.de</option>
        <option value="fr">法国 amazon.fr</option>
        <option value="jp">日本 amazon.co.jp</option>
        <option value="ca">加拿大 amazon.ca</option>
      </select>
    </div>
    <button class="btn" id="checkBtn" onclick="check()">开始检查</button>

    <div id="result" class="result hidden"></div>
  </div>

  <script>
    async function check() {
      const url = document.getElementById('urlInput').value.trim();
      const site = document.getElementById('siteSelect').value;
      const btn = document.getElementById('checkBtn');
      const result = document.getElementById('result');

      if (!url) return alert('请输入亚马逊链接或 ASIN');

      btn.disabled = true;
      btn.textContent = '检查中...';
      result.classList.add('hidden');

      try {
        const res = await fetch('/check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, site })
        });
        const data = await res.json();

        if (data.error) {
          result.innerHTML = `<div class="error">${data.error}</div>`;
          result.classList.remove('hidden');
          return;
        }

        render(data);
      } catch (e) {
        result.innerHTML = `<div class="error">请求失败：${e.message}</div>`;
        result.classList.remove('hidden');
      } finally {
        btn.disabled = false;
        btn.textContent = '开始检查';
      }
    }

    function render(data) {
      const score = data.score;
      let level = '', color = '';
      if (score >= 80) { level = 'A · 健康'; color = '#16a34a'; }
      else if (score >= 70) { level = 'B · 良好'; color = '#65a30d'; }
      else if (score >= 60) { level = 'C · 一般'; color = '#ca8a04'; }
      else if (score >= 50) { level = 'D · 较差'; color = '#ea580c'; }
      else { level = 'E · 严重'; color = '#dc2626'; }

      const rows = data.details.map(d => `
        <tr>
          <td>${d.item}</td>
          <td>${d.full}</td>
          <td class="${d.ok ? 'ok' : 'no'}">${d.ok ? '✅' : '❌'}</td>
          <td>${d.note}</td>
        </tr>
      `).join('');

      const suggestions = data.suggestions.length
        ? `<ol class="suggestions">${data.suggestions.map(s => `<li>${s}</li>`).join('')}</ol>`
        : '<p>暂无明确建议，Listing 完整度优秀。</p>';

      const meta = data.data;
      const result = document.getElementById('result');
      result.classList.remove('hidden');
      result.innerHTML = `
        <div class="score-box">
          <div class="score-num" style="color:${color}">${score.toFixed(1)}</div>
          <div>
            <div class="score-level" style="color:${color}">${level}</div>
            <div style="font-size:13px;color:#666">满分 100 · 合格线 80</div>
          </div>
        </div>

        <div class="section-title">基础信息</div>
        <div class="meta">
          <p><b>ASIN：</b>${data.asin}</p>
          <p><b>站点：</b>amazon.${data.site}</p>
          <p><b>标题：</b>${meta.title ? meta.title.slice(0, 80) + (meta.title.length > 80 ? '...' : '') : '未识别'}</p>
          <p><b>品牌：</b>${meta.brand || '未识别'}</p>
          <p><b>图片数：</b>约 ${meta.imageCount} 张</p>
          <p><b>要点数：</b>${meta.bulletCount} 条</p>
          <p><b>描述/A+：</b>${meta.hasDescription ? '是' : '否'}</p>
          <p><b>分类路径：</b>${meta.category || '未识别'}</p>
          ${meta.rating ? `<p><b>Rating：</b>${meta.rating}（${meta.reviewCount || '?'} 评）</p>` : ''}
          ${meta.price ? `<p><b>价格：</b>${meta.price}</p>` : ''}
        </div>

        <div class="section-title">Listing 完整度明细</div>
        <table>
          <tr><th>检查项</th><th>满分</th><th>状态</th><th>说明</th></tr>
          ${rows}
        </table>

        <div class="section-title">优先修改建议</div>
        ${suggestions}

        <div class="tips" style="margin-top:16px">
          <b>说明：</b>本工具仅基于公开产品页可抓取字段打分。搜索关键词、关键属性、库存、合规等需卖家后台数据补充。
        </div>
      `;
    }
  </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_PAGE)


@app.route('/check', methods=['POST'])
def check():
    payload = request.get_json() or {}
    url_or_asin = payload.get('url', '').strip()
    selected_site = payload.get('site', 'auto')

    if not url_or_asin:
        return jsonify({"error": "请输入亚马逊链接或 ASIN"})

    asin, detected_site = extract_asin_and_site(url_or_asin)
    if not asin:
        return jsonify({"error": "无法识别 ASIN，请输入完整链接或 10 位 ASIN 编码"})

    site = detected_site if selected_site == 'auto' else selected_site

    html, status = fetch_page(asin, site)
    if html is None:
        return jsonify({"error": f"无法访问亚马逊页面：{status}。可能触发反爬或验证码，请稍后重试，或使用本地 HTML 模式。"})

    if "api-services-support@amazon.com" in html or "captcha" in html.lower() or status != 200:
        return jsonify({"error": "亚马逊返回了反爬/验证码页面。建议用浏览器打开页面后保存 HTML，再用本地脚本解析。"})

    data = parse_page(html)
    score, details, suggestions = evaluate(data)

    return jsonify({
        "asin": asin,
        "site": site,
        "score": score,
        "data": data,
        "details": details,
        "suggestions": suggestions
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
