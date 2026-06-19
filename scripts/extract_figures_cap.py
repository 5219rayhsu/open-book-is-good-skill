# -*- coding: utf-8 -*-
"""
extract_figures_cap.py — 會考(CAP)「需要圖」題目版面區塊萃取器

目的
----
把 data/_stage/cap_{科}.json 中 needs_figure==True 的題目,所在原卷 PDF
(data/raw/{年}_會考{科}_試題.pdf)的版面區塊 render 成乾淨 PNG,存到
data/figures/,並把 figure 檔名寫回 staging JSON(只動 staging,不碰正本)。
忠實重現原卷(raster+vector 一起點陣化),不簡化、不重排。

安全規則(最高優先)
------------------
- 圖一律存成獨立二進位 PNG 檔。本腳本「只」印出:張數、位元組大小、檔名、
  座標數字、計數。絕不 print 圖片 bytes / base64 / data URL、不 cat 圖檔。
- staging JSON 只寫入檔名字串(figure 欄),永不寫 base64,保持純文字可 lint。

定位策略(沿用並改寫 extract_figures.py)
----------------------------------------
會考版面與學測不同處:
1. 題號行(「{no}.」於左邊界 x0<90)非常穩定,作為 band 邊界的主錨點。
   學測用 stem 定位;但會考「這張圖最可能…」型題的圖在「題號行」與「stem」
   之間,若用 stem 當上界會把圖切掉。故改用「題號行」當獨立題的上下界。
2. 題組共用材料/圖:用子標題「…回答第 {首} 至 {末} 題：」/「…回答{首}～{末}題：」
   當 passage 上界錨點;下界=同頁該題組第一個子題的題號行。
3. band 內圖片(raster)+向量圖底部取 max,避免圖被下界切半張(沿用原機制)。

檔名規則(依任務指定)
--------------------
- 獨立題 : C{年}_{科}_q{no}.png            例 C111_國文_q1.png
- 題組   : C{年}_{科}_g{首題no}_{末題no}.png  例 C111_社會_g44_45.png
  題組區間取「該 group 全部成員的 min~max 題號」(忠實:共用同一張圖),
  group 內所有 needs_figure 子題的 figure 欄都指向這張。

冪等:只刪除/重建本腳本負責科目的 C 開頭 PNG(C{年}_{科}_*),不動學測 S/G/E。

用法
----
    uv run --with pymupdf python scripts/extract_figures_cap.py
    uv run --with pymupdf python scripts/extract_figures_cap.py --dry-run
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

import fitz  # PyMuPDF

# ---- 路徑 ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
STAGE_DIR = os.path.join(ROOT, "data", "_stage")
RAW_DIR = os.path.join(ROOT, "data", "raw")
FIG_DIR = os.path.join(ROOT, "data", "figures")

# 只處理當前 staging 在跑的科目(cap_{科}.json 須存在)。國文/社會/自然圖已裁好並進 bank。
SUBJECTS = ["英語"]
YEARS = [111, 112, 113, 114, 115]

# ---- render 參數(與學測一致)----
ZOOM = 2.2
MATRIX = fitz.Matrix(ZOOM, ZOOM)

# ---- band 邊界微調(point,72dpi)----
TOP_PAD = 6.0
BOTTOM_PAD = 5.0
HEADER_Y = 50.0                  # 會考內文頁上緣約 y~54
FOOTER_Y_MARGIN = 36.0           # 頁尾頁碼區
SIDE_MARGIN_L = 44.0
SIDE_MARGIN_R = 12.0

QNUM_X_MAX = 92.0                # 題號行左邊界上限(x0)

# 題號行:行首為「{no}.」或「{no}．」
QNUM_RE = re.compile(r"^\s*(\d{1,3})[.．]")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def collect_question_anchors(page) -> list:
    """
    回傳該頁所有「題號行」起點 [(no:int, y0:float), ...],依 y 排序。
    題號行 = 行首為「{no}.」且左邊界 x0 < QNUM_X_MAX。
    """
    d = page.get_text("dict")
    anchors = []
    for block in d["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            x0 = line["bbox"][0]
            if x0 >= QNUM_X_MAX:
                continue
            txt = "".join(s["text"] for s in line["spans"])
            m = QNUM_RE.match(txt)
            if m:
                anchors.append((int(m.group(1)), line["bbox"][1]))
    anchors.sort(key=lambda a: a[1])
    return anchors


def build_page_anchors(doc) -> dict:
    """pno -> sorted [(no, y0)] 題號行錨點。"""
    return {pno: collect_question_anchors(doc[pno]) for pno in range(len(doc))}


def find_question_top(page_anchors: dict, no: int):
    """
    在全份 PDF 找題號 no 的題號行 -> (pno, y0)。
    同號可能在多頁(理論上不會),取第一個命中。
    """
    for pno in sorted(page_anchors.keys()):
        for (n, y0) in page_anchors[pno]:
            if n == no:
                return pno, y0
    return None


def next_anchor_y(page_anchors: dict, pno: int, y0: float):
    """同頁、y 大於 y0 的下一個題號行 y;無則 None(到頁尾)。"""
    cand = [y for (n, y) in page_anchors[pno] if y > y0 + 2]
    return min(cand) if cand else None


# 題組/大題 section 標題:用來當獨立題 band 的下界硬上限,避免吃進題組材料。
# 注意:必須只匹配「真正的大題標題」(如「二、題組：」「請閱讀…回答X～Y題」),
# 不可誤匹配右側材料框內的條列(如法規「一、春節。」)——故:
#   1) 只看左邊界行(x0 < QNUM_X_MAX),材料框內文 x0 較大會被排除;
#   2) 中文數字大題標題須緊接「單題/題組」等關鍵字,不單看「一、」。
SECTION_RE = re.compile(
    r"題組|回答第?\d+\s*[~～\-－至到]\s*\d+\s*題"
    r"|^[一二三四五六七八九十]+、\s*(?:單題|題組|題)"
)


def next_section_y(page, y0: float):
    """同頁、y 大於 y0 的第一個題組/大題 section 標題行 y(僅限左邊界行);無則 None。"""
    d = page.get_text("dict")
    cand = []
    for block in d["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            y = line["bbox"][1]
            if y <= y0 + 2:
                continue
            if line["bbox"][0] >= QNUM_X_MAX:   # 右側材料框內文排除
                continue
            txt = norm("".join(s["text"] for s in line["spans"]))
            if SECTION_RE.search(txt):
                cand.append(y)
    return min(cand) if cand else None


GROUP_HEAD_PREFIXES = ("回答第", "回答")


def find_group_head(doc, first_no: int, last_no: int):
    """
    找題組子標題「…回答第 {首} 至 {末} 題：」或「…回答{首}～{末}題：」。
    回傳 (pno, y0) 或 None。容忍各種分隔符與空白。
    """
    # 正規化後比對:回答(第?){首}(分隔){末}題
    seps = r"[~～\-－至到]"
    pat = re.compile(
        rf"回答第?{first_no}\s*{seps}\s*{last_no}\s*題"
    )
    for pno in range(len(doc)):
        d = doc[pno].get_text("dict")
        for block in d["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                txt = norm("".join(s["text"] for s in line["spans"]))
                if pat.search(txt):
                    return pno, line["bbox"][1]
    return None


def figure_segment_count(page, y0: float, y1: float, xL: float, xR: float) -> int:
    """
    區間 [y0,y1] 內「圖形繪製線段」數量(向量 drawings + raster 圖)。
    用來判斷某子題區是否含真正的圖(計分表/示意圖/路線圖等):
    純文字題此值很低(僅文字無 drawing);含圖題會有大量線段。
    排除整頁/整框級的大矩形(passage 外框)以免誤判文字框為圖。
    """
    H = page.rect.height
    cnt = 0
    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    for dr in drawings:
        r = dr.get("rect")
        if r is None:
            continue
        if r.y1 < y0 or r.y0 > y1:
            continue
        if r.x1 < xL or r.x0 > xR:
            continue
        h = r.y1 - r.y0
        w = r.x1 - r.x0
        if h > H * 0.6 and w > (xR - xL) * 0.8:   # passage/page 外框,排除
            continue
        cnt += 1
    for img in page.get_images(full=True):
        try:
            rects = page.get_image_rects(img[0])
        except Exception:
            continue
        for r in rects:
            if r.y1 < y0 or r.y0 > y1:
                continue
            if (r.y1 - r.y0) > H * 0.85:
                continue
            cnt += 10   # raster 圖權重高(一定是圖)
    return cnt


# 子題區「含圖」門檻:向量線段數超過此值視為該子題自帶圖(非純文字選項)。
CHILD_FIG_SEG_MIN = 40
# passage 區「圖佔主導」門檻:超過此值代表共用圖就在 passage(海報/示意圖/插畫)。
PASSAGE_FIG_DOMINANT = 100
# 子題題幹/選項出現這些字樣,代表該子題自帶圖/表(常在題幹旁或選項區)。
CHILD_FIG_REF_RE = re.compile(
    r"右圖|左圖|下圖|上圖|右表|左表|下表|上表|如圖|附圖|示意圖|圖表|下列圖|哪一(?:張|個)圖"
)


def child_references_figure(q: dict) -> bool:
    """子題題幹/選項是否明指自帶圖表(右圖/右表/示意圖/圖表…),或選項為空(圖選項)。"""
    if CHILD_FIG_REF_RE.search(q.get("stem", "")):
        return True
    opts = q.get("options", {}) or {}
    if not opts:                       # 選項為空 = 圖形選項(解析時無文字可填)
        return True
    if all(len((v or "").strip()) == 0 for v in opts.values()):
        return True
    return False


def page_text_bottom(page) -> float:
    """頁面最後一行內文 y1(排除頁碼),作為頁尾 band 下界上限。"""
    d = page.get_text("dict")
    cap = page.rect.height - FOOTER_Y_MARGIN
    ys = []
    for block in d["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                y1 = span["bbox"][3]
                if y1 < cap:
                    ys.append(y1)
    return max(ys) if ys else cap


def band_image_bottom(page, y0, y1, xL, xR, hard_limit) -> float:
    """
    band 內圖片(raster)+向量圖最低 y1,防止圖被下界切掉(沿用學測機制)。
    """
    SLACK = 24.0
    cap = hard_limit if hard_limit is not None else (page.rect.height - FOOTER_Y_MARGIN)
    bottom = y1

    def consider(r):
        nonlocal bottom
        if r.x1 < xL or r.x0 > xR:
            return
        if (r.y1 - r.y0) > page.rect.height * 0.85:   # 整頁框線排除
            return
        if y0 - 2 <= r.y0 <= y1 + SLACK:
            bottom = max(bottom, min(r.y1, cap))

    for img in page.get_images(full=True):
        try:
            rects = page.get_image_rects(img[0])
        except Exception:
            continue
        for r in rects:
            consider(r)
    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    for dr in drawings:
        r = dr.get("rect")
        if r is not None:
            consider(r)
    return min(bottom, cap)


def band_image_top(page, y0, y1, xL, xR, soft_limit) -> float:
    """
    band 內圖片(raster)+向量圖最高 y0,用來防止「圖頂高於題號行」的圖被上界
    切掉(會考右側並排圖常比題幹高,頂端凸出於題號行上方)。
    - 只考慮「圖底落在 band 內」(y0-SLACK <= r.y1 <= y1)的圖,代表該圖屬本題。
    - 延伸後的上界絕不高於 soft_limit(前一題下界/頁眉),避免吃進上一題。
    找不到需延伸的圖則回傳原 y0。
    """
    SLACK = 24.0
    cap = soft_limit if soft_limit is not None else (HEADER_Y - 6)
    top = y0

    def consider(r):
        nonlocal top
        if r.x1 < xL or r.x0 > xR:
            return
        if (r.y1 - r.y0) > page.rect.height * 0.85:   # 整頁框線排除
            return
        # 只延伸「跨越題號行的右側並排圖」:圖頂在題號行上方、圖底在題號行下方,
        # 代表該圖與本題並排(頂端凸出於題號)。若圖整個在題號行上方(r.y1<=y0)則
        # 屬上一題,不可納入。
        if r.y0 < y0 and r.y1 > y0 + SLACK and r.y1 <= y1 + 2:
            top = min(top, max(r.y0, cap))

    for img in page.get_images(full=True):
        try:
            rects = page.get_image_rects(img[0])
        except Exception:
            continue
        for r in rects:
            consider(r)
    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    for dr in drawings:
        r = dr.get("rect")
        if r is not None:
            consider(r)
    return max(top, cap)


def clamp_bottom(page, bottom) -> float:
    return min(bottom, page.rect.height - FOOTER_Y_MARGIN)


def render_band(page, y0, y1, xL, xR, out_path):
    y0 = max(y0, HEADER_Y - 6)
    clip = fitz.Rect(xL, y0, xR, y1)
    pix = page.get_pixmap(matrix=MATRIX, clip=clip)
    pix.save(out_path)
    return os.path.getsize(out_path), pix.width, pix.height


def process_subject(subject: str, year: int, questions: list, dry_run: bool, report: dict):
    """處理單一(科,年)PDF。questions = 該年該科的全部題(用來算 group 範圍)。"""
    pdf_path = os.path.join(RAW_DIR, f"{year}_會考{subject}_試題.pdf")
    if not os.path.exists(pdf_path):
        report["missing_pdf"].append(pdf_path)
        return {}

    doc = fitz.open(pdf_path)
    page_anchors = build_page_anchors(doc)
    qid_to_fig = {}

    # 整頁寬單欄(會考題幹單欄;圖文並排時圖在右半,需整頁寬才不切圖)
    def cols(page):
        return SIDE_MARGIN_L, page.rect.width - SIDE_MARGIN_R

    # 目標題(needs_figure)
    targets = [q for q in questions if q.get("needs_figure")]
    indep = [q for q in targets if not q.get("group_id")]
    grouped = defaultdict(list)
    for q in targets:
        if q.get("group_id"):
            grouped[q["group_id"]].append(q)

    # group 範圍用「全部成員」算(忠實:共用同張圖)
    group_all = defaultdict(list)
    for q in questions:
        if q.get("group_id"):
            group_all[q["group_id"]].append(q)

    # ---- 獨立圖題:band = 題號行 -> 下一題號行 ----
    for q in indep:
        no = q["no"]
        loc = find_question_top(page_anchors, no)
        if loc is None:
            report["unlocated"].append((q["qid"], "題號行無法定位"))
            continue
        pno, y0 = loc
        page = doc[pno]
        xL, xR = cols(page)
        y_top = y0 - TOP_PAD
        ny = next_anchor_y(page_anchors, pno, y0)
        ns = next_section_y(page, y0)          # 題組/大題標題(避免吃進題組材料)
        bounds = [b for b in (ny, ns) if b is not None]
        lower = min(bounds) if bounds else None
        hard = (lower - 2) if lower is not None else None
        y_bottom = (lower - 2) if lower is not None else (page_text_bottom(page) + BOTTOM_PAD)
        y_bottom = band_image_bottom(page, y_top, y_bottom, xL, xR, hard)
        y_bottom = clamp_bottom(page, y_bottom + BOTTOM_PAD)
        # 上界保護:右側並排圖頂端常凸出於題號行上方,往上延伸但不越過前一題
        prev_ys = [yy for (n, yy) in page_anchors[pno] if yy < y0 - 2]
        soft_top = (max(prev_ys) + TOP_PAD) if prev_ys else (HEADER_Y - 6)
        y_top = band_image_top(page, y_top, y_bottom, xL, xR, soft_top) - TOP_PAD
        y_top = max(y_top, HEADER_Y - 6)

        fname = f"C{year}_{subject}_q{no}.png"
        qid_to_fig[q["qid"]] = fname
        if not dry_run:
            size, w, h = render_band(page, y_top, y_bottom, xL, xR,
                                     os.path.join(FIG_DIR, fname))
            report["rendered"].append((fname, size, w, h))
        report["bands"].append((q["qid"], fname, pno, round(y_top, 1),
                                round(y_bottom, 1), "indep"))

    # ---- 題組共用材料/圖 ----
    for gid, members in grouped.items():
        allmem = sorted(group_all.get(gid, members), key=lambda m: m["no"])
        nos = [m["no"] for m in allmem]
        first_no, last_no = nos[0], nos[-1]
        fname = f"C{year}_{subject}_g{first_no}_{last_no}.png"

        head = find_group_head(doc, first_no, last_no)
        # 子題第一題的題號行(下界)
        child_loc = find_question_top(page_anchors, first_no)

        if head is not None:
            pno, head_y = head
        elif child_loc is not None:
            # 找不到子標題時,退而用第一子題的題號行上方少量 padding 當上界
            pno, head_y = child_loc
            head_y = head_y - 130.0  # 往上抓 passage/圖區(保守)
        else:
            report["unlocated"].append((gid, "題組標題與子題皆無法定位"))
            continue

        page = doc[pno]
        xL, xR = cols(page)
        y_top = max(head_y - TOP_PAD, HEADER_Y - 6)

        # 預設下界:同頁、head 之後第一個題號行(=passage/共用圖 區塊下緣)
        page_anchor_list = sorted(page_anchors.get(pno, []), key=lambda a: a[1])
        cand = [y for (n, y) in page_anchor_list if y > head_y + 2]
        if cand:
            y_bottom = min(cand) - 2
            hard = min(cand) - 2
        else:
            # 子題落到下一頁:passage/圖佔本頁底部
            y_bottom = page_text_bottom(page) + BOTTOM_PAD
            hard = None

        # 圖在子題(非 passage)的情形:某些國文題組 passage 為純文字,真正的圖
        # (示意圖/計分表/路線圖/圖選項)落在某 needs_figure 子題的題幹旁或選項區。
        # passage 是否「圖佔主導」(海報/插畫/示意圖直接在 passage):
        passage_segs = figure_segment_count(page, y_top, y_bottom, xL, xR)
        passage_is_fig = passage_segs >= PASSAGE_FIG_DOMINANT

        # 逐一檢查同頁 needs_figure 子題,決定是否把下界延伸到該子題之後,
        # 使共用圖含進該子題自帶的圖(忠實呈現該題所需視覺)。觸發條件:
        #   (a) 該子題自身區塊含大量圖線段, 或
        #   (b) passage 非圖主導(純文字題組,圖必在子題), 或
        #   (c) 子題題幹/選項明指自帶圖表(右圖/右表/示意圖/圖選項…)。
        members_by_no = {m["no"]: m for m in members}
        for cno in sorted(members_by_no.keys()):
            cy = next((y for (n, y) in page_anchor_list if n == cno), None)
            if cy is None or cy <= head_y:
                continue
            after = [y for (n, y) in page_anchor_list if y > cy + 2]
            sec_after = next_section_y(page, cy)
            child_bot_cands = list(after) + ([sec_after] if sec_after else [])
            child_bottom = (min(child_bot_cands) if child_bot_cands
                            else (page_text_bottom(page) + BOTTOM_PAD))
            segs = figure_segment_count(page, cy, child_bottom, xL, xR)
            trigger = (segs >= CHILD_FIG_SEG_MIN
                       or not passage_is_fig
                       or child_references_figure(members_by_no[cno]))
            if trigger and child_bottom > y_bottom:
                y_bottom = child_bottom - 2
                hard = child_bottom - 2

        y_bottom = band_image_bottom(page, y_top, y_bottom, xL, xR, hard)
        y_bottom = clamp_bottom(page, y_bottom + BOTTOM_PAD)

        for m in members:   # 只有 needs_figure 的成員指向圖
            qid_to_fig[m["qid"]] = fname
        if not dry_run:
            size, w, h = render_band(page, y_top, y_bottom, xL, xR,
                                     os.path.join(FIG_DIR, fname))
            report["rendered"].append((fname, size, w, h))
        report["bands"].append((gid, fname, pno, round(y_top, 1),
                                round(y_bottom, 1), f"group({len(members)}題)"))

    doc.close()
    return qid_to_fig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只算 band 與印報告,不存圖、不寫 staging")
    args = ap.parse_args()

    report = {"rendered": [], "bands": [], "unlocated": [], "missing_pdf": []}

    if not args.dry_run:
        os.makedirs(FIG_DIR, exist_ok=True)
        # 冪等:只清除本次負責科目的 C 開頭舊圖
        for fn in os.listdir(FIG_DIR):
            if not fn.lower().endswith(".png"):
                continue
            if any(fn.startswith(f"C{y}_{s}_") for y in YEARS for s in SUBJECTS):
                os.remove(os.path.join(FIG_DIR, fn))

    for subject in SUBJECTS:
        stage_path = os.path.join(STAGE_DIR, f"cap_{subject}.json")
        with open(stage_path, encoding="utf-8") as f:
            data = json.load(f)

        by_year = defaultdict(list)
        for q in data:
            by_year[q["year"]].append(q)

        qid_to_fig = {}
        for year in sorted(by_year.keys()):
            mapping = process_subject(subject, year, by_year[year],
                                      args.dry_run, report)
            qid_to_fig.update(mapping)

        if not args.dry_run:
            for q in data:
                if q["qid"] in qid_to_fig:
                    q["figure"] = qid_to_fig[q["qid"]]
            with open(stage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)

    # ---- 報告(純文字)----
    print("=" * 60)
    print("會考圖題萃取報告")
    print("=" * 60)
    total_targets = 0
    for subject in SUBJECTS:
        with open(os.path.join(STAGE_DIR, f"cap_{subject}.json"), encoding="utf-8") as f:
            d = json.load(f)
        nf = sum(1 for q in d if q.get("needs_figure"))
        total_targets += nf
        print(f"  {subject}: needs_figure 題數 = {nf}")
    print(f"目標題合計            : {total_targets}")
    print(f"產出 PNG 檔數         : {len(report['rendered'])}")
    if report["rendered"]:
        tot = sum(r[1] for r in report["rendered"])
        print(f"figures 總大小        : {tot/1024/1024:.2f} MB ({tot} bytes)")
        print(f"平均單張              : {tot/len(report['rendered'])/1024:.1f} KB")

    by_kind = defaultdict(int)
    for (_, fname, _, _, _, kind) in report["bands"]:
        by_kind[kind.split("(")[0]] += 1
    print("\nband 類型分布:", dict(by_kind))

    if report["unlocated"]:
        print(f"\n★ 無法定位 ({len(report['unlocated'])}):")
        for r in report["unlocated"]:
            print("   ", r)
    if report["missing_pdf"]:
        print(f"\n★ 缺 PDF: {report['missing_pdf']}")

    heights = [(fname, round(y1 - y0, 1), kind)
               for (_, fname, _, y0, y1, kind) in report["bands"]]
    short = [h for h in heights if h[1] < 60]
    tall = [h for h in heights if h[1] > 740]
    if short:
        print(f"\n△ band 偏矮(<60pt,留意切圖) {len(short)}:")
        for h in short:
            print("   ", h)
    if tall:
        print(f"\n△ band 偏高(>740pt,留意含到別題) {len(tall)}:")
        for h in tall:
            print("   ", h)

    print("\n完成。", "（dry-run,未寫檔）" if args.dry_run
          else f"figures 目錄: {FIG_DIR}")


if __name__ == "__main__":
    sys.exit(main())
