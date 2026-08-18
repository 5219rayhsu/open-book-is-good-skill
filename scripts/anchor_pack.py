#!/usr/bin/env python3
"""Build and use an offline statutory-text anchor pack for exam explanations.

The scraper intentionally depends only on the visible text of the official
``LawAll.aspx`` page.  That is less coupled to CSS/class names than a selector-
based scraper while still using :class:`html.parser.HTMLParser` as required.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={}"
SCRIPT_DIR = Path(__file__).resolve().parent
HTTP_TIMEOUT_SECONDS = 30
HTTP_ATTEMPTS = 3
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Pcodes are stable identifiers looked up once from the official database.
EXAM_LAWS: dict[str, tuple[tuple[str, str], ...]] = {
    "social-worker": (
        ("社會工作師法", "D0050125"),
        ("社會救助法", "D0050078"),
        ("老人福利法", "D0050037"),
        ("身心障礙者權益保障法", "D0050046"),
        ("兒童及少年福利與權益保障法", "D0050001"),
        ("性別平等工作法", "N0030014"),
        ("家庭暴力防治法", "D0050071"),
        ("精神衛生法", "L0020030"),
        ("長期照顧服務法", "L0070040"),
        ("國民年金法", "D0050152"),
    ),
    "lawyer": (
        ("中華民國憲法增修條文", "A0000002"),
        ("中華民國憲法", "A0000001"),
        ("中華民國刑法", "C0000001"),
        ("民法", "B0000001"),
        ("民事訴訟法", "B0010001"),
        ("刑事訴訟法", "C0010001"),
        ("行政程序法", "A0030055"),
        ("行政訴訟法", "A0030154"),
        ("公司法", "J0080001"),
        ("證券交易法", "G0400001"),
        ("律師法", "I0020006"),
        ("強制執行法", "B0010004"),
        # B0010049 是「家事事件書狀規則」（僅 9 條），不是家事事件法——舊值誤填，
        # 導致 --verify 把 34 筆正確的家事事件法引用誤判成 fail。2026-07-23 以頁標題回讀更正。
        ("家事事件法", "B0010048"),
        ("憲法訴訟法", "A0030159"),
        ("票據法", "G0380028"),
    ),
    # cpa 只有「稅務法規」會引法條（實測 94 處引用集中於此科；審計學／中級會計學的
    # 「權益法／加權平均法／測試資料法」是方法名不是法規，無從錨定）。pcode 皆以
    # LawAll 頁標題回讀二次確認，未憑記憶填入。
    "cpa": (
        ("所得稅法", "G0340003"),
        ("稅捐稽徵法", "G0340001"),
        ("加值型及非加值型營業稅法", "G0340080"),
        ("遺產及贈與稅法", "G0340072"),
        ("土地稅法", "G0340096"),
        ("所得基本稅額條例", "G0340115"),
        ("納稅者權利保護法", "G0340142"),
    ),
}

# 執行期依 --exam 切換（預設 social-worker，selftest 用）。
CURRENT_EXAM = "social-worker"
CORE_LAWS: tuple[tuple[str, str], ...] = EXAM_LAWS[CURRENT_EXAM]
LAW_NAMES = tuple(name for name, _ in CORE_LAWS)
PACK_PATH = SCRIPT_DIR / "anchor_packs" / (CURRENT_EXAM + ".json")


def setExam(exam: str) -> None:
    global CURRENT_EXAM, CORE_LAWS, LAW_NAMES, PACK_PATH
    CURRENT_EXAM = exam
    CORE_LAWS = EXAM_LAWS[exam]
    LAW_NAMES = tuple(name for name, _ in CORE_LAWS)
    PACK_PATH = SCRIPT_DIR / "anchor_packs" / (exam + ".json")
ARTICLE_HEADING_RE = re.compile(
    r"(?m)^第\s*([0-9０-９]+(?:\s*[-－]\s*[0-9０-９]+)?)\s*條\s*$"
)
AMEND_DATE_RE = re.compile(
    r"修正日期\s*[:：]\s*民國\s*([0-9０-９]+)\s*年\s*"
    r"([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日"
)
CHINESE_NUMBER_CHARS = "零〇一二兩三四五六七八九十百千萬億"
CHINESE_NUMBER_RE = re.compile(f"[{CHINESE_NUMBER_CHARS}]+")
ARTICLE_NUMBER_TOKEN = rf"(?:[0-9０-９]+|[{CHINESE_NUMBER_CHARS}]+)"
ARTICLE_REF_RE = re.compile(
    # 兩種子條寫法都要吃：「第26條之1」（之／- 在條之後）與「第26-1條」（- 在條之前）。
    # 只支援後綴式時，「第26-1條」會在 26 處匹配失敗、往後吃到下一個法的條號（實證：
    # 「證交法第26-1條規定，公司法第209條」→ 證交法被標成第209條）。
    rf"第\s*({ARTICLE_NUMBER_TOKEN})"
    rf"(?:\s*(?:之|[-－])\s*({ARTICLE_NUMBER_TOKEN}))?\s*條"
    rf"(?:\s*(?:之|[-－])\s*({ARTICLE_NUMBER_TOKEN}))?"
)
# 法名後若緊接其他漢字（「票據法律關係」「公司法人」「所得稅法施行細則」），代表那是更長的
# 詞或另一部法，不是本法的引用；只有「第」（第N條）或非漢字才算真引用邊界。
LAW_NAME_TAIL_OK = re.compile(r"^(?:第|[^一-鿿]|$)")
# 「條之N」不一定是子條號——「之」也可能是「的」：
#   第22條之3年時效  ＝ 第22條「的」3年時效（不是第22-3條）
#   第305條之兩造同意 ＝ 第305條「的」兩造同意（「兩」還剛好是中文數字）
# 子條號後面接的若是單位／名詞字，就把它還原成單純的第N條。
SUBARTICLE_FALSE_TAIL = re.compile(r"^\s*[年月日項款目時分秒人元造次種類件筆倍成天週歲條]")
KEY_NUMBER_RE = re.compile(
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>億|萬|千)?\s*(?P<unit>日|天|年|歲|元|個月|月)"
)


class AnchorPackError(RuntimeError):
    """An expected, user-facing failure while fetching or processing a pack."""


class VisibleTextParser(HTMLParser):
    """Collect visible HTML text without relying on the site's CSS classes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignoredDepth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignoredDepth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._ignoredDepth:
            self._ignoredDepth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignoredDepth:
            return
        cleaned = re.sub(r"[\t\r\f\v ]+", " ", data).strip()
        if cleaned:
            self._chunks.append(cleaned)

    def text(self) -> str:
        return "\n".join(self._chunks)


@dataclass(frozen=True)
class Citation:
    law: str
    art: str
    start: int
    end: int


def curlArgv(url: str) -> list[str]:
    # ponytail: -4 because law.moj.gov.tw 的 AAAA 位址無回應（IPv6 逾時）；
    # 不加 -k——該站憑證缺 Subject Key Identifier，OpenSSL 3 拒收但系統信任鏈接受，
    # 驗證仍然開著。
    return [
        "curl",
        "-sS",
        "-4",
        "-L",
        "--fail",
        "--max-time",
        str(HTTP_TIMEOUT_SECONDS),
        "-A",
        BROWSER_USER_AGENT,
        "-H",
        "Accept-Language: zh-TW,zh;q=0.9",
        url,
    ]


def fetchViaCurl(url: str) -> str:
    completed = subprocess.run(
        curlArgv(url),
        capture_output=True,
        timeout=HTTP_TIMEOUT_SECONDS + 10,
    )
    if completed.returncode != 0:
        raise OSError(
            f"curl exit {completed.returncode}: "
            f"{completed.stderr.decode('utf-8', 'replace').strip()}"
        )
    return completed.stdout.decode("utf-8", errors="strict")


def fetchViaUrllib(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "anchor-pack/1.0 (+stdlib urllib; exam reference builder)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-TW,zh;q=0.9",
        },
    )
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        payload = response.read()
    return payload.decode(charset, errors="strict")


def fetchHtml(url: str) -> str:
    # curl 先行：政府站憑證／IPv6 常讓 urllib 直接死（見 curlArgv 註解），
    # urllib 保留為 curl 不在時的後備。
    lastError: Exception | None = None
    for attempt in range(1, HTTP_ATTEMPTS + 1):
        for transport in (fetchViaCurl, fetchViaUrllib):
            try:
                return transport(url)
            except (
                HTTPError,
                URLError,
                TimeoutError,
                UnicodeError,
                OSError,
                subprocess.SubprocessError,
            ) as exc:
                lastError = exc
        if attempt < HTTP_ATTEMPTS:
            time.sleep(0.5 * attempt)
    raise AnchorPackError(
        f"network fetch failed after {HTTP_ATTEMPTS} attempts: {url}: {lastError}"
    )


def visibleText(html: str) -> str:
    parser = VisibleTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise AnchorPackError(f"invalid HTML from official site: {exc}") from exc
    return parser.text()


def normalizeArticleNumber(major: str, minor: str | None = None) -> str:
    combined = unicodedata.normalize("NFKC", major).replace(" ", "")
    if minor is None and "-" in combined:
        major, minor = combined.split("-", 1)
    normalizedMajor = numeralTokenToAscii(major)
    if not minor:
        return normalizedMajor
    return f"{normalizedMajor}-{numeralTokenToAscii(minor)}"


def parseLawPage(html: str, expectedName: str, pcode: str) -> dict[str, Any]:
    text = visibleText(html)
    compactText = re.sub(r"\s+", " ", text)
    if expectedName not in compactText:
        raise AnchorPackError(
            f"official page for {pcode} did not contain expected law name {expectedName}"
        )

    dateMatch = AMEND_DATE_RE.search(compactText)
    if not dateMatch:
        
        # 憲法本文從未「修正」,官方頁只有「公布日期」——fallback 用公布日期當版本戳記。
        pubMatch = re.search(r"公布日期\s*[:：]\s*民國\s*([0-9０-９]+)\s*年\s*([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日", compactText)
        if not pubMatch:
            raise AnchorPackError(f"could not find amendment date for {expectedName} ({pcode})")
        dateMatch = pubMatch
    rocYear, month, day = (int(unicodedata.normalize("NFKC", value)) for value in dateMatch.groups())
    amendDate = f"{rocYear + 1911:04d}-{month:02d}-{day:02d}"

    # The official headings use Arabic digits.  Body cross-references use
    # Chinese numerals, so anchoring at line-level Arabic headings avoids false
    # splits without coupling the parser to the current DOM class names.
    normalizedText = unicodedata.normalize("NFKC", text)
    matches = list(ARTICLE_HEADING_RE.finditer(normalizedText))
    if not matches:
        raise AnchorPackError(f"could not find article headings for {expectedName} ({pcode})")

    articles: dict[str, str] = {}
    footerMarkers = ("最新訊息", "本網站係提供法規之最新動態資訊", "法治宣導專區")
    for index, match in enumerate(matches):
        bodyEnd = matches[index + 1].start() if index + 1 < len(matches) else len(normalizedText)
        body = normalizedText[match.end() : bodyEnd].strip()
        if index + 1 == len(matches):
            markerPositions = [body.find(marker) for marker in footerMarkers if marker in body]
            if markerPositions:
                body = body[: min(markerPositions)].strip()
        body = cleanArticleBody(body)
        articleNumber = normalizeArticleNumber(match.group(1).replace(" ", ""))
        if not body:
            raise AnchorPackError(
                f"article {articleNumber} had empty text for {expectedName} ({pcode})"
            )
        if articleNumber in articles:
            raise AnchorPackError(
                f"duplicate article heading {articleNumber} for {expectedName} ({pcode})"
            )
        articles = {**articles, articleNumber: body}

    return {"pcode": pcode, "amend_date": amendDate, "articles": articles}


def cleanArticleBody(body: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in body.splitlines()]
    meaningful = [line for line in lines if line]
    while meaningful and re.fullmatch(r"第\s*[一二三四五六七八九十百]+\s*章(?:\s+.*)?", meaningful[-1]):
        meaningful = meaningful[:-1]
    return "\n".join(meaningful).strip()


def fetchLaw(name: str, pcode: str) -> dict[str, Any]:
    url = BASE_URL.format(pcode)
    try:
        return parseLawPage(fetchHtml(url), name, pcode)
    except AnchorPackError as exc:
        raise AnchorPackError(f"{name} ({pcode}): {exc}") from exc


def atomicWriteJson(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporaryName = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporaryPath = Path(temporaryName)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporaryPath, path)
    except Exception:
        if temporaryPath.exists():
            temporaryPath.unlink()
        raise


def loadPack(path: Path | None = None) -> dict[str, Any]:
    path = path if path is not None else PACK_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AnchorPackError(f"anchor pack not found: {path}; run --build first") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnchorPackError(f"could not read valid anchor pack {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise AnchorPackError(f"anchor pack root must be an object: {path}")
    return raw


def buildPack() -> int:
    """從法務部 Open API 的 bulk dump 重建 anchor pack（2026-08-18 起）。

    ⚠️ **`--build` 走 dump，`--check` 仍走即時網頁**，這個分工是刻意的：

    - `--build` 要的是**正確的全文**。舊的逐部爬 HTML 路徑實測有三種文字毀損：
      6,530/6,989 條（93%）的全形標點被 `parseLawPage` 的 NFKC 壓成半形；
      32 條（每一部法的最後一條，一部不漏）尾端黏著網站的跳過導覽記號 `:::`；
      325 條尾端黏著下一個「節／編」標題（`cleanArticleBody` 只剝「第X章」）。
      也就是說，紅隊拿來查證法源的那份「官方條文」從來就不是官方條文。
    - `--check` 要的是**最新**。dump 每週五更新、資料整編有截止日，實測落後現行公布
      約 7–14 天；拿它回答「有沒有過期」等於用可能落後兩週的資料判斷新不新。
      而且 `--check` 每月實跑一次抓頁＋解析全鏈路，順帶當「爬蟲沒被改版打壞」的探針。

    換源前量過的兩件事（都在 `progress_log.md` 2026-08-18）：條文集合零增減；
    `--verify` 對 3,860 筆引用零翻盤（`extractKeyNumbers` 內部本來就先做 NFKC，
    比對一直發生在正規化之後的空間，所以 pack 存全形或半形都到不了判定）。
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    import law_dump  # noqa: PLC0415

    try:
        law_dump.fetch()
        out = law_dump.build_pack(CURRENT_EXAM)
    except law_dump.LawDumpError as exc:
        raise AnchorPackError(f"build failed: {exc}") from exc
    pack = json.loads(out.read_text())
    articles = sum(len(entry.get("articles", {})) for entry in pack.values())
    print(f"wrote {len(pack)}/{len(CORE_LAWS)} laws ({articles} articles) to {out}")
    return 0


def checkPack() -> int:
    pack = loadPack()
    outdated: list[str] = []
    errors: list[str] = []
    for name, pcode in CORE_LAWS:
        localEntry = pack.get(name)
        if not isinstance(localEntry, dict):
            outdated.append(f"{name} (missing locally)")
            continue
        try:
            liveEntry = fetchLaw(name, pcode)
        except AnchorPackError as exc:
            errors.append(str(exc))
            continue
        localDate = localEntry.get("amend_date")
        liveDate = liveEntry["amend_date"]
        if localDate != liveDate:
            outdated.append(f"{name} (local {localDate}, live {liveDate})")
    if errors:
        raise AnchorPackError("check could not reach/parse live site:\n- " + "\n- ".join(errors))
    if outdated:
        print("outdated laws:")
        for item in outdated:
            print(f"- {item}")
        return 2
    print(f"all {CURRENT_EXAM} anchor laws are up to date")
    return 0


def chineseInteger(token: str) -> int:
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3,
              "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    smallUnits = {"十": 10, "百": 100, "千": 1000}
    largeUnits = {"萬": 10_000, "億": 100_000_000}
    total = 0
    section = 0
    number = 0
    hasUnit = any(char in smallUnits or char in largeUnits for char in token)
    if not hasUnit:
        return int("".join(str(digits[char]) for char in token))
    for char in token:
        if char in digits:
            number = digits[char]
        elif char in smallUnits:
            section += (number or 1) * smallUnits[char]
            number = 0
        else:
            section += number
            total += (section or 1) * largeUnits[char]
            section = 0
            number = 0
    return total + section + number


def numeralTokenToAscii(token: str) -> str:
    normalized = unicodedata.normalize("NFKC", token).strip()
    if re.fullmatch(r"\d+", normalized):
        return str(int(normalized))
    if re.fullmatch(f"[{CHINESE_NUMBER_CHARS}]+", normalized):
        return str(chineseInteger(normalized))
    raise ValueError(f"not a supported numeral token: {token!r}")


def normalizeNumerals(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return CHINESE_NUMBER_RE.sub(lambda match: str(chineseInteger(match.group(0))), normalized)


def canonicalNumber(value: str, scale: str | None) -> str:
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"invalid number: {value}") from exc
    multiplier = {None: 1, "千": 1_000, "萬": 10_000, "億": 100_000_000}[scale]
    scaled = number * multiplier
    return format(scaled.normalize(), "f")


def extractKeyNumbers(text: str) -> set[str]:
    normalized = normalizeNumerals(text)
    # 日期（民國式「97年3月28日」「97年3月」）是沿革敘述,不是法定期限——整段剔除,
    # 否則會被切成「97年」「3月」「28日」誤當關鍵數字比對（社工全掃實測的最大誤報源）。
    normalized = re.sub(r"\d{1,3}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?", "", normalized)
    results: set[str] = set()
    for match in KEY_NUMBER_RE.finditer(normalized):
        unit = {"天": "日", "個月": "月"}.get(match.group("unit"), match.group("unit"))
        value = canonicalNumber(match.group("number"), match.group("scale"))
        results.add(f"{value}{unit}")
    return results


def extractCitations(text: str, lawNames: Iterable[str] | None = None) -> list[Citation]:
    lawNames = lawNames if lawNames is not None else LAW_NAMES
    normalized = unicodedata.normalize("NFKC", text)
    citations: list[Citation] = []
    seen: set[tuple[str, str, int]] = set()
    for law in lawNames:
        for lawMatch in re.finditer(re.escape(law), normalized):
            if not LAW_NAME_TAIL_OK.match(normalized[lawMatch.end():lawMatch.end() + 1]):
                continue                      # 「票據法律關係」「公司法人」「所得稅法施行細則」
            afterEnd = min(len(normalized), lawMatch.end() + 36)
            after = ARTICLE_REF_RE.search(normalized, lawMatch.end(), afterEnd)
            # 反向（「…第10條，本法…」）只在**緊鄰**時採計：距離放寬會把前一部法的條號
            # 綁到後面出現的法名上（實證：「通保法第18條之1…適用刑事訴訟法」→ 刑訴第18-1條）。
            beforeStart = max(0, lawMatch.start() - 12)
            beforeMatches = [m for m in ARTICLE_REF_RE.finditer(normalized, beforeStart, lawMatch.start())]
            candidates = [after] if after else beforeMatches[-1:]
            for refMatch in candidates:
                if refMatch is None:
                    continue
                betweenStart = min(lawMatch.end(), refMatch.end())
                betweenEnd = max(lawMatch.start(), refMatch.start())
                between = normalized[betweenStart:betweenEnd]
                if re.search(r"[。！？!?；;\n]", between):
                    continue
                if re.search(r"[一-鿿]{2,12}(?:法|條例|通則|規則)", between):
                    continue                  # 中間夾了另一部法名 → 這個條號不屬於本法
                sub = refMatch.group(2) or refMatch.group(3)
                if sub and SUBARTICLE_FALSE_TAIL.match(normalized[refMatch.end():refMatch.end() + 4]):
                    sub = None            # 「之」是「的」，不是子條號
                art = normalizeArticleNumber(refMatch.group(1), sub)
                start = min(lawMatch.start(), refMatch.start())
                end = max(lawMatch.end(), refMatch.end())
                identity = (law, art, start)
                if identity not in seen:
                    citations.append(Citation(law, art, start, end))
                    seen.add(identity)
    return sorted(citations, key=lambda citation: citation.start)


def citationContext(text: str, citation: Citation) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    boundaries = "。！？!?；;\n"
    left = max(normalized.rfind(char, 0, citation.start) for char in boundaries) + 1
    rightCandidates = [normalized.find(char, citation.end) for char in boundaries]
    validRights = [position for position in rightCandidates if position >= 0]
    right = min(validRights) if validRights else len(normalized)
    return normalized[left:right]


# 舊條號引用：考古題常考「命題當時」的法制,詳解寫舊條號並指出現行條號是正確寫法,
# 不該被判 fail。兩個條件都要成立才降級——只有「舊法」字樣沒指出現行條號,
# 仍是待查的引用,維持 fail。
HISTORICAL_MARKERS = ("命題當時", "修正前", "舊法", "當時法制", "已刪除", "舊律師法")
CURRENT_POINTER = re.compile(r"(?:現行(?:法)?|修正後|已(?:修正|移列|改列))[^。；\n]{0,20}第\s*[0-9０-９一二三四五六七八九十百]+")


def citationParagraph(text: str, citation: Citation) -> str:
    # 「現行條號」常寫在同段的下一句（分號後）,舊條號判定要看整段,不能只看一句。
    normalized = unicodedata.normalize("NFKC", text)
    left = normalized.rfind("\n", 0, citation.start) + 1
    right = normalized.find("\n", citation.end)
    return normalized[left : right if right >= 0 else len(normalized)]


def isHistoricalCitation(paragraph: str) -> bool:
    return any(marker in paragraph for marker in HISTORICAL_MARKERS) and bool(
        CURRENT_POINTER.search(paragraph)
    )


def checkCitation(citation: Citation, text: str, pack: dict[str, Any]) -> dict[str, str]:
    entry = pack.get(citation.law)
    if not isinstance(entry, dict) or not isinstance(entry.get("articles"), dict):
        return {"law": citation.law, "art": citation.art, "status": "fail",
                "note": "law is missing from the local anchor pack"}
    article = entry["articles"].get(citation.art)
    if not isinstance(article, str):
        if isHistoricalCitation(citationParagraph(text, citation)):
            return {"law": citation.law, "art": citation.art, "status": "historical",
                    "note": "已刪除／改號的舊條文，但詳解已明示為舊法並指出現行條號"}
        return {"law": citation.law, "art": citation.art, "status": "fail",
                "note": "cited article does not exist in the local law text"}
    claimed = extractKeyNumbers(citationContext(text, citation))
    articleNumbers = extractKeyNumbers(article)
    missing = sorted(claimed - articleNumbers)
    if missing:
        return {"law": citation.law, "art": citation.art, "status": "flag",
                "note": "key number(s) not found in article text: " + ", ".join(missing)}
    return {"law": citation.law, "art": citation.art, "status": "ok", "note": ""}


def flattenStrings(value: Any, excludedKeys: set[str] | None = None) -> str:
    excluded = excludedKeys or set()
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(flattenStrings(item, excluded) for item in value)
    if isinstance(value, dict):
        return "\n".join(
            flattenStrings(item, excluded) for key, item in value.items() if key not in excluded
        )
    return ""


def jsonExplanationItems(data: Any) -> list[tuple[str, str]]:
    idKeys = ("qid", "id", "question_id", "questionId")
    source = data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else data
    # 正式庫形狀 {meta, explanations:{qid:{t,...}}}——鑽進 explanations,別把頂層鍵當 qid
    if isinstance(source, dict) and isinstance(source.get("explanations"), dict):
        source = source["explanations"]
    if isinstance(source, list):
        results: list[tuple[str, str]] = []
        for index, item in enumerate(source, start=1):
            qid = next((str(item[key]) for key in idKeys if isinstance(item, dict) and key in item), str(index))
            results.append((qid, flattenStrings(item, set(idKeys))))
        return results
    if isinstance(source, dict):
        if any(key in source for key in idKeys):
            qid = next(str(source[key]) for key in idKeys if key in source)
            return [(qid, flattenStrings(source, set(idKeys)))]
        return [(str(key), flattenStrings(value)) for key, value in source.items()]
    raise AnchorPackError("explanations JSON must be an object or array")


def draftExplanationItems(text: str, fallbackQid: str) -> list[tuple[str, str]]:
    headerRe = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:Q(?:ID)?|題號)\s*[:：#]?\s*([A-Za-z0-9_-]+).*$"
    )
    headers = list(headerRe.finditer(text))
    if not headers:
        return [(fallbackQid, text)]
    return [
        (
            match.group(1),
            text[match.end() : headers[index + 1].start() if index + 1 < len(headers) else len(text)],
        )
        for index, match in enumerate(headers)
    ]


def loadExplanationItems(path: Path) -> list[tuple[str, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AnchorPackError(f"could not read explanation file {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return draftExplanationItems(text, path.stem)
    return jsonExplanationItems(data)


def verifyExplanations(path: Path) -> int:
    pack = loadPack()
    items: list[dict[str, Any]] = []
    counts = {"ok": 0, "fail": 0, "flag": 0, "historical": 0}
    for qid, text in loadExplanationItems(path):
        refs = [checkCitation(citation, text, pack) for citation in extractCitations(text)]
        for ref in refs:
            counts[ref["status"]] += 1
        items.append({"qid": qid, "refs": refs})
    result = {
        "items": items,
        "summary": {"items": len(items), "refs": sum(counts.values()), **counts},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if counts["fail"] else 0


def runSelftest() -> int:
    sampleHtml = """
    <html><head><style>第 999 條 hidden</style></head><body>
      <h1>測試法</h1><div>修正日期：民國 113 年 02 月 03 日</div>
      <a href='single?flno=10'>第 10 條</a>
      <div>應於三十日內辦理，並處新臺幣三萬元。</div>
      <a href='single?flno=44-3'>第 44-3 條</a><div>年滿十八歲。</div>
      <footer>本網站係提供法規之最新動態資訊</footer>
    </body></html>
    """
    sampleLaw = parseLawPage(sampleHtml, "測試法", "T0000001")
    tests: list[tuple[str, bool]] = [
        (
            "article-number extraction",
            [(item.art) for item in extractCitations("測試法第44條之3、測試法第 10 條、測試法第４４條之３", ["測試法"])]
            == ["44-3", "10", "44-3"],
        ),
        ("numeral normalization", normalizeNumerals("三十日與３０日") == "30日與30日"),
        ("HTML article parsing", set(sampleLaw["articles"]) == {"10", "44-3"}),
        # --- 引用抽取精準度 canary（2026-07-23 實測 lawyer 46 筆假 fail 的三個成因）---
        (
            "法名後接漢字不算引用（票據法律關係／公司法人）",
            sorted((c.law, c.art) for c in extractCitations(
                "追加票據法律關係，屬民事訴訟法第 386 條第 4 款；公司法人所有，民法第 668 條",
                ["票據法", "民事訴訟法", "公司法", "民法"]))
            == [("民事訴訟法", "386"), ("民法", "668")],
        ),
        (
            "第N-M條前綴式子條可解析",
            sorted((c.law, c.art) for c in extractCitations(
                "證券交易法第 26-1 條規定，公司法第 209 條第 1 項", ["證券交易法", "公司法"]))
            == [("公司法", "209"), ("證券交易法", "26-1")],
        ),
        (
            "條第M項不得誤併為子條",
            [c.art for c in extractCitations("民事訴訟法第 305 條第 6 項", ["民事訴訟法"])] == ["305"],
        ),
        (
            "「條之N」後接單位字時「之」＝「的」，不是子條號",
            [c.art for c in extractCitations(
                "票據法第 22 條之 3 年時效；民事訴訟法第 305 條之兩造同意",
                ["票據法", "民事訴訟法"])] == ["22", "305"],
        ),
        (
            "真子條號不被誤殺",
            [c.art for c in extractCitations("刑事訴訟法第 158 條之 4 規定", ["刑事訴訟法"])] == ["158-4"],
        ),
        (
            "前一部法的條號不綁到後面出現的法名",
            [(c.law, c.art) for c in extractCitations(
                "通保法第 18 條之 1 第 1 項規定，並非當然不得適用刑事訴訟法第 158-4 條",
                ["刑事訴訟法"])] == [("刑事訴訟法", "158-4")],
        ),
    ]
    # 舊條號引用（2026-08-01 月維護實測：律師法第 37-1 條為 103 年命題當時條號，
    # 詳解已標明現行為第 28 條，判 fail 是誤報）
    historicalText = (
        "正解：依 103 年命題當時法制，題幹所引律師法第 37 條之 1 限制司法人員離職"
        "後三年內執行律師職務；現行法已修正為律師法第 28 條。"
    )
    bareOldText = "依律師法第 37 條之 1，離職後三年內不得執業。"
    emptyPack: dict[str, Any] = {"律師法": {"articles": {"28": "司法人員或公職律師自離職之日起三年內"}}}
    historicalRef = checkCitation(
        extractCitations(historicalText, ["律師法"])[0], historicalText, emptyPack
    )
    bareOldRef = checkCitation(
        extractCitations(bareOldText, ["律師法"])[0], bareOldText, emptyPack
    )
    tests.extend(
        [
            ("舊條號＋指出現行條號→historical", historicalRef["status"] == "historical"),
            ("只有舊條號、沒指現行條號→仍 fail", bareOldRef["status"] == "fail"),
        ]
    )

    curlCmd = curlArgv("https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=T0000001")
    tests.extend(
        [
            ("curl 走 IPv4（AAAA 逾時）", "-4" in curlCmd),
            ("curl 不關憑證驗證", "-k" not in curlCmd and "--insecure" not in curlCmd),
            ("curl 帶逾時上限", "--max-time" in curlCmd),
        ]
    )
    samplePack = {"測試法": sampleLaw}
    okRef = checkCitation(extractCitations("測試法第 10 條規定三十日。", ["測試法"])[0], "測試法第 10 條規定三十日。", samplePack)
    failRef = checkCitation(extractCitations("測試法第 99 條。", ["測試法"])[0], "測試法第 99 條。", samplePack)
    flagRef = checkCitation(extractCitations("測試法第 10 條規定四十日。", ["測試法"])[0], "測試法第 10 條規定四十日。", samplePack)
    tests.extend(
        [
            ("ok decision", okRef["status"] == "ok"),
            ("fail decision", failRef["status"] == "fail"),
            ("flag decision", flagRef["status"] == "flag"),
        ]
    )
    for name, passed in tests:
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return 0 if all(passed for _, passed in tests) else 1


def parseArgs(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true", help="fetch and write the anchor pack")
    mode.add_argument("--check", action="store_true", help="compare local and live amendment dates")
    mode.add_argument("--verify", action="store_true", help="verify citations in explanations")
    mode.add_argument("--selftest", action="store_true", help="run embedded offline tests")
    parser.add_argument("--exam", choices=sorted(EXAM_LAWS))
    parser.add_argument("--expl", type=Path, help="JSON or draft explanations file")
    args = parser.parse_args(argv)
    if not args.selftest:
        if not args.exam:
            parser.error("--exam <exam> is required for --build/--check/--verify")
        setExam(args.exam)
    if args.verify and args.expl is None:
        parser.error("--expl is required with --verify")
    if not args.verify and args.expl is not None:
        parser.error("--expl is only valid with --verify")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parseArgs(argv)
    try:
        if args.selftest:
            return runSelftest()
        if args.build:
            return buildPack()
        if args.check:
            return checkPack()
        return verifyExplanations(args.expl)
    except AnchorPackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
