#!/usr/bin/env python3
"""把 web/ 的開發版打包成「雙擊就能用」的單檔 HTML。

為什麼需要這支:瀏覽器在 file://(直接雙擊 HTML)下會擋住 fetch() 本機檔,
所以開發版那種 fetch('../data/bank.json') 會失敗、卡在「題庫尚未載入」。
單檔版把題庫 / 關聯 / 樣式 / 程式全部內嵌進一個 HTML,不需要伺服器、不需要
任何前置步驟 —— 使用者只要打開它就能練習。

作法(確定性、純標準庫):
  1. 讀 data/bank.json(原樣內嵌)與 data/relations.json(精簡成純 qid 清單)。
  2. 讀 web/index.html,把 <link app.css> 換成 <style>、把每個 <script src> 換成
     內嵌 <script>,並在最前面注入 window.__BANK__ / window.__REL__。
  3. 一場考試輸出一份獨立單檔(開卷有益_學測.html / 開卷有益_會考.html),
     並產生 repo 根的 index.html(GitHub Pages 首頁 + 離線下載目錄)與 .nojekyll。

loader.js 會優先採用 window.__BANK__/__REL__,因此同一套程式碼:單檔版走內嵌、
開發版(http.server)走 fetch,互不衝突。

用法:
    python3 scripts/build_app.py
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA = ROOT / "data"
OUT = ROOT / "開卷有益_升學.html"

# 內嵌時各類關聯保留的上限(夠用就好,壓低單檔體積)
REL_KEEP = {"similar": 4, "opposite": 3, "related": 3}

# 內嵌 JS 檔的順序必須與 index.html 一致(載入順序有意義)
JS_ORDER = ["srs.js", "stats.js", "charts.js", "loader.js", "exams.js", "run.js", "coach.js",
           "essays.js", "explain.js", "diagnostic.js", "modes.js", "help.js", "progress.js", "naming.js", "history.js", "blueprint.js", "app.js"]


def slim_relations(rel: dict) -> dict:
    """把 {meta, relations:{qid:{similar:[{qid,score}],...}}} 精簡成
    {qid:{similar:[qid,...], opposite:[qid,...], related:[qid,...]}}。
    app 端兩種形狀都吃(取 x.qid 或 x 本身),所以丟掉分數可大幅縮小體積。"""
    src = rel.get("relations", rel)
    out: dict[str, dict] = {}
    for qid, entry in src.items():
        slim: dict[str, list] = {}
        for kind, cap in REL_KEEP.items():
            items = entry.get(kind) or []
            ids = []
            for it in items[:cap]:
                qid2 = it.get("qid") if isinstance(it, dict) else it
                if qid2:
                    ids.append(qid2)
            if ids:
                slim[kind] = ids
        if slim:
            out[qid] = slim
    return out


def js_safe_json(obj) -> str:
    """序列化成可安全內嵌進 <script> 的 JSON 字串。
    關鍵:把任何 '</' 變成 '<\\/',避免資料裡萬一出現 </script> 提早關閉標籤。"""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s.replace("</", "<\\/")


def figures_block(bank: dict) -> str:
    """收集 bank 題目引用的 figure 檔名,讀 data/figures/ 下 PNG → base64 data URI,
    組成 window.__FIGS__={檔名:dataURI}。

    ⚠️ base64 字串只在本函式內部與輸出 HTML 字串裡流動,**絕不 print**(避免把編碼
    字串塞進 stdout/context window 觸發 AUP 過濾器)。本函式只印張數/大小/缺檔。"""
    figdir = DATA / "figures"
    names: list[str] = []
    seen: set[str] = set()
    for q in bank.get("questions", []):
        fn = q.get("figure")
        if fn and fn not in seen:
            seen.add(fn)
            names.append(fn)
    figs: dict[str, str] = {}
    missing: list[str] = []
    total = 0
    for fn in names:
        p = figdir / fn
        if not p.exists():
            missing.append(fn)
            continue
        raw = p.read_bytes()
        total += len(raw)
        figs[fn] = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    print(f"圖片內嵌:{len(figs)}/{len(names)} 張,原始合計 {total / 1024 / 1024:.1f} MB"
          + (f";缺檔 {len(missing)}" if missing else ""))
    if missing:
        print("  缺檔(figure 欄指到但 data/figures/ 沒有):"
              + ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else ""))
    return "window.__FIGS__=" + js_safe_json(figs) + ";\n"


def build(exam: str | None = None, out: Path = OUT) -> Path:
    bank = json.loads((DATA / "bank.json").read_text(encoding="utf-8"))
    if not isinstance(bank, dict) or not bank.get("questions"):
        raise SystemExit("bank.json 形狀不對:缺 questions。請先跑 build_bank.py。")

    rel_path = DATA / "relations.json"
    rel_slim = {}
    if rel_path.exists():
        rel_slim = slim_relations(json.loads(rel_path.read_text(encoding="utf-8")))

    essays_path = DATA / "essays.json"
    essays = {}
    if essays_path.exists():
        essays = json.loads(essays_path.read_text(encoding="utf-8"))

    # 本題解釋(AI 整理):{qid:{t,c}};可能尚未生成(隔夜批次跑),缺檔時內嵌空物件
    expl_path = DATA / "explanations.json"
    expl = {}
    if expl_path.exists():
        expl = json.loads(expl_path.read_text(encoding="utf-8"))
        expl = expl.get("explanations", expl)

    # 申論三種範本(AI 示例):{qid:[範本1,範本2,範本3]};缺檔時內嵌空物件
    esamp_path = DATA / "essay_samples.json"
    esamp = {}
    if esamp_path.exists():
        esamp = json.loads(esamp_path.read_text(encoding="utf-8"))
        esamp = esamp.get("samples", esamp)

    # 一科一檔(per-exam):指定 exam 時只留該考試的題/詳解/圖,輸出較小單檔
    # (仍保留「考試內各科交錯」—— 只是不含別的考試,故檔案小)
    if exam:
        qs = [q for q in bank["questions"] if q.get("exam") == exam]
        if not qs:
            raise SystemExit(f"bank 內無 exam={exam} 的題")
        bank = {**bank, "questions": qs}
        keep = {q["qid"] for q in qs}
        expl = {k: v for k, v in expl.items() if k in keep}
        rel_slim = {k: v for k, v in rel_slim.items() if k in keep}
        if isinstance(essays, dict):
            essays = {k: v for k, v in essays.items() if k in keep}
        if isinstance(esamp, dict):
            esamp = {k: v for k, v in esamp.items() if k in keep}

    html = (WEB / "index.html").read_text(encoding="utf-8")

    # 0) 剝除 PWA 標記區塊(manifest link / SW 註冊):那是網站版專用,file:// 單檔不適用
    html = re.sub(r"<!--PWA-->.*?<!--/PWA-->", "", html, flags=re.S)

    # 1) <link app.css> → 內嵌 <style>
    css = (WEB / "app.css").read_text(encoding="utf-8")
    html = re.sub(
        r'<link\s+rel="stylesheet"\s+href="app\.css"\s*/?>',
        "<style>\n" + css + "\n</style>",
        html,
        count=1,
    )

    # 2) 注入資料 + 內嵌各 JS(取代對應的 <script src> 標籤)
    figs_js = figures_block(bank)
    data_block = (
        "<script>\n"
        "window.__BANK__=" + js_safe_json(bank) + ";\n"
        + figs_js +
        "window.__REL__=" + js_safe_json(rel_slim) + ";\n"
        "window.__ESSAYS__=" + js_safe_json(essays) + ";\n"
        "window.__EXPL__=" + js_safe_json(expl) + ";\n"
        "window.__ESAMPLES__=" + js_safe_json(esamp) + ";\n"
        "</script>"
    )
    # 把第一個 <script src="srs.js"> 之前插入資料區塊
    first_tag = '<script src="srs.js" defer></script>'
    if first_tag not in html:
        raise SystemExit("index.html 找不到預期的 <script src=\"srs.js\">,結構可能已改。")
    html = html.replace(first_tag, data_block + "\n" + first_tag, 1)

    for name in JS_ORDER:
        code = (WEB / name).read_text(encoding="utf-8")
        tag = f'<script src="{name}" defer></script>'
        if tag not in html:
            raise SystemExit(f"index.html 找不到 {tag},無法內嵌 {name}。")
        # 內嵌 JS 同樣防 </script> 提早關閉(本專案 JS 不含此字串,仍保險處理)
        safe = code.replace("</script>", "<\\/script>")
        html = html.replace(tag, "<script>\n" + safe + "\n</script>", 1)

    # 標記為單檔版,避免使用者誤把它當開發版找不到 app.css
    html = html.replace(
        "<!-- 開發版:外連 app.css(用 python3 -m http.server 服務)。\n"
        "     單檔版由 scripts/build_app.py 內嵌成一個雙擊即用的 HTML。 -->",
        "<!-- 單檔版:題庫/關聯/樣式/程式皆已內嵌,雙擊即可用,無需伺服器。 -->",
    )

    out.write_text(html, encoding="utf-8")
    return out


# 一科一檔輸出清單:(exam, 輸出檔, 首頁卡片說明)。
# 刻意不再輸出「合併版」單檔:每場考試各自一份獨立單檔 —— fork 友善、體積有上限、
# 避開 GitHub 50MB 檔案警示;想全包的人下載多份即可。決策見 docs/DECISIONS.md。
EXAM_BUILDS = [
    ("學測", ROOT / "開卷有益_學測.html", "國綜・英文・社會，含原卷圖表"),
    ("會考", ROOT / "開卷有益_會考.html", "國文・英語・社會，含原卷圖表"),
]


def build_index(entries: list) -> Path:
    """產生網站首頁 / 離線目錄(repo 根 index.html)。
    GitHub Pages 直接拿它當網站首頁;本機 clone 也能雙擊它當下載目錄。
      ・「線上練習」按鈕 → web/index.html(純線上網站版,隨開隨用;不再做 PWA／離線快取,離線交給未來 app)。
      ・各考試卡片 → 下載對應的離線單檔(挑要考的那一份就好,不必扛全部)。
    entries: list of (label, filename, mb, note)。純靜態 HTML,無相依。"""
    cards = "\n".join(
        '<a class="card" href="{fn}" download><div class="t">{label}</div>'
        '<div class="n">{note}</div><div class="s">⬇ 下載離線單檔・{mb:.0f} MB</div></a>'.format(
            fn=fn, label=label, note=note, mb=mb)
        for (label, fn, mb, note) in entries
    )
    page = (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>開卷有益 Open-Book-Is-Good</title><style>'
        ':root{--paper:#f7f3ea;--ink:#2b2a26;--soft:#6b665c;--rule:#d8d0c0;--accent:#3a6ea5}'
        'body{margin:0 auto;max-width:680px;background:var(--paper);color:var(--ink);'
        'font:16px/1.7 -apple-system,"PingFang TC","Noto Sans TC",sans-serif;padding:2.4rem 1.2rem}'
        'h1{font-size:1.5rem;margin:.2rem 0}p.sub{color:var(--soft);margin:.3rem 0 1.4rem}'
        'h2{font-size:1rem;color:var(--soft);font-weight:600;margin:1.8rem 0 .4rem;'
        'border-bottom:1px solid var(--rule);padding-bottom:.3rem}'
        '.go{display:block;text-decoration:none;background:var(--accent);color:#fff;'
        'border-radius:12px;padding:1rem 1.2rem;margin:.6rem 0}'
        '.go .t{font-size:1.2rem;font-weight:700}.go .n{opacity:.92;font-size:.92rem;margin-top:.2rem}'
        '.go:hover{filter:brightness(1.06)}'
        '.card{display:block;text-decoration:none;color:inherit;border:1px solid var(--rule);'
        'border-radius:12px;padding:.9rem 1.2rem;margin:.6rem 0;background:#fff;'
        'transition:border-color .15s,transform .15s}'
        '.card:hover{border-color:var(--accent);transform:translateY(-1px)}'
        '.card .t{font-size:1.1rem;font-weight:600}.card .n{color:var(--soft);margin:.2rem 0}'
        '.card .s{color:var(--accent);font-size:.9rem}'
        'footer{color:var(--soft);font-size:.85rem;margin-top:2rem;border-top:1px solid var(--rule);padding-top:1rem}'
        '</style></head><body>'
        '<h1>開卷有益 Open-Book-Is-Good</h1>'
        '<p class="sub">學測與會考，歷年真題完全離線練習，進度只屬於你、不追蹤。</p>'
        '<a class="go" href="web/index.html"><div class="t">▶ 線上練習（隨開隨用）</div>'
        '<div class="n">免下載、可加到主畫面當 App、仍可離線</div></a>'
        '<h2>或下載離線單檔（雙擊即用，適合完全離線／備份）</h2>'
        + cards +
        '<footer>歷年真題在本機練習，進度只屬於你。題目依著作權法 §9 自由使用；'
        'AI 整理之詳解請對照現行資料查證。開放原始碼（MIT），歡迎 fork、貢獻新考科。</footer>'
        '</body></html>'
    )
    p = ROOT / "index.html"
    p.write_text(page, encoding="utf-8")
    return p


def main() -> None:
    entries = []
    for exam, out, note in EXAM_BUILDS:
        build(exam, out)
        mb = out.stat().st_size / (1024 * 1024)
        entries.append((exam, out.name, mb, note))
        print(f"{exam}: {out.name}  {mb:.1f} MB")
    idx = build_index(entries)
    # GitHub Pages 不跑 Jekyll(才不會吃掉底線開頭的檔/資料夾);全站靜態原樣服務
    (ROOT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"首頁/目錄:{idx.name}(GitHub Pages 首頁 + 離線下載目錄)")


if __name__ == "__main__":
    main()
