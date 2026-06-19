# -*- coding: utf-8 -*-
"""
extract_figures.py — 學測「需要圖」題目版面區塊萃取器

目的
----
把 data/bank.json 中 exam=='學測' 且 needs_figure==True 的題目,所在的原卷
PDF 版面區塊(band)render 成乾淨 PNG,存到 data/figures/,供單檔離線 HTML
內嵌顯示。忠實重現原卷(不簡化、不重排)。

安全規則(最高優先)
------------------
- 圖一律存成獨立二進位 PNG 檔。本腳本「只」印出:張數、位元組大小、檔名、
  qid 清單、座標數字。絕不 print 圖片 bytes / base64 / data URL。
- bank.json 只寫入檔名字串(figure 欄),永不寫 base64,保持純文字可 lint。

定位策略(穩健性關鍵)
--------------------
逐頁建立「正規化字元索引」:把每個非空白字元對應到其所屬 text span 的 bbox。
用題目 stem 的正規化前綴在頁內定位 y 座標。重點:
- 用「長前綴(優先 30→10 字)+ 該前綴在頁內唯一」來避免題號數字或短字串
  撞題(短前綴會誤配到別題),長前綴對不上時才放寬到 6 字。
- 題組共用圖/材料:用「N-M為題組」這個題組標記當主錨點(文字短、固定、
  在 passage 區上緣),比 passage 全文比對可靠得多(passage 經 markitdown
  重排後字序與 PDF span 不一致,且常含 ◎/圖說/數字而比對失敗)。

band(render 區塊)決定
---------------------
- 獨立圖題(無 group_id)、英文圖選項題:
    上界 = 該題 stem 起點(往上含題號,留 padding)
    下界 = 同頁「下一個學測題目」起點;若為頁面最後一題則到頁尾(扣頁碼);
           再對「band 內圖片/向量圖底部」取 max,確保圖不被切半張。
- 題組共用材料/圖(社會、國綜,有 group_id):
    用「N-M為題組」錨點定位 passage 所在頁與上界:
    上界 = 題組標記 y(往上少量 padding)
    下界 = 同頁、標記之後第一個子題 stem 的 y;若無子題在同頁(passage 獨佔
           該頁底部、子題落到下一頁)則到頁尾;再對圖片底部取 max。
    一個 group 只 render 一張,該 group 內「所有目標子題」的 figure 欄都指向
    這張(忠實:共用同一張圖)。

檔名規則
--------
- 獨立題 : {簡碼}{year}_q{no}.png        例 S114_q24.png
- 題組   : {簡碼}{year}_g{首題no}_{末題no}.png  例 S114_g31_32.png、G115_g14_15.png
簡碼:社會 S、國綜 G、英文 E。格式跨科一致、含年份與科目。

寬度:社會/英文/國綜 經探勘均為單欄(所有題 stem x0 一致 ~64-82),band 取
整頁寬(扣左右白邊)。detect_columns 保留雙欄擴充能力。

冪等:每次重建 data/figures/(清空再產),figure 欄以重算後的對應覆蓋寫入。

用法
----
    uv run --with pymupdf python scripts/extract_figures.py
    uv run --with pymupdf python scripts/extract_figures.py --dry-run   # 只報告不寫檔
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
BANK_PATH = os.path.join(ROOT, "data", "bank.json")
RAW_DIR = os.path.join(ROOT, "data", "raw")
FIG_DIR = os.path.join(ROOT, "data", "figures")

# ---- render 參數 ----
ZOOM = 2.2
MATRIX = fitz.Matrix(ZOOM, ZOOM)

# ---- band 邊界微調(point,72dpi)----
TOP_PAD = 6.0
BOTTOM_PAD = 5.0
HEADER_Y = 78.0                  # 頁眉下緣(頁眉約 y<70);band 上界不高於此
FOOTER_Y_MARGIN = 30.0           # 頁尾頁碼「- N -」約 y>780
SIDE_MARGIN_L = 44.0
SIDE_MARGIN_R = 12.0

# 定位前綴長度
PREFIX_MAX = 30
PREFIX_MIN_STRICT = 10           # 先試 30→10 且要求唯一
PREFIX_MIN_LOOSE = 6             # 放寬到 6,不要求唯一

SUBJ_CODE = {"社會": "S", "國綜": "G", "英文": "E", "自然": "N"}


def norm(s):
    return re.sub(r"\s+", "", s or "")


def safe_name(s):
    return re.sub(r"[^0-9A-Za-z_一-鿿]+", "_", s).strip("_")


def build_char_index(page):
    """頁面正規化字元索引:normtext[i] 對應 metas[i]=span bbox。"""
    d = page.get_text("dict")
    chars, metas = [], []
    for block in d["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                bbox = span["bbox"]
                for ch in span["text"]:
                    if ch.strip() == "":
                        continue
                    chars.append(ch)
                    metas.append(bbox)
    return "".join(chars), metas


def locate_text(normtext, metas, text):
    """
    用 text 正規化前綴在 normtext 定位,回傳 (idx, bbox) 或 None。
    先試長前綴(30→10)且要求唯一;再放寬(30→6,取第一個命中)。
    """
    nt = norm(text)
    if not nt:
        return None
    # 階段一:長前綴 + 唯一
    for L in range(min(PREFIX_MAX, len(nt)), PREFIX_MIN_STRICT - 1, -1):
        p = nt[:L]
        idx = normtext.find(p)
        if idx >= 0 and normtext.find(p, idx + 1) < 0:
            return idx, metas[idx]
    # 階段二:放寬,不要求唯一(取第一個)
    for L in range(min(PREFIX_MAX, len(nt)), PREFIX_MIN_LOOSE - 1, -1):
        p = nt[:L]
        idx = normtext.find(p)
        if idx >= 0:
            return idx, metas[idx]
    return None


def locate_text_fragments(normtext, metas, text, frag=12):
    """
    前綴定位失敗時的 fallback:把 text 切成多個 frag 字片段,任一片段命中即可。
    回傳該頁中所有命中片段的「最小 y」對應 bbox(最接近題目開頭),或 None。
    用於 bank 中 stem 開頭被解析器截斷的題(如 115_社會_22)。
    """
    nt = norm(text)
    if len(nt) < frag:
        return None
    best = None
    step = max(1, frag // 2)
    for start in range(0, len(nt) - frag + 1, step):
        p = nt[start:start + frag]
        idx = normtext.find(p)
        if idx >= 0:
            bbox = metas[idx]
            if best is None or bbox[1] < best[1]:
                best = bbox
    return (None, best) if best else None


def page_text_bottom(page):
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


def detect_columns(page):
    """
    回傳 band 寬度(欄)。社會/英文/國綜的題幹皆為單欄佈局,且題組材料常為
    「文字左、圖右」的圖文並排——若依文字 x0 切欄會把右側的圖切掉(實測
    111_社會_g59_60 圖11 在右半,誤切)。故一律回傳整頁寬單欄,確保圖完整。
    保留此函式作為單一寬度決策點(日後若真遇到雙欄題卷可在此擴充)。
    """
    w = page.rect.width
    return [(SIDE_MARGIN_L, w - SIDE_MARGIN_R)]


def band_image_bottom(page, y0, y1, xL, xR, hard_limit):
    """
    band 內圖片(raster)+向量圖最低 y1,用來防止圖被下界切掉。
    - 只考慮「圖頂落在 band 內」(y0-2 <= r.y0 <= y1+SLACK)的圖,代表該圖屬於
      本題且可能被下界切到。
    - 延伸後的下界絕不超過 hard_limit(下一題起點),避免吃進下一題的圖。
    找不到需延伸的圖則回傳原 y1。
    """
    SLACK = 24.0  # 圖頂略低於下界一點(被切到)時才納入;不可太大以免吃下一題
    cap = hard_limit if hard_limit is not None else (page.rect.height - FOOTER_Y_MARGIN)
    bottom = y1

    def consider(r):
        nonlocal bottom
        if r.x1 < xL or r.x0 > xR:
            return
        # 整頁框線(向量)排除
        if (r.y1 - r.y0) > page.rect.height * 0.85:
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


def clamp_bottom(page, bottom):
    return min(bottom, page.rect.height - FOOTER_Y_MARGIN)


def render_band(page, y0, y1, xL, xR, out_path):
    y0 = max(y0, HEADER_Y - 6)
    clip = fitz.Rect(xL, y0, xR, y1)
    pix = page.get_pixmap(matrix=MATRIX, clip=clip)
    pix.save(out_path)
    return os.path.getsize(out_path), pix.width, pix.height


def locate_all_questions(doc, questions):
    """
    定位一份 PDF 內全部學測題目的 stem 起點。
    回傳 (tops: qid->(pno,bbox), page_index: list of (normtext,metas))。
    """
    page_index = [build_char_index(doc[p]) for p in range(len(doc))]
    tops = {}
    for q in questions:
        located = None
        for pno in range(len(doc)):
            nt, metas = page_index[pno]
            hit = locate_text(nt, metas, q["stem"])
            if hit:
                located = (pno, hit[1])
                break
        if located is None:
            # fallback:片段掃描(處理 bank stem 開頭被截斷的題)
            for pno in range(len(doc)):
                nt, metas = page_index[pno]
                hit = locate_text_fragments(nt, metas, q["stem"])
                if hit:
                    bbox = hit[1]
                    # 往上吸附到同頁最近的題號「no.」起點,使 band 含題號
                    y = snap_to_question_number(page_index[pno][0],
                                                page_index[pno][1],
                                                q["no"], bbox[1])
                    if y is not None:
                        bbox = (bbox[0], y, bbox[2], bbox[3])
                    located = (pno, bbox)
                    break
        if located is not None:
            tops[q["qid"]] = located
    return tops, page_index


def snap_to_question_number(normtext, metas, no, y_hint):
    """
    在 normtext 找題號「{no}.」且 y <= y_hint+2 的最近位置,回傳其 y。
    用於 fallback 定位後把上界吸附到題號行。找不到回 None。
    """
    pat = f"{no}."
    best = None
    start = 0
    while True:
        idx = normtext.find(pat, start)
        if idx < 0:
            break
        y = metas[idx][1]
        if y <= y_hint + 2:
            if best is None or y > best:   # 取 <=y_hint 中最大(最接近題目)
                best = y
        start = idx + 1
    return best


def find_group_mark(page_index, nos):
    """
    在整份 PDF 找題組標記「N-M為題組」。回傳 (pno, y, normtext, metas) 或 None。
    nos = 該題組成員題號(已排序)。
    """
    # 社會用「N-M為題組」;自然用「N-M題為題組」(數字與「為題組」間多一個「題」)。
    # 兩種變體都列入(各種分隔符 × 有無「題」)。
    pats = [f"{nos[0]}{sep}{nos[-1]}{mid}為題組"
            for sep in ("-", "－", "~", "～", "–", "至")
            for mid in ("", "題")]
    for pno, (nt, metas) in enumerate(page_index):
        for pat in pats:
            idx = nt.find(norm(pat))
            if idx >= 0:
                return pno, metas[idx][1], nt, metas
    return None


def process_pdf(year, subject, targets_all, all_questions, dry_run, report):
    pdf_path = os.path.join(RAW_DIR, f"{year}_{subject}_試題.pdf")
    if not os.path.exists(pdf_path):
        report["missing_pdf"].append(pdf_path)
        return {}

    doc = fitz.open(pdf_path)
    tops, page_index = locate_all_questions(doc, all_questions)
    code = SUBJ_CODE.get(subject, subject)
    qid_to_fig = {}

    # 同頁題目起點排序(找下一題用)
    tops_by_page = defaultdict(list)
    for qid, (pno, bbox) in tops.items():
        tops_by_page[pno].append((bbox[1], bbox[0], qid))
    for pno in tops_by_page:
        tops_by_page[pno].sort()

    indep = [q for q in targets_all if not q.get("group_id")]
    grouped = defaultdict(list)
    for q in targets_all:
        if q.get("group_id"):
            grouped[q["group_id"]].append(q)

    def next_question_y(pno, cur_bbox, cur_qid, cols):
        """同頁、同欄、y 大於本題的下一題起點;無則 None。"""
        x_start = cur_bbox[0]
        for (yy, xx, oqid) in tops_by_page[pno]:
            if oqid == cur_qid or yy <= cur_bbox[1] + 2:
                continue
            if len(cols) == 1 or abs(xx - x_start) < 40:
                return yy
        return None

    def pick_col(cols, x_start):
        for (cl, cr) in cols:
            if cl - 10 <= x_start <= cr:
                return cl, cr
        return cols[0]

    # ---- 獨立圖題(含英文圖選項題)----
    for q in indep:
        qid = q["qid"]
        if qid not in tops:
            report["unlocated"].append((qid, "stem 無法定位"))
            continue
        pno, bbox = tops[qid]
        page = doc[pno]
        cols = detect_columns(page)
        xL, xR = pick_col(cols, bbox[0])
        y_top = bbox[1] - TOP_PAD
        ny = next_question_y(pno, bbox, qid, cols)
        # 圖底保護的硬上限 = 下一題起點(無則頁尾),確保不吃進下一題的圖
        hard = (ny - 2) if ny is not None else None
        y_bottom = (ny - 2) if ny is not None else (page_text_bottom(page) + BOTTOM_PAD)
        y_bottom = band_image_bottom(page, y_top, y_bottom, xL, xR, hard)
        y_bottom = clamp_bottom(page, y_bottom + BOTTOM_PAD)

        fname = f"{code}{year}_q{q['no']}.png"
        qid_to_fig[qid] = fname
        if not dry_run:
            size, w, h = render_band(page, y_top, y_bottom, xL, xR,
                                     os.path.join(FIG_DIR, fname))
            report["rendered"].append((fname, size, w, h))
        report["bands"].append((qid, fname, pno, round(y_top, 1),
                                round(y_bottom, 1), "indep"))

    # ---- 題組共用材料/圖 ----
    for gid, members in grouped.items():
        members_sorted = sorted(members, key=lambda m: m["no"])
        group_all = sorted([x for x in all_questions if x.get("group_id") == gid],
                           key=lambda m: m["no"])
        nos = [m["no"] for m in group_all] or [m["no"] for m in members_sorted]

        is_english = subject == "英文"
        # 檔名統一用「簡碼+年份+題號區間」(g{首}_{末}),格式跨科一致、含年份科目,
        # 不沿用 group_id(社會 group_id 含中文與年份前綴會與簡碼/年份重複)。
        fname = f"{code}{year}_g{nos[0]}_{nos[-1]}.png"

        if is_english:
            # 英文題組:圖在「Which picture」子題的選項區,非 passage 上方。
            # 找含圖的子題(needs_figure 的成員),逐一當獨立圖處理,但共用檔名:
            # 取第一個 needs_figure 成員的 stem→下一題 區塊。
            fig_member = next((m for m in members_sorted if m["needs_figure"]),
                              members_sorted[0])
            qid = fig_member["qid"]
            if qid not in tops:
                report["unlocated"].append((gid, "英文圖子題無法定位"))
                doc_close_safe(doc)
                continue
            pno, bbox = tops[qid]
            page = doc[pno]
            cols = detect_columns(page)
            xL, xR = pick_col(cols, bbox[0])
            y_top = bbox[1] - TOP_PAD
            ny = next_question_y(pno, bbox, qid, cols)
            hard = (ny - 2) if ny is not None else None
            y_bottom = (ny - 2) if ny is not None else (page_text_bottom(page) + BOTTOM_PAD)
            y_bottom = band_image_bottom(page, y_top, y_bottom, xL, xR, hard)
            y_bottom = clamp_bottom(page, y_bottom + BOTTOM_PAD)
            for m in members_sorted:
                if m["needs_figure"]:
                    qid_to_fig[m["qid"]] = fname
            if not dry_run:
                size, w, h = render_band(page, y_top, y_bottom, xL, xR,
                                         os.path.join(FIG_DIR, fname))
                report["rendered"].append((fname, size, w, h))
            report["bands"].append((gid, fname, pno, round(y_top, 1),
                                    round(y_bottom, 1), "eng-group"))
            continue

        # 社會/國綜題組:用「N-M為題組」錨點
        mk = find_group_mark(page_index, nos)
        if mk is None:
            report["unlocated"].append((gid, "題組標記找不到"))
            continue
        pno, mark_y, nt, metas = mk
        page = doc[pno]
        cols = detect_columns(page)
        xL, xR = cols[0]  # 題組材料多為整頁寬單欄
        y_top = mark_y - TOP_PAD

        # 下界:同頁、標記之後第一個子題起點
        first_child_y = None
        cand = []
        for (yy, xx, oqid) in tops_by_page.get(pno, []):
            if yy > mark_y + 2:
                cand.append(yy)
        if cand:
            first_child_y = min(cand)
        if first_child_y is not None:
            y_bottom = first_child_y - 2
            hard = first_child_y - 2
        else:
            # 子題在下一頁:passage/圖 佔到本頁尾
            y_bottom = page_text_bottom(page) + BOTTOM_PAD
            hard = None
        y_bottom = band_image_bottom(page, y_top, y_bottom, xL, xR, hard)
        y_bottom = clamp_bottom(page, y_bottom + BOTTOM_PAD)

        for m in members_sorted:
            qid_to_fig[m["qid"]] = fname
        if not dry_run:
            size, w, h = render_band(page, y_top, y_bottom, xL, xR,
                                     os.path.join(FIG_DIR, fname))
            report["rendered"].append((fname, size, w, h))
        report["bands"].append((gid, fname, pno, round(y_top, 1),
                                round(y_bottom, 1),
                                f"group({len(members_sorted)}題)"))

    doc.close()
    return qid_to_fig


def doc_close_safe(doc):
    try:
        doc.close()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只計算 band 與印報告,不存圖、不寫 bank.json")
    args = ap.parse_args()

    with open(BANK_PATH, encoding="utf-8") as f:
        bank = json.load(f)
    questions = bank["questions"]

    targets = [q for q in questions
               if q.get("exam") == "學測" and q.get("needs_figure")]

    targets_by_pdf = defaultdict(list)
    all_by_pdf = defaultdict(list)
    for q in questions:
        if q.get("exam") == "學測":
            all_by_pdf[(q["year"], q["subject"])].append(q)
    for q in targets:
        targets_by_pdf[(q["year"], q["subject"])].append(q)

    report = {
        "rendered": [], "bands": [], "unlocated": [], "missing_pdf": [],
    }

    if not args.dry_run:
        os.makedirs(FIG_DIR, exist_ok=True)
        # 只清本腳本要重建的「學測科目簡碼」開頭 PNG(S/G/E/N…);
        # 絕不動會考(C 開頭)或其他來源的圖 —— 否則會誤刪已上線的會考/數學圖。
        _gsat_codes = tuple(SUBJ_CODE.values())
        for fn in os.listdir(FIG_DIR):
            if fn.lower().endswith(".png") and fn.startswith(_gsat_codes):
                os.remove(os.path.join(FIG_DIR, fn))

    qid_to_fig = {}
    for (year, subject) in sorted(targets_by_pdf.keys()):
        mapping = process_pdf(year, subject,
                              targets_by_pdf[(year, subject)],
                              all_by_pdf[(year, subject)],
                              args.dry_run, report)
        qid_to_fig.update(mapping)

    if not args.dry_run:
        for q in questions:
            if q["qid"] in qid_to_fig:
                q["figure"] = qid_to_fig[q["qid"]]
        with open(BANK_PATH, "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False, indent=1)

    # ---- 報告(純文字)----
    print("=" * 60)
    print("圖題萃取報告")
    print("=" * 60)
    print(f"目標題(學測 needs_figure): {len(targets)}")
    print(f"成功對應 figure 的題數    : {len(qid_to_fig)} / {len(targets)}")
    print(f"產出 PNG 檔數              : {len(report['rendered'])}")
    if report["rendered"]:
        total = sum(r[1] for r in report["rendered"])
        print(f"figures 總大小            : {total/1024/1024:.2f} MB ({total} bytes)")
        print(f"平均單張                  : {total/len(report['rendered'])/1024:.1f} KB")

    by_ys = defaultdict(int)
    for (qid, fname, pno, y0, y1, kind) in report["bands"]:
        m = re.match(r"([SGE])(\d{3})_", fname)
        if m:
            by_ys[(m.group(2), m.group(1))] += 1
    print("\n各(年份,科目簡碼)張數:")
    for k in sorted(by_ys):
        print(f"   {k[0]} {k[1]}: {by_ys[k]}")

    if report["unlocated"]:
        print(f"\n★ 無法定位 ({len(report['unlocated'])}):")
        for r in report["unlocated"]:
            print("   ", r)
    if report["missing_pdf"]:
        print(f"\n★ 缺 PDF: {report['missing_pdf']}")

    heights = [(fname, round(y1 - y0, 1), kind)
               for (qid, fname, pno, y0, y1, kind) in report["bands"]]
    short = [h for h in heights if h[1] < 70]
    tall = [h for h in heights if h[1] > 730]
    if short:
        print(f"\n△ band 偏矮(<70pt,留意是否切圖) {len(short)}:")
        for h in short:
            print("   ", h)
    if tall:
        print(f"\n△ band 偏高(>730pt,留意是否含到別題) {len(tall)}:")
        for h in tall:
            print("   ", h)

    print("\n完成。", "（dry-run,未寫檔）" if args.dry_run
          else f"figures 目錄: {FIG_DIR}")


if __name__ == "__main__":
    sys.exit(main())
