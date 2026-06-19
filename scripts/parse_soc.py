#!/usr/bin/env python3
"""學測社會 markitdown(.md) → 結構化題庫(題組感知、跨領域、多年度),合併進 data/bank.json。

社會卷結構(逐字忠實擷取原文,絕不改寫/摘要/翻譯):
  第壹部分、選擇題      第 1 題至第 N 題單選 (A)-(D);N 因年而異。前段含獨立單選,
                       後段穿插題組(每組共用 ◎ 材料 + 數小題)。
  第貳部分、混合題或非選 全為題組(共用 ◎ 材料):單選=單選、多選=多選、
                       填空/簡答/作圖=非選(答案標「／」)。

社會卷幾乎全為題組,且大量「依據圖N/表N/附圖/照片」作答的圖表題。文字來源用
markitdown 的 markdown(散文閱讀順序大致正確),但 markitdown 會:
  1) 把題幹/選項/材料嵌進 markdown 表格(| ... | ...),需攤平還原純文字;
  2) 把題組標頭「a-b 為題組」切成兩行,且順序可能顛倒(「為題組」在前、「a-b」在後)。
故 flatten_md 先攤平表格、去頁眉頁腳;題組標頭以三形態容錯比對。

needs_figure(社會圖表多,寧可多標):題幹或 passage 出現「圖/表/地圖/附圖/照片/
下圖/下表/示意圖/統計圖…」,或選項數 < 4(圖被吃掉)、或選項全空 → true。

答案用 pymupdf find_tables 解析答案 PDF(橫排 4 對「題號/答案」;單選單字母 A-E、
多選多字母、非選標「／」)。

前置(每年):
  markitdown data/raw/{年}_社會_試題.pdf -o data/raw/{年}_社會_試題.md
用法:uv run --with pymupdf python3 scripts/parse_soc.py
著作權:大考中心歷年試題,著作權法 §9 不受著作權保護。
"""
import fitz, re, json, os, glob

RAW = "data/raw"
EXAM = "學測"
SUBJECT = "社會"
BANK = "data/bank.json"

# 頁眉頁腳/作答注意事項/裝飾行:攤平後逐行過濾,以免污染題幹與 passage。
DROP = re.compile(
    r"^\s*("
    r"第\s*\d+\s*頁|共\s*\d+\s*頁|-\s*\d+\s*-|\d+\s*年學測|"
    r"社\s*會\s*考\s*科|財團法人.*|\d+學年度.*|請記得在答題卷.*|"
    r"請於考試.*|背\s*面\s*尚\s*有\s*試\s*題|"
    r"[˙․•·]\s*.*|考試時間.*|作答方式.*|作答注意事項.*|"
    r"選擇題計分方式.*|更正時.*|應以橡皮擦.*|切勿使用修正.*|"
    r"考生須依.*|答題卷每人.*|非選擇題用.*"
    r")\s*$"
)

# 章節邊界:第壹部分單選說明(標出單選題號上限)、第貳部分混合題。
PART1_HDR = re.compile(r"說\s*明\s*[:：︰]\s*第\s*1\s*題\s*至\s*第\s*(\d+)\s*題\s*為\s*單\s*選\s*題")
PART2_HDR = re.compile(r"第\s*貳\s*部\s*分")

# 題組標頭三形態:同行「a-b 為題組」、顛倒兩行「為題組\na-b」、正常兩行「a-b\n為題組」。
GROUP_SAME = re.compile(r"(?m)^\s*(\d+)\s*[-－–~至]\s*(\d+)\s*為\s*題\s*組")
GROUP_INV = re.compile(r"(?m)^\s*為\s*題\s*組\s*\n\s*(\d+)\s*[-－–~至]\s*(\d+)\s*$")
GROUP_NORM = re.compile(r"(?m)^\s*(\d+)\s*[-－–~至]\s*(\d+)\s*\n\s*為\s*題\s*組")

# needs_figure 觸發字:社會卷大量圖表/地圖/照片題。
FIG_KW = re.compile(r"圖|表|地\s*圖|附\s*圖|照\s*片|示\s*意|統\s*計\s*圖|曲\s*線|分\s*布")

# 領域推斷關鍵詞(可推則填,否則空)。歷史/地理/公民。
DOMAIN_HINTS = {
    "歷史": ("世紀", "朝", "王朝", "皇帝", "戰爭", "帝國", "革命", "史料", "年代",
             "古代", "近代", "殖民", "條約", "清", "明", "漢", "唐", "宋", "元",
             "羅馬", "希臘", "二次世界大戰", "冷戰", "日治", "總督府", "民國"),
    "地理": ("氣候", "地形", "經緯", "降水", "氣溫", "河川", "都市", "聚落", "等高線",
             "產業區位", "農業", "板塊", "洋流", "季風", "人口分布", "區域", "地圖",
             "緯度", "經度", "土壤", "植被", "流域", "等值線", "比例尺"),
    "公民": ("憲法", "選舉", "民主", "政府", "權利", "市場", "GDP", "經濟", "法律",
             "需求", "供給", "人權", "政黨", "立法", "司法", "公共", "福利", "社會",
             "契約", "所有權", "民法", "刑法", "彈性", "通膨", "失業", "財政"),
}


def flatten_md(md_path):
    """攤平 markdown:去分隔線、把表格 cell 抽出按序拼回(各 cell 換行分隔以保留
    題號/選項/題組標頭的行首錨點)、去頁眉頁腳裝飾;回傳乾淨多行純文字。"""
    body = open(md_path, encoding="utf-8").read()
    out = []
    for ln in body.split("\n"):
        s = ln.rstrip()
        # markdown 表格分隔線 |---|---| → 丟棄
        if re.match(r"^\s*\|?\s*[-:]+\s*(\|\s*[-:]+\s*)+\|?\s*$", s):
            continue
        if "|" in s and s.count("|") >= 2:
            cells = [c.strip() for c in s.strip().strip("|").split("|")]
            for c in cells:
                if c:
                    out.append(c)
        else:
            if s.strip():
                out.append(s)
    return [l for l in out if not DROP.match(l)]


# 中日韓統一表意文字範圍:用於移除中文字之間的殘留空格(markitdown 逐字拆 cell 所致)。
_CJK = r"　-〿㐀-䶿一-鿿＀-￯"


def join_clean(s):
    s = re.sub(r"[ \t]+", " ", re.sub(r"\n+", " ", s)).strip()
    # 反覆移除「中文字 空格 中文字」間的空格(處理連續逐字拆字,如「某 民 間 協 會」);
    # 只動兩側皆為 CJK 的空格,保留英數/標點與中文之間的空白,避免黏壞英文與數字。
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"(?<=[%s]) (?=[%s])" % (_CJK, _CJK), "", s)
    return s


def section_bounds(lines):
    """切出第壹部分(含單選題號上限)與第貳部分起點。回傳 (single_max, part2_idx)。"""
    single_max, part2_idx = None, len(lines)
    for i, ln in enumerate(lines):
        m = PART1_HDR.search(ln)
        if m and single_max is None:
            single_max = int(m.group(1))
        if PART2_HDR.search(ln) and part2_idx == len(lines):
            part2_idx = i
    return single_max, part2_idx


def parse_groups(text):
    """掃所有題組標頭(三形態),建 no -> (gid, passage)。passage = 標頭後到第一個
    子題題號前的材料文字(含 ◎ 引文,攤平後純文字)。"""
    heads = []  # (pos_end, a, b)  pos_end=標頭結束位置(passage 從此起算)
    for m in GROUP_SAME.finditer(text):
        heads.append((m.end(), int(m.group(1)), int(m.group(2))))
    for m in GROUP_INV.finditer(text):
        heads.append((m.end(), int(m.group(1)), int(m.group(2))))
    for m in GROUP_NORM.finditer(text):
        heads.append((m.end(), int(m.group(1)), int(m.group(2))))
    heads.sort()
    g = {}
    for k, (pe, a, b) in enumerate(heads):
        nxt = heads[k + 1][0] if k + 1 < len(heads) else len(text)
        rest = text[pe:nxt]
        # passage = 標頭後到第一個子題「a.」前
        qm = re.search(r"(?m)^\s*%d\s*[.．]\s*" % a, rest)
        passage = join_clean(rest[:qm.start()]) if qm else join_clean(rest)
        gid = "%s_社會_g%d_%d" % ("%d", a, b)  # year 之後補
        for n in range(a, b + 1):
            g[n] = (a, b, passage)
    return g


def parse_questions(text, single_max):
    """以行首題號(容許全形句點、點後無空白)切題;選項抓 (A)-(E)。回傳 list。
    title 行內題號(如表格殘留「| 49. 表 |」)經攤平後已成行首,亦能被切到。"""
    starts = list(re.finditer(r"(?m)^\s*(\d+)\s*[.．]\s*", text))
    # 去重複題號(攤平偶有重複殘影):保留每題號第一個出現,且題號需遞增合理。
    out, seen = [], set()
    valid = []
    for mm in starts:
        no = int(mm.group(1))
        if no in seen or no < 1 or no > 80:
            continue
        seen.add(no)
        valid.append(mm)
    for i, mm in enumerate(valid):
        no = int(mm.group(1))
        seg = text[mm.end(): valid[i + 1].start() if i + 1 < len(valid) else len(text)]
        # 切掉段內可能殘留的下一個題組標頭/章節說明,避免吃進別題
        cut = re.search(r"(為\s*題\s*組|第\s*貳\s*部\s*分|說\s*明\s*[:：︰])", seg)
        if cut:
            seg = seg[:cut.start()]
        stem, opts = split_stem_options(seg)
        out.append({"no": no, "stem": stem, "options": opts})
    return out


# 選項尾巴污染:markdown 破碎時,末選項(常是 D)會吃進下一題號文字或頁眉殘留。
# 截斷標記:「(空白)題號.」或行內出現的下一題起始。
_OPT_TAIL = re.compile(r"\s\d+\s*[.．]\s*\S")


def _trim_option(content):
    """清掉選項內容尾端被黏入的下一題號/頁眉殘留(僅截斷,不改寫保留的原文)。"""
    s = join_clean(content)
    m = _OPT_TAIL.search(s)
    if m:
        s = s[:m.start()].strip()
    return s


def split_stem_options(seg):
    """切出題幹 + 選項 dict{A..E}(選項可能跨行/同行並排,以字母為鍵,取第一次)。"""
    om = list(re.finditer(r"\(([A-E])\)", seg))
    if not om:
        return join_clean(seg), {}
    stem = seg[:om[0].start()]
    opts = {}
    for j, m in enumerate(om):
        L = m.group(1)
        content = seg[m.end(): om[j + 1].start() if j + 1 < len(om) else len(seg)]
        if L not in opts:
            opts[L] = _trim_option(content)
    return join_clean(stem), opts


def infer_domain(stem, passage):
    """依關鍵詞推斷領域(歷史/地理/公民);命中最多者勝,平手或皆 0 則空。"""
    blob = (stem or "") + " " + (passage or "")
    scores = {d: sum(blob.count(k) for k in kws) for d, kws in DOMAIN_HINTS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return ""
    # 平手不武斷判定
    if list(scores.values()).count(scores[best]) > 1:
        return ""
    return best


def needs_figure(stem, passage, options, answer):
    """寧可多標:題幹/passage 含圖表字、或選項數<4(圖被吃)、或選項全空(純圖選項)。
    非選題(answer 空且無選項)若 stem/passage 提到圖表也標 true(作圖/讀圖)。"""
    if FIG_KW.search((stem or "") + (passage or "")):
        return True
    if options:
        if len(options) < 4:
            return True
        if all(not v for v in options.values()):
            return True
    return False


def pdf_text_rows(pdf):
    """以 PDF 座標蒐集所有文字行(page, y, x, text),依閱讀順序(頁→上→左)排序。
    用於 markitdown 把複雜統計表線性化失敗時的題幹/選項 fallback(如 111 的破碎表)。"""
    doc = fitz.open(pdf)
    rows = []
    for pi, pg in enumerate(doc):
        for blk in pg.get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                txt = "".join(s["text"] for s in line["spans"]).strip()
                if txt:
                    rows.append((pi, round(line["bbox"][1], 1), round(line["bbox"][0], 1), txt))
    rows.sort(key=lambda t: (t[0], t[1], t[2]))
    return rows


def qfix_from_pdf(rows, no):
    """從 PDF 座標重抓單一題(no)的題幹 + 選項(A-E):找「no. …」起始列(內容夠長,
    排除統計值碎片),題號到第一個 (X) 為題幹,其後 (X) 列為選項;遇下一題號或集滿
    即停。回傳 (stem, options) 或 (None, None) 找不到。"""
    si = None
    for i, (pi, y, x, txt) in enumerate(rows):
        if re.match(r"^%d[.．]\s*\S" % no, txt) and len(txt) > 6:
            si = i
            break
    if si is None:
        return None, None
    stem_parts, opts, seen_opt = [], {}, False
    for pi, y, x, txt in rows[si:]:
        # 下一題號(且非當前題)→ 停
        m_next = re.match(r"^(\d+)[.．]\s*\S", txt)
        if m_next and int(m_next.group(1)) != no and seen_opt:
            break
        oms = list(re.finditer(r"\(([A-E])\)\s*([^()]*)", txt))
        if oms:
            seen_opt = True
            for om in oms:
                L = om.group(1)
                if L not in opts:
                    opts[L] = join_clean(om.group(2))
            if len(opts) >= 4:
                break
        elif not seen_opt:
            stem_parts.append(txt)
    stem = join_clean(" ".join(stem_parts))
    stem = re.sub(r"^%d[.．]\s*" % no, "", stem)  # 去題號前綴
    if len(opts) < 4:
        return None, None
    return stem, opts


def nonmc_stem_from_pdf(rows, no):
    """從 PDF 座標重抓非選題(no)題幹:「no. …」起始列起,拼到下一題號/頁眉/選項前。
    用於 markitdown 破碎表把非選題幹打成數字碎片時(如 111 的 48、56)。"""
    si = None
    for i, (pi, y, x, txt) in enumerate(rows):
        if re.match(r"^%d[.．]\s*\S" % no, txt) and len(txt) > 6:
            si = i
            break
    if si is None:
        return None
    parts = []
    for k, (pi, y, x, txt) in enumerate(rows[si:]):
        if k > 0 and re.match(r"^\d+[.．]\s*\S", txt):  # 下一題號
            break
        if DROP.match(txt) or re.match(r"^-\s*\d+\s*-$", txt):  # 頁眉頁腳
            break
        parts.append(txt)
    stem = join_clean(" ".join(parts))
    return re.sub(r"^%d[.．]\s*" % no, "", stem) or None


def parse_answers(pdf):
    """橫排 4 對(題號/答案)表;單選 A-E、多選多字母、非選標「／」。find_tables 解析。"""
    ans = {}
    doc = fitz.open(pdf)
    for pg in doc:
        for tb in pg.find_tables().tables:
            for row in tb.extract():
                cells = [c.strip() if c else "" for c in row]
                for k in range(len(cells) - 1):
                    if re.fullmatch(r"\d+", cells[k]) and re.fullmatch(r"[A-E／/]+", cells[k + 1] or ""):
                        ans[int(cells[k])] = cells[k + 1].replace("/", "／")
    return ans


def parse_year(year):
    lines = flatten_md("%s/%d_%s_試題.md" % (RAW, year, SUBJECT))
    single_max, part2_idx = section_bounds(lines)
    text = "\n".join(lines)
    groups = parse_groups(text)
    qs = parse_questions(text, single_max)
    ans = parse_answers("%s/%d_%s_答案.pdf" % (RAW, year, SUBJECT))
    # 答案表是大考中心官方完整題號清單(含非選的「／」):以此為權威過濾,剔除卷末
    # 附錄/評分參考表裡被誤判為題號的孤立數字(如 111 的 69-80)。
    valid_nos = set(ans)
    pdf = "%s/%d_%s_試題.pdf" % (RAW, year, SUBJECT)
    _rows = []  # PDF 座標行,lazy 建立(僅在需要 fallback 時)
    out = []
    for q in qs:
        no = q["no"]
        if no not in valid_nos:
            continue
        a = ans.get(no, "")
        # markitdown 破碎統計表(如 111)會讓選擇題選項不足/題幹變數字碎片:答案是
        # 選擇字母(A-E)但解析選項<4 → 改由 PDF 座標重抓題幹+選項(閱讀順序可靠)。
        if a and a != "／" and re.fullmatch(r"[A-E]+", a) and len(q["options"]) < 4:
            if not _rows:
                _rows = pdf_text_rows(pdf)
            fstem, fopts = qfix_from_pdf(_rows, no)
            if fopts:
                q["options"] = fopts
                if fstem:
                    q["stem"] = fstem
        # 非選題(答案「／」)題幹被破碎表打成碎片(中文字 <8)→ 由 PDF 座標重抓題幹。
        is_nonmc = (a == "／") or (a == "" and not q["options"])
        if is_nonmc and len(re.findall(r"[一-鿿]", q["stem"])) < 8:
            if not _rows:
                _rows = pdf_text_rows(pdf)
            fstem = nonmc_stem_from_pdf(_rows, no)
            if fstem and len(re.findall(r"[一-鿿]", fstem)) >= 8:
                q["stem"] = fstem
        gd = groups.get(no)
        if gd:
            ga, gb, passage = gd
            gid = "%d_社會_g%d_%d" % (year, ga, gb)
        else:
            gid, passage = None, ""
        # 型別:非選(答案「／」或空且無選項)/多選/單選
        if a == "／" or (a == "" and not q["options"]):
            qtype, answer = "非選", ""
        elif len(a) > 1:
            qtype, answer = "多選", a
        else:
            qtype, answer = "單選", a
        nf = needs_figure(q["stem"], passage, q["options"], answer)
        out.append({
            "qid": "%d_社會_%d" % (year, no), "exam": EXAM, "subject": SUBJECT,
            "year": year, "no": no,
            "domain": infer_domain(q["stem"], passage),
            "type": qtype, "stem": q["stem"], "options": q["options"],
            "answer": answer, "group_id": gid, "passage": passage,
            "needs_figure": nf,
        })
    return out


def merge_bank(new_soc):
    """讀現有 bank.json → 移除舊社會 → 加新社會 → 寫回(idempotent,不動國綜/英文)。"""
    if os.path.exists(BANK):
        obj = json.load(open(BANK, encoding="utf-8"))
    else:
        obj = {"meta": {}, "questions": []}
    kept = [q for q in obj.get("questions", []) if q.get("subject") != SUBJECT]
    merged = kept + new_soc
    years_soc = sorted({q["year"] for q in new_soc})
    meta = obj.get("meta", {})
    meta["n"] = len(merged)
    meta["subjects"] = sorted({q.get("subject") for q in merged})
    meta.setdefault("source", "大考中心 學測歷年試題(著作權法 §9 不受著作權保護)")
    meta["social"] = {"years": years_soc, "n": len(new_soc),
                      "parser": "markitdown table-flatten + pymupdf find_tables"}
    obj["meta"] = meta
    obj["questions"] = merged
    json.dump(obj, open(BANK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return len(kept), len(merged)


def main():
    years = sorted({int(re.match(r"(\d+)_", os.path.basename(p)).group(1))
                    for p in glob.glob("%s/*_%s_試題.md" % (RAW, SUBJECT))})
    all_soc = []
    for y in years:
        qs = parse_year(y)
        all_soc.extend(qs)
        n = len(qs)
        ans_n = sum(1 for q in qs if q["answer"])
        fig_n = sum(1 for q in qs if q["needs_figure"])
        grp_ids = {q["group_id"] for q in qs if q["group_id"]}
        types = {}
        for q in qs:
            types[q["type"]] = types.get(q["type"], 0) + 1
        type_str = " ".join("%s%d" % (t, c) for t, c in sorted(types.items()))
        print("%d 社會:%d 題 | 型別 %s | 有答案 %d | needs_figure %d (%.0f%%) | 題組 %d" % (
            y, n, type_str, ans_n, fig_n, 100 * fig_n / n if n else 0, len(grp_ids)))

    total = len(all_soc)
    fig_total = sum(1 for q in all_soc if q["needs_figure"])
    print("\n合計 %d 題 | 文字可答 %d (%.0f%%) vs 須對照圖表 %d (%.0f%%)" % (
        total, total - fig_total, 100 * (total - fig_total) / total,
        fig_total, 100 * fig_total / total))

    # 抽 3 題樣本
    print("\n抽樣(qid / domain / type / stem前40 / 選項數 / answer / needs_figure):")
    import random
    random.seed(7)
    for q in random.sample(all_soc, 3):
        stem = (q["stem"] or q["passage"])[:40]
        print("  %s | %s | %s | %s… | opts=%d | ans=%r | fig=%s" % (
            q["qid"], q["domain"] or "(空)", q["type"], stem,
            len(q["options"]), q["answer"], q["needs_figure"]))

    kept, merged = merge_bank(all_soc)
    print("\n合併:保留非社會 %d 題 + 新社會 %d 題 = %d 題 → %s" % (
        kept, total, merged, BANK))


if __name__ == "__main__":
    main()
