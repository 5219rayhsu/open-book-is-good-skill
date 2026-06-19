#!/usr/bin/env python3
"""國中教育會考(CAP)社會科 markitdown(.md) → 結構化題庫(題組感知、跨領域、多年度)。

會考社會卷結構(逐字忠實擷取原文,絕不改寫/摘要/翻譯;約 54 題/年,全為四選一單選):
  一、單題：(1～N 題)        每題獨立題幹 + (A)-(D) 四選項。
  二、題組：(N+1～54 題)      共用「閱讀下列選文,回答第 a 至 b 題：」選文,綁同一 group_id。
其中 N 因年而異(111-113、115 為 43;114 為 42)。歷史/地理/公民混合,大量圖表題。

markitdown 產出特性(本程式須容錯):
  1) 前約 1.5 頁為「測驗說明 / 注意事項 / 作答方式」,在「一、單題」標記前全部跳過;
  2) 中文字之間殘留空格(如「某 宗 教 的 全 球」),由 join_clean 還原;
  3) 選項可能順序顛倒(B 在 A 前)、跨多行,以字母 (A)-(D) 為鍵歸位;
  4) 頁眉/頁碼(孤立數字)/「請翻頁繼續作答」(會黏在題號或題組標頭前)/註釋行
     (以「&」起首,如「& 山竹：一種水果。」)→ 全部清掉,避免污染題幹/選項/passage。

needs_figure(社會圖表多,寧可多標):題幹或 passage 出現「圖(/表(/地圖/附圖/照片/
示意圖/統計圖…」,或選項數 < 4、或選項全空(圖被吃掉) → true。

答案:解析 data/raw/{年}_會考_參考答案.pdf(該檔含各科橫向對照表)。以 pymupdf
find_tables 取得 7 欄表,依表頭定位「社會」欄(固定為 index 5,但仍動態偵測表頭),
逐列取「題號 / 社會答案(A-D)」。每年應得 1-54 共 54 個答案。

前置(每年):
  markitdown data/raw/{年}_會考社會_試題.pdf -o data/raw/{年}_會考社會_試題.md
  (PDF 由 scripts/fetch_cap.py 下載)
用法:uv run --with pymupdf python3 scripts/parse_cap_社會.py
輸出:data/_stage/cap_社會.json(陣列;不直接動 bank.json,合併由上游負責)
著作權:心測中心歷年試題,著作權法 §9 不受著作權保護。
"""
import fitz
import glob
import json
import os
import re

RAW = "data/raw"
STAGE = "data/_stage"
OUT = os.path.join(STAGE, "cap_社會.json")
EXAM = "會考"
SUBJECT = "社會"

# 頁眉/頁碼/裝飾行:攤平後逐行過濾。會考的頁碼是孤立阿拉伯數字(如「3」)獨佔一行,
# 試題本標題、翻頁提示等亦在此剔除(題幹/選項/passage 不會是純數字行)。
DROP = re.compile(
    r"^\s*("
    r"\d+"                                  # 孤立頁碼
    r"|請翻頁繼續作答"                       # 翻頁提示(獨佔行)
    r"|請不要翻到次頁[！!]?"
    r"|讀完本頁的說明.*"
    r"|試題結束"
    r"|\d+\s*年\s*國\s*中\s*教\s*育\s*會\s*考"  # 試題本標題(逐字拆字版)
    r"|社\s*會\s*科\s*試\s*題\s*本"
    r"|&\s*.*"                              # 註釋行(& 山竹：一種水果。)
    r")\s*$"
)

# 章節邊界:一、單題(取單題題號上限 N)、二、題組起點。
PART1_HDR = re.compile(r"一\s*、\s*單\s*題\s*[:：︰]?\s*[(（]\s*\d+\s*[~～至]\s*(\d+)\s*題")
PART2_HDR = re.compile(r"二\s*、\s*題\s*組")

# 題組標頭:「閱讀下列選文,回答第 a 至 b 題：」(可能被「請翻頁繼續作答」黏在前面)。
GROUP_HDR = re.compile(r"閱\s*讀.*?回\s*答\s*第\s*(\d+)\s*[至到~～\-]\s*(\d+)\s*題")

# 「請翻頁繼續作答」黏在題號或題組標頭前綴 → 行首移除。
TURN_PAGE = re.compile(r"^\s*請翻頁繼續作答")

# needs_figure 觸發字:會考以「圖(一)」「表(二)」帶括號編號為主,另含地圖/照片等。
FIG_KW = re.compile(r"圖\s*[(（]|表\s*[(（]|地\s*圖|附\s*圖|照\s*片|示\s*意|統\s*計\s*圖|衛\s*星\s*影\s*像")

# 中日韓統一表意文字範圍:用於移除中文字之間殘留空格(markitdown 逐字拆字所致)。
_CJK = r"　-〿㐀-䶿一-鿿＀-￯"

# 選項尾巴污染邊界:會考圖表常排在選項「之後」,markitdown/PDF 座標把圖表/表格資料/
# 頁碼/(cid:…)字型碎片/座標軸數值接在選項後面,致選項貪婪吃進整段非選項內容。
# 選項內容遇下列任一即截斷(僅截斷,保留前面真正的選項原文,不改寫):
#   圖( / 表( 圖表標號、(cid: 字型碎片、「(空白)題號.」下一題起始、
#   座標軸/統計值(逗號千分位如 70,000、或 3+ 位數的孤立數字如 13460),選項文字
#   不會含此類大數;單一年分(2020)等 4 位數仍可能出現在選項中故不一律切。
_OPT_TAIL = re.compile(
    r"圖\s*[(（]|表\s*[(（]|\(cid:|\s\d+\s*[.．]\s*\S"
    r"|\s\d{1,3}(?:,\d{3})+"                # 千分位數字(70,000)
)
# markitdown 對嵌入字型解碼失敗的殘碼,全程清除(不具語意,純雜訊)。
_CID = re.compile(r"\(cid:\d+\)")


def clean_lines(md_path):
    """讀 markdown → 去 markdown 表格分隔線、攤平表格 cell、去頁眉頁碼/翻頁/註釋;
    每行行首的「請翻頁繼續作答」前綴亦剝除。回傳乾淨多行純文字(保留行首錨點)。"""
    body = open(md_path, encoding="utf-8").read()
    out = []
    for ln in body.split("\n"):
        s = ln.rstrip()
        # markdown 表格分隔線 |---|---| → 丟棄
        if re.match(r"^\s*\|?\s*[-:]+\s*(\|\s*[-:]+\s*)+\|?\s*$", s):
            continue
        # 表格列:把各 cell 抽出,逐 cell 換行(保留題號/選項/題組標頭的行首錨點)
        if "|" in s and s.count("|") >= 2:
            for c in (c.strip() for c in s.strip().strip("|").split("|")):
                if c:
                    out.append(c)
            continue
        if not s.strip():
            continue
        # 剝除「請翻頁繼續作答」黏在行首的前綴(其後可能直接接題號或題組標頭)
        s = TURN_PAGE.sub("", s).strip()
        if not s:
            continue
        out.append(s)
    return [l for l in out if not DROP.match(l)]


def join_clean(s):
    """把多行併一行、壓縮空白,並反覆移除「中文字 空格 中文字」間空格(逐字拆字還原);
    只動兩側皆為 CJK 的空格,保留英數/標點與中文間的空白,避免黏壞英文與數字。
    並清除 (cid:…) 字型解碼殘碼(純雜訊)。"""
    s = _CID.sub("", s)
    s = re.sub(r"[ \t]+", " ", re.sub(r"\n+", " ", s)).strip()
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"(?<=[%s]) (?=[%s])" % (_CJK, _CJK), "", s)
    return s


# 整段即圖表座標軸數值(如圖選項把整個 (B) 內容抓成「9,998」千分位、或純大數),
# 非選項文字 → 視為空選項(圖選項)。選項真實文字中的千分位(9,999元)有中文/單位
# 黏附,不會整段只有數字,故以「整段 fullmatch 純數字/千分位」為準,不誤傷。
_OPT_PURE_NUM = re.compile(r"^\d{1,3}(?:,\d{3})+$|^\d{3,}$")


def trim_option(content):
    """清掉選項內容尾端被黏入的圖表/表格資料/頁碼/(cid:…)/下一題號(僅截斷,保留原文);
    若整段即座標軸大數(圖選項殘留),視為空選項。"""
    s = join_clean(content)
    m = _OPT_TAIL.search(s)
    if m:
        s = s[:m.start()].strip()
    if _OPT_PURE_NUM.fullmatch(s):           # 整段純大數/千分位 = 圖表座標軸殘留 → 空
        s = ""
    return s


def section_bounds(lines):
    """切出第一部分(單選題號上限 N)與第二部分(題組)起點。回傳 (single_max, part2_idx)。"""
    single_max, part2_idx = None, len(lines)
    for i, ln in enumerate(lines):
        m = PART1_HDR.search(ln)
        if m and single_max is None:
            single_max = int(m.group(1))
        if PART2_HDR.search(ln) and part2_idx == len(lines):
            part2_idx = i
    return single_max, part2_idx


def start_index(lines):
    """找「一、單題」標記所在行 index;其前為測驗說明/注意事項,全部跳過。
    找不到則回 0(保底,理論上每年都有)。"""
    for i, ln in enumerate(lines):
        if PART1_HDR.search(ln):
            return i
    return 0


def parse_groups(text):
    """掃所有題組標頭「閱讀…回答第 a 至 b 題：」,建 no -> (a, b, passage)。
    passage = 標頭後到第一個子題「a.」前的選文(攤平純文字)。"""
    heads = []  # (pos_end, a, b)
    for m in GROUP_HDR.finditer(text):
        heads.append((m.end(), int(m.group(1)), int(m.group(2))))
    heads.sort()
    g = {}
    for k, (pe, a, b) in enumerate(heads):
        nxt = heads[k + 1][0] if k + 1 < len(heads) else len(text)
        rest = text[pe:nxt]
        qm = re.search(r"(?m)^\s*%d\s*[.．]\s*" % a, rest)
        passage = join_clean(rest[:qm.start()]) if qm else join_clean(rest)
        # 標頭「…回答第 a 至 b 題」後緊接的冒號殘留(：/:)剝除,passage 由正文起。
        passage = re.sub(r"^[：:]\s*", "", passage)
        for n in range(a, b + 1):
            g[n] = (a, b, passage)
    return g


def split_stem_options(seg):
    """切出題幹 + 選項 dict{A..D}(以字母 (A)-(D) 為鍵,取第一次;容許順序顛倒、跨行)。"""
    om = list(re.finditer(r"\(([A-D])\)", seg))
    if not om:
        return join_clean(seg), {}
    stem = seg[:om[0].start()]
    opts = {}
    for j, m in enumerate(om):
        letter = m.group(1)
        content = seg[m.end(): om[j + 1].start() if j + 1 < len(om) else len(seg)]
        if letter not in opts:
            opts[letter] = trim_option(content)
    return join_clean(stem), opts


def parse_questions(text, valid_nos):
    """以行首題號(1.~54.)切題;題號限定在 valid_nos(答案表權威清單),剔除誤判。
    每段切出題幹 + (A)-(D) 選項。回傳 no -> {stem, options}。"""
    # 題號行格式固定為「N.␣␣…」(點後至少一個空白,試題本雙空格縮排,題幹可能以
    # 數字起首如「2014 年…」或題號獨佔一行)。表格統計值(16.1、36.28、1.5)點後緊接
    # 數字、無空白,以「點後須為空白」精準排除被誤判為題號的統計值。
    starts = []
    for mm in re.finditer(r"(?m)^\s*(\d+)\s*[.．]\s", text):
        no = int(mm.group(1))
        if no in valid_nos:
            starts.append(mm)
    # 去重題號:保留每題號第一次出現(攤平偶有重複殘影)
    seen, valid = set(), []
    for mm in starts:
        no = int(mm.group(1))
        if no in seen:
            continue
        seen.add(no)
        valid.append(mm)
    out = {}
    for i, mm in enumerate(valid):
        no = int(mm.group(1))
        end = valid[i + 1].start() if i + 1 < len(valid) else len(text)
        seg = text[mm.end():end]
        # 段內若殘留下一個題組標頭/章節說明 → 截掉,避免吃進別題
        cut = GROUP_HDR.search(seg) or PART2_HDR.search(seg)
        if cut:
            seg = seg[:cut.start()]
        stem, opts = split_stem_options(seg)
        out[no] = {"stem": stem, "options": opts}
    return out


def pdf_text_rows(pdf):
    """以 PDF 座標蒐集所有文字行(page, y, x, text),依閱讀順序(頁→上→左)排序。
    用於 markitdown 把雙欄選項(A|B 同列、C|D 次列)線性化失敗時的選項 fallback。"""
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


def pdf_options(rows, no):
    """從 PDF 座標重抓單一題(no)的選項(A-D):找「no. …」起始列,其後依閱讀順序
    (上→左,故雙欄會是 A,B,C,D)收集 (X) 選項,集滿 4 個或遇下一題號即停。
    回傳 dict{A..D}(可能空內容,如純圖選項) 或 {} 找不到。會考雙欄選項以此為準。"""
    si = None
    for i, (pi, y, x, txt) in enumerate(rows):
        if re.match(r"^%d\s*[.．]\s" % no, txt):
            si = i
            break
    if si is None:
        return {}
    opts = {}
    for pi, y, x, txt in rows[si + 1:]:
        m_next = re.match(r"^(\d+)\s*[.．]\s", txt)
        if m_next and int(m_next.group(1)) != no:
            break
        for om in re.finditer(r"\(([A-D])\)\s*([^()]*)", txt):
            letter = om.group(1)
            if letter not in opts:
                opts[letter] = trim_option(om.group(2))
        if len(opts) >= 4:
            break
    return opts if len(opts) == 4 else {}


def parse_answers(pdf):
    """解析會考參考答案 PDF(各科橫向對照表):find_tables 取 7 欄表,動態偵測「社會」
    欄,逐列取「題號 / 社會答案(A-D)」。回傳 no -> 'A'..'D'。"""
    ans = {}
    doc = fitz.open(pdf)
    for pg in doc:
        for tb in pg.find_tables().tables:
            ex = tb.extract()
            # 偵測「社會」欄 index(表頭某 cell 含「社會」)
            sidx = None
            for row in ex:
                for j, c in enumerate(row):
                    if c and "社會" in c.replace(" ", "").replace("\n", ""):
                        sidx = j
            if sidx is None:
                continue
            for row in ex:
                qn = (row[0] or "").strip()
                if re.fullmatch(r"\d+", qn) and sidx < len(row):
                    a = (row[sidx] or "").strip()
                    if re.fullmatch(r"[A-D]", a):
                        ans[int(qn)] = a
    return ans


def needs_figure(stem, passage, options):
    """寧可多標:題幹/passage 含圖表字、或選項數 < 4、或選項全空(圖被吃掉) → true。"""
    if FIG_KW.search((stem or "") + " " + (passage or "")):
        return True
    if options:
        if len(options) < 4:
            return True
        if all(not v for v in options.values()):
            return True
    return False


def parse_year(year):
    """解析單一年度:回傳該年題目 list(依題號排序)。"""
    md = "%s/%d_會考%s_試題.md" % (RAW, year, SUBJECT)
    lines = clean_lines(md)
    si = start_index(lines)
    lines = lines[si:]                       # 跳過測驗說明/注意事項
    single_max, part2_idx = section_bounds(lines)
    text = "\n".join(lines)

    ans = parse_answers("%s/%d_會考_參考答案.pdf" % (RAW, year))
    valid_nos = set(ans)                     # 答案表為官方權威題號清單(應為 1-54)
    groups = parse_groups(text)
    qmap = parse_questions(text, valid_nos)

    pdf = "%s/%d_會考%s_試題.pdf" % (RAW, year, SUBJECT)
    _rows = []                               # PDF 座標行,lazy 建立(僅 fallback 時)

    out = []
    for no in sorted(valid_nos):
        q = qmap.get(no, {"stem": "", "options": {}})
        # markitdown 對雙欄選項(A|B 同列、C|D 次列)或圖表夾在選項間時會亂序/漏抓,
        # 致選項 < 4。改由 PDF 座標(閱讀順序可靠)重抓四選項;成功才覆蓋。
        if len(q["options"]) < 4:
            if not _rows:
                _rows = pdf_text_rows(pdf)
            fopts = pdf_options(_rows, no)
            if fopts:
                q["options"] = fopts
        gd = groups.get(no)
        if gd:
            ga, gb, passage = gd
            gid = "會考_%d_%s_g%d_%d" % (year, SUBJECT, ga, gb)
        else:
            gid, passage = None, ""
        nf = needs_figure(q["stem"], passage, q["options"])
        out.append({
            "qid": "會考_%d_%s_%d" % (year, SUBJECT, no),
            "exam": EXAM,
            "subject": SUBJECT,
            "year": year,
            "no": no,
            "type": "單選",                  # 會考全為四選一單選
            "group_id": gid,
            "passage": passage,
            "stem": q["stem"],
            "options": q["options"],
            "answer": ans.get(no, ""),
            "needs_figure": nf,
        })
    return out


def validate(year, qs):
    """逐年自驗,回傳 issue 字串 list(空=該年通過)。"""
    issues = []
    n = len(qs)
    # 題數合理(會考社會固定 54 題)
    if n != 54:
        issues.append("%d 年題數 %d ≠ 54" % (year, n))
    # 題號連續 1..n、無重複
    nos = [q["no"] for q in qs]
    if nos != list(range(1, n + 1)):
        issues.append("%d 年題號不連續/有缺漏:%s" % (year, nos))
    for q in qs:
        no = q["no"]
        # 答案齊全且為 A-D
        if q["answer"] not in ("A", "B", "C", "D"):
            issues.append("%d 年第 %d 題答案異常:%r" % (year, no, q["answer"]))
        # 選項齊全(A-D 四個);needs_figure 圖被吃時可能不足,單獨列為提醒不算硬錯
        if set(q["options"]) != {"A", "B", "C", "D"}:
            tag = "(needs_figure)" if q["needs_figure"] else ""
            issues.append("%d 年第 %d 題選項不齊:有 %s%s" % (
                year, no, "".join(sorted(q["options"])) or "(無)", tag))
        # 題幹不應為空(needs_figure 圖題仍應有文字題幹)
        if not q["stem"]:
            issues.append("%d 年第 %d 題題幹為空" % (year, no))
        # 選項洩漏偵測:某選項內容若殘留「(X)」其他選項字母,代表切割失敗
        for letter, content in q["options"].items():
            if re.search(r"\([A-D]\)", content):
                issues.append("%d 年第 %d 題選項 %s 疑似洩漏其他選項:%s" % (
                    year, no, letter, content[:30]))
            # 選項內殘留下一題題號(如「… 14.」)→ 洩漏到別題
            if re.search(r"\s\d+\s*[.．]\s*\S", content):
                issues.append("%d 年第 %d 題選項 %s 疑似吃進下一題號:%s" % (
                    year, no, letter, content[:30]))
    # 題組完整性:同一 group_id 的題號應連續且涵蓋標頭宣告的 a..b
    gmap = {}
    for q in qs:
        if q["group_id"]:
            gmap.setdefault(q["group_id"], []).append(q["no"])
    for gid, members in gmap.items():
        m = re.search(r"_g(\d+)_(\d+)$", gid)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if sorted(members) != list(range(a, b + 1)):
                issues.append("%d 年題組 %s 成員不完整:宣告 %d-%d 實得 %s" % (
                    year, gid, a, b, sorted(members)))
    return issues


def main():
    os.makedirs(STAGE, exist_ok=True)
    years = sorted({int(re.match(r"(\d+)_", os.path.basename(p)).group(1))
                    for p in glob.glob("%s/*_會考%s_試題.md" % (RAW, SUBJECT))})
    all_q = []
    all_issues = []
    print("年度 | 題數 | 有答案 | 選項齊全 | 題組數 | needs_figure")
    for y in years:
        qs = parse_year(y)
        all_q.extend(qs)
        n = len(qs)
        ans_n = sum(1 for q in qs if q["answer"] in ("A", "B", "C", "D"))
        full_opt = sum(1 for q in qs if set(q["options"]) == {"A", "B", "C", "D"})
        grp_n = len({q["group_id"] for q in qs if q["group_id"]})
        fig_n = sum(1 for q in qs if q["needs_figure"])
        print("%d  |  %d  |  %d  |  %d  |  %d  |  %d (%.0f%%)" % (
            y, n, ans_n, full_opt, grp_n, fig_n, 100 * fig_n / n if n else 0))
        all_issues.extend(validate(y, qs))

    json.dump(all_q, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    total = len(all_q)
    fig_total = sum(1 for q in all_q if q["needs_figure"])
    print("\n合計 %d 題 | 文字可答 %d (%.0f%%) vs 須對照圖表 %d (%.0f%%)" % (
        total, total - fig_total, 100 * (total - fig_total) / total if total else 0,
        fig_total, 100 * fig_total / total if total else 0))
    print("寫出 → %s" % OUT)

    print("\n自驗 issues(%d):" % len(all_issues))
    for it in all_issues:
        print("  -", it)


if __name__ == "__main__":
    main()
