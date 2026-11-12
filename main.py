import sys
import json
import re
import time
import os
from datetime import datetime

import requests

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
)

from PySide6.QtCore import QThread, Signal

from playwright.sync_api import sync_playwright


# ============================================================
# 配置
# ============================================================

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

BASE_DIR = os.path.dirname(
    os.path.abspath(sys.argv[0])
)

BANK_FILE = os.path.join(
    BASE_DIR,
    "question_bank.json"
)


# ============================================================
# 文本标准化
# ============================================================

def normalize_text(text):
    if not text:
        return ""

    text = str(text)

    # 去掉空白
    text = re.sub(
        r"\s+",
        "",
        text
    )

    # 去掉常见标点
    text = re.sub(
        r"[，。！？、；：,.!?;:\"'“”‘’（）()【】\[\]{}<>《》]",
        "",
        text
    )

    return text.lower()


# ============================================================
# 本地题库
# ============================================================

class QuestionBank:

    def __init__(self, filename):

        self.filename = filename

        self.data = []

        self.load()

    # --------------------------------------------------------

    def load(self):

        if not os.path.exists(
            self.filename
        ):

            self.data = []

            return

        try:

            with open(
                self.filename,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            if isinstance(
                data,
                list
            ):

                self.data = data

            else:

                self.data = []

        except Exception:

            self.data = []

    # --------------------------------------------------------

    def save(self):

        temp_file = (
            self.filename
            + ".tmp"
        )

        try:

            with open(
                temp_file,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    self.data,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            os.replace(
                temp_file,
                self.filename
            )

        except Exception as e:

            print(
                "题库保存失败：",
                e
            )

    # --------------------------------------------------------

    def find(self, question):

        target = normalize_text(
            question
        )

        if not target:

            return None

        # 精确匹配
        for item in self.data:

            old_question = normalize_text(
                item.get(
                    "question",
                    ""
                )
            )

            if old_question == target:

                return item

        # 简单模糊匹配
        for item in self.data:

            old_question = normalize_text(
                item.get(
                    "question",
                    ""
                )
            )

            if not old_question:

                continue

            if (
                len(target) >= 12
                and len(old_question) >= 12
            ):

                if (
                    target in old_question
                    or
                    old_question in target
                ):

                    return item

        return None

    # --------------------------------------------------------

    def add(
        self,
        question,
        answers,
        source="DeepSeek"
    ):

        now = datetime.now().isoformat(
            timespec="seconds"
        )

        existing = self.find(
            question
        )

        if existing:

            existing["answers"] = answers

            existing["last_seen"] = now

            existing["count"] = (
                existing.get(
                    "count",
                    1
                )
                + 1
            )

        else:

            self.data.append(
                {
                    "question": question,
                    "answers": answers,
                    "source": source,
                    "count": 1,
                    "created": now,
                    "last_seen": now,
                }
            )

        self.save()


# ============================================================
# 工作线程
# ============================================================

class Worker(QThread):

    log = Signal(str)

    def __init__(
        self,
        api_key,
        model,
        port,
        delay
    ):

        super().__init__()

        self.api_key = (
            api_key.strip()
        )

        self.model = (
            model.strip()
            or "deepseek-flash"
        )

        self.port = (
            port.strip()
            or "9222"
        )

        try:

            self.delay = float(
                delay
            )

        except Exception:

            self.delay = 2.0

        self.stop_flag = False

        self.bank = QuestionBank(
            BANK_FILE
        )

    # ========================================================
    # 停止
    # ========================================================

    def stop(self):

        self.stop_flag = True

        self.log.emit(
            "正在停止……"
        )

    # ========================================================
    # DeepSeek
    # ========================================================

    def ask_deepseek(
        self,
        question,
        options
    ):

        if not self.api_key:

            raise RuntimeError(
                "没有填写 DeepSeek API Key"
            )

        option_text = "\n".join(
            [
                f"{letter}. {text}"
                for letter, text
                in options.items()
            ]
        )

        prompt = f"""
请回答下面这道选择题。

题目：
{question}

选项：
{option_text}

要求：

1. 只返回 JSON。
2. 格式必须是：
{{"answers":["A"]}}

3. 多选题例如：
{{"answers":["A","C"]}}

4. 只能返回 A、B、C、D。
5. 不要输出解释。
6. 单选题只返回一个答案。
7. 多选题返回所有正确答案。
"""

        headers = {
            "Authorization":
                f"Bearer {self.api_key}",

            "Content-Type":
                "application/json",
        }

        payload = {

            "model":
                self.model,

            "messages": [

                {
                    "role":
                        "system",

                    "content":
                        "你是严谨的计算机课程选择题解答助手。"
                },

                {
                    "role":
                        "user",

                    "content":
                        prompt
                }

            ],

            "temperature":
                0,

            "response_format":
                {
                    "type":
                        "json_object"
                }
        }

        response = requests.post(
            DEEPSEEK_URL,
            headers=headers,
            json=payload,
            timeout=60
        )

        if response.status_code != 200:

            raise RuntimeError(
                "DeepSeek HTTP "
                f"{response.status_code}: "
                f"{response.text[:500]}"
            )

        data = response.json()

        content = (
            data
            .get(
                "choices",
                [{}]
            )[0]
            .get(
                "message",
                {}
            )
            .get(
                "content",
                ""
            )
        )

        if not content:

            raise RuntimeError(
                "DeepSeek 没有返回答案"
            )

        # 尝试直接解析 JSON
        try:

            result = json.loads(
                content
            )

        except Exception:

            # 如果模型带了多余内容
            match = re.search(
                r"\{.*\}",
                content,
                re.S
            )

            if not match:

                raise RuntimeError(
                    "无法解析 DeepSeek 返回："
                    + content
                )

            result = json.loads(
                match.group(0)
            )

        answers = result.get(
            "answers",
            []
        )

        if isinstance(
            answers,
            str
        ):

            answers = [
                answers
            ]

        answers = [
            str(x).upper().strip()
            for x in answers
            if str(x).upper().strip()
            in [
                "A",
                "B",
                "C",
                "D"
            ]
        ]

        # 去重
        answers = list(
            dict.fromkeys(
                answers
            )
        )

        if not answers:

            raise RuntimeError(
                "DeepSeek 返回了无效答案："
                + content
            )

        return answers

    # ========================================================
    # 检测测评是否完成
    # ========================================================

    def is_completed(
        self,
        page
    ):

        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=3000
            )

        except Exception:

            return False

        if not body_text:

            return False

        completion_keywords = [

            "恭喜你,本次考评成功",

            "恭喜你，本次考评成功",

            "本次考评成功",

            "考评成功",

            "测评成功",

            "考试完成",

            "测评完成",

            "考评完成",

        ]

        for keyword in completion_keywords:

            if keyword in body_text:

                return True

        return False

    # ========================================================
    # 点击开始测评
    # ========================================================

    def click_start_test(
        self,
        page
    ):

        try:

            self.log.emit(
                "正在查找“开始测评”按钮……"
            )

            start_clicked = False

            # ------------------------------------------------
            # 方法1：直接找文字
            # ------------------------------------------------

            try:

                elements = page.get_by_text(
                    "开始测评",
                    exact=True
                )

                count = elements.count()

                for i in range(count):

                    try:

                        element = elements.nth(
                            i
                        )

                        if element.is_visible():

                            element.click()

                            start_clicked = True

                            self.log.emit(
                                "✓ 已点击“开始测评”"
                            )

                            break

                    except Exception:

                        continue

            except Exception:

                pass

            # ------------------------------------------------
            # 方法2：按钮
            # ------------------------------------------------

            if not start_clicked:

                try:

                    elements = page.locator(
                        "button, a, "
                        "input[type='button'], "
                        "input[type='submit']"
                    )

                    count = elements.count()

                    for i in range(count):

                        try:

                            element = elements.nth(
                                i
                            )

                            if not element.is_visible():

                                continue

                            text = ""

                            try:

                                text = element.inner_text(
                                    timeout=1000
                                ).strip()

                            except Exception:

                                pass

                            value = (
                                element.get_attribute(
                                    "value"
                                )
                                or ""
                            )

                            if (
                                "开始测评"
                                in text
                                or
                                "开始测评"
                                in value
                            ):

                                element.click()

                                start_clicked = True

                                self.log.emit(
                                    "✓ 已点击“开始测评”"
                                )

                                break

                        except Exception:

                            continue

                except Exception:

                    pass

            # ------------------------------------------------
            # 没找到开始按钮
            # ------------------------------------------------

            if not start_clicked:

                self.log.emit(
                    "⚠ 没找到“开始测评”，"
                    "可能已经在答题页面。"
                )

                return

            # ------------------------------------------------
            # 等待确认弹窗
            # ------------------------------------------------

            time.sleep(1)

            self.log.emit(
                "正在检查“是否立即开始？”确认弹窗……"
            )

            confirm_clicked = False

            # ------------------------------------------------
            # 方法1：寻找“确定”
            # ------------------------------------------------

            try:

                elements = page.get_by_text(
                    "确定",
                    exact=True
                )

                count = elements.count()

                for i in range(count):

                    try:

                        element = elements.nth(
                            i
                        )

                        if element.is_visible():

                            element.click()

                            confirm_clicked = True

                            self.log.emit(
                                "✓ 已点击“确定”，"
                                "正式开始测评"
                            )

                            break

                    except Exception:

                        continue

            except Exception:

                pass

            # ------------------------------------------------
            # 方法2：按钮查找
            # ------------------------------------------------

            if not confirm_clicked:

                try:

                    elements = page.locator(
                        "button, a, "
                        "input[type='button'], "
                        "input[type='submit']"
                    )

                    count = elements.count()

                    for i in range(count):

                        try:

                            element = elements.nth(
                                i
                            )

                            if not element.is_visible():

                                continue

                            text = ""

                            try:

                                text = element.inner_text(
                                    timeout=1000
                                ).strip()

                            except Exception:

                                pass

                            value = (
                                element.get_attribute(
                                    "value"
                                )
                                or ""
                            )

                            if (
                                text == "确定"
                                or
                                value == "确定"
                            ):

                                element.click()

                                confirm_clicked = True

                                self.log.emit(
                                    "✓ 已点击确认按钮"
                                )

                                break

                        except Exception:

                            continue

                except Exception:

                    pass

            if not confirm_clicked:

                self.log.emit(
                    "⚠ 没检测到“确定”按钮，"
                    "可能没有确认弹窗。"
                )

            # 等页面真正进入题目
            time.sleep(2)

        except Exception as e:

            self.log.emit(
                "开始测评处理失败："
                + str(e)
            )

    # ========================================================
    # 提取当前题目
    # ========================================================

    def extract_question(
        self,
        page
    ):

        # ----------------------------------------------------
        # 首先检测完成页
        # ----------------------------------------------------

        if self.is_completed(
            page
        ):

            return None, {}

        # ----------------------------------------------------
        # 获取页面文字
        # ----------------------------------------------------

        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=5000
            )

        except Exception:

            return None, {}

        if not body_text:

            return None, {}

        # ----------------------------------------------------
        # 防止完成页面
        # ----------------------------------------------------

        if (
            "恭喜你,本次考评成功"
            in body_text
            or
            "恭喜你，本次考评成功"
            in body_text
            or
            "本次考评成功"
            in body_text
        ):

            return None, {}

        # ----------------------------------------------------
        # 识别选项
        # ----------------------------------------------------

        options = {}

        # 常见元素
        try:

            elements = page.locator(
                "label, li, "
                "[class*='option'], "
                "[class*='answer'], "
                "[class*='choice']"
            )

            count = elements.count()

            for i in range(count):

                try:

                    element = elements.nth(
                        i
                    )

                    if not element.is_visible():

                        continue

                    text = element.inner_text(
                        timeout=1000
                    ).strip()

                    if not text:

                        continue

                    text = re.sub(
                        r"\s+",
                        " ",
                        text
                    )

                    match = re.match(
                        r"^\s*([A-D])[\.\、:：\)]\s*(.+)$",
                        text,
                        re.S
                    )

                    if match:

                        letter = (
                            match.group(1)
                            .upper()
                        )

                        content = (
                            match.group(2)
                            .strip()
                        )

                        if letter not in options:

                            options[letter] = content

                except Exception:

                    continue

        except Exception:

            pass

        # ----------------------------------------------------
        # 页面文字兜底识别选项
        # ----------------------------------------------------

        if len(options) < 2:

            pattern = re.compile(
                r"(?:^|\n)"
                r"\s*([A-D])[\.\、:：\)]\s*"
                r"(.+?)"
                r"(?=\n\s*[A-D][\.\、:：\)]|\Z)",
                re.S
            )

            matches = pattern.findall(
                body_text
            )

            for letter, content in matches:

                letter = letter.upper()

                content = re.sub(
                    r"\s+",
                    " ",
                    content
                ).strip()

                if letter not in options:

                    options[letter] = content

        # ----------------------------------------------------
        # 识别题目
        # ----------------------------------------------------

        question = ""

        selectors = [

            ".question-title",

            ".question",

            ".exam-question",

            ".subject-title",

            ".topic-title",

            "[class*='question-title']",

            "[class*='subject-title']",

            "[class*='question']",

            "[class*='topic']",

        ]

        for selector in selectors:

            try:

                elements = page.locator(
                    selector
                )

                count = elements.count()

                for i in range(count):

                    try:

                        element = elements.nth(
                            i
                        )

                        if not element.is_visible():

                            continue

                        text = element.inner_text(
                            timeout=1000
                        ).strip()

                        if len(text) < 5:

                            continue

                        text = re.sub(
                            r"\s+",
                            " ",
                            text
                        )

                        # 排除完成提示
                        if (
                            "恭喜你" in text
                            or
                            "考评成功" in text
                            or
                            "测评成功" in text
                        ):

                            continue

                        question = text

                        break

                    except Exception:

                        continue

                if question:

                    break

            except Exception:

                continue

        # ----------------------------------------------------
        # 从页面文本兜底找题目
        # ----------------------------------------------------

        if not question:

            lines = [
                line.strip()
                for line
                in body_text.splitlines()
                if line.strip()
            ]

            for line in lines:

                if len(line) < 5:

                    continue

                # 排除 A-D 选项
                if re.match(
                    r"^[A-D][\.\、:：\)]",
                    line,
                    re.I
                ):

                    continue

                # 排除按钮
                if line in [
                    "开始测评",
                    "下一题",
                    "下一步",
                    "上一题",
                    "提交",
                    "确定",
                    "取消",
                ]:

                    continue

                # 排除完成信息
                if (
                    "恭喜你" in line
                    or
                    "考评成功" in line
                    or
                    "测评成功" in line
                ):

                    continue

                question = line

                break

        if not question:

            return None, options

        return question, options

    # ========================================================
    # 点击答案
    # ========================================================

    def click_answers(
        self,
        page,
        answers,
        options
    ):

        clicked = []

        for answer in answers:

            answer = (
                answer.upper()
                .strip()
            )

            if answer not in [
                "A",
                "B",
                "C",
                "D"
            ]:

                continue

            found = False

            # ------------------------------------------------
            # 根据选项完整文字点击
            # ------------------------------------------------

            option_text = options.get(
                answer,
                ""
            )

            if option_text:

                try:

                    elements = page.get_by_text(
                        option_text,
                        exact=False
                    )

                    count = elements.count()

                    for i in range(count):

                        try:

                            element = elements.nth(
                                i
                            )

                            if element.is_visible():

                                element.click()

                                found = True

                                break

                        except Exception:

                            continue

                except Exception:

                    pass

            # ------------------------------------------------
            # 根据 A. / A、 / A: / A)
            # ------------------------------------------------

            if not found:

                patterns = [

                    f"{answer}.",

                    f"{answer}、",

                    f"{answer}:",

                    f"{answer}：",

                    f"{answer})",

                ]

                for pattern in patterns:

                    try:

                        elements = page.get_by_text(
                            pattern,
                            exact=False
                        )

                        count = elements.count()

                        for i in range(count):

                            try:

                                element = elements.nth(
                                    i
                                )

                                if element.is_visible():

                                    element.click()

                                    found = True

                                    break

                            except Exception:

                                continue

                        if found:

                            break

                    except Exception:

                        continue

            # ------------------------------------------------
            # XPath 兜底
            # ------------------------------------------------

            if not found:

                try:

                    xpath = (
                        "//*["
                        "starts-with("
                        "normalize-space(text()),"
                        f"'{answer}.'"
                        ") or "
                        "starts-with("
                        "normalize-space(text()),"
                        f"'{answer}、'"
                        ") or "
                        "starts-with("
                        "normalize-space(text()),"
                        f"'{answer}:'"
                        ") or "
                        "starts-with("
                        "normalize-space(text()),"
                        f"'{answer}：'"
                        ") or "
                        "starts-with("
                        "normalize-space(text()),"
                        f"'{answer})'"
                        ")"
                        "]"
                    )

                    elements = page.locator(
                        f"xpath={xpath}"
                    )

                    count = elements.count()

                    for i in range(count):

                        try:

                            element = elements.nth(
                                i
                            )

                            if element.is_visible():

                                element.click()

                                found = True

                                break

                        except Exception:

                            continue

                except Exception:

                    pass

            if found:

                clicked.append(
                    answer
                )

        return clicked

    # ========================================================
    # 点击下一题
    # ========================================================

    def click_next(
        self,
        page
    ):

        # ----------------------------------------------------
        # 直接找文字
        # ----------------------------------------------------

        candidates = [

            "下一题",

            "下一步",

            "下一题目",

        ]

        for text in candidates:

            try:

                elements = page.get_by_text(
                    text,
                    exact=True
                )

                count = elements.count()

                for i in range(count):

                    try:

                        element = elements.nth(
                            i
                        )

                        if element.is_visible():

                            element.click()

                            return True

                    except Exception:

                        continue

            except Exception:

                continue

        # ----------------------------------------------------
        # 按钮兜底
        # ----------------------------------------------------

        try:

            elements = page.locator(
                "button, a, "
                "input[type='button'], "
                "input[type='submit']"
            )

            count = elements.count()

            for i in range(count):

                try:

                    element = elements.nth(
                        i
                    )

                    if not element.is_visible():

                        continue

                    text = ""

                    try:

                        text = element.inner_text(
                            timeout=1000
                        ).strip()

                    except Exception:

                        pass

                    value = (
                        element.get_attribute(
                            "value"
                        )
                        or ""
                    )

                    if (
                        "下一题" in text
                        or
                        "下一步" in text
                        or
                        "下一题" in value
                        or
                        "下一步" in value
                    ):

                        element.click()

                        return True

                except Exception:

                    continue

        except Exception:

            pass

        return False

    # ========================================================
    # 主程序
    # ========================================================

    def run(self):

        self.log.emit(
            "================================"
        )

        self.log.emit(
            "DeepSeek 足下自动测评助手启动"
        )

        self.log.emit(
            "================================"
        )

        self.log.emit(
            f"题库位置：{BANK_FILE}"
        )

        with sync_playwright() as p:

            browser = None

            try:

                # ------------------------------------------------
                # 连接 Edge
                # ------------------------------------------------

                self.log.emit(
                    "正在连接 Edge CDP "
                    f"127.0.0.1:{self.port}……"
                )

                browser = p.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{self.port}"
                )

                self.log.emit(
                    "✓ Edge CDP 连接成功"
                )

                # ------------------------------------------------
                # 找页面
                # ------------------------------------------------

                page = None

                for context in browser.contexts:

                    if not context.pages:

                        continue

                    # 优先寻找有标题的页面
                    for candidate in context.pages:

                        try:

                            title = candidate.title()

                            if title:

                                page = candidate

                                break

                        except Exception:

                            continue

                    if page is None:

                        page = context.pages[0]

                    break

                if page is None:

                    raise RuntimeError(
                        "没有找到 Edge 中打开的页面。"
                    )

                self.log.emit(
                    f"当前页面：{page.url}"
                )

                # ------------------------------------------------
                # 自动开始测评
                # ------------------------------------------------

                if not self.is_completed(
                    page
                ):

                    self.click_start_test(
                        page
                    )

                # ------------------------------------------------
                # 开始答题
                # ------------------------------------------------

                question_number = 0

                empty_retry = 0

                while not self.stop_flag:

                    # ============================================
                    # 第一优先级：检测完成
                    # ============================================

                    if self.is_completed(
                        page
                    ):

                        self.log.emit(
                            ""
                        )

                        self.log.emit(
                            "🎉 检测到考评成功！"
                        )

                        self.log.emit(
                            "本次测评已经完成。"
                        )

                        self.log.emit(
                            "自动刷题已停止。"
                        )

                        break

                    # ============================================
                    # 提取题目
                    # ============================================

                    question, options = (
                        self.extract_question(
                            page
                        )
                    )

                    # ============================================
                    # 再次检测完成
                    # ============================================

                    if self.is_completed(
                        page
                    ):

                        self.log.emit(
                            ""
                        )

                        self.log.emit(
                            "🎉 检测到考评成功！"
                        )

                        self.log.emit(
                            "本次测评已经完成。"
                        )

                        break

                    # ============================================
                    # 没识别到题目
                    # ============================================

                    if not question:

                        empty_retry += 1

                        self.log.emit(
                            "⚠ 暂时没有识别到题目，"
                            f"等待页面加载…… "
                            f"({empty_retry}/5)"
                        )

                        if empty_retry >= 5:

                            self.log.emit(
                                "⚠ 连续 5 次没有识别到题目。"
                            )

                            self.log.emit(
                                "请检查足下页面是否正常显示。"
                            )

                            break

                        time.sleep(
                            1
                        )

                        continue

                    empty_retry = 0

                    question_number += 1

                    self.log.emit(
                        ""
                    )

                    self.log.emit(
                        f"第 {question_number} 题"
                    )

                    self.log.emit(
                        f"题目：{question}"
                    )

                    # ============================================
                    # 没识别到选项
                    # ============================================

                    if not options:

                        self.log.emit(
                            "⚠ 未识别到选项。"
                        )

                        time.sleep(
                            1
                        )

                        continue

                    # ============================================
                    # 显示选项
                    # ============================================

                    for letter in [
                        "A",
                        "B",
                        "C",
                        "D"
                    ]:

                        if letter in options:

                            self.log.emit(
                                f"{letter}. "
                                f"{options[letter]}"
                            )

                    # ============================================
                    # 查本地题库
                    # ============================================

                    local = self.bank.find(
                        question
                    )

                    answers = None

                    if local:

                        answers = local.get(
                            "answers",
                            []
                        )

                        self.log.emit(
                            "✓ 本地题库命中"
                        )

                        self.log.emit(
                            "本地答案："
                            + ", ".join(
                                answers
                            )
                        )

                    # ============================================
                    # 本地没有 → DeepSeek
                    # ============================================

                    else:

                        self.log.emit(
                            "本地题库未命中。"
                        )

                        self.log.emit(
                            "正在请求 DeepSeek……"
                        )

                        try:

                            answers = (
                                self.ask_deepseek(
                                    question,
                                    options
                                )
                            )

                            self.log.emit(
                                "DeepSeek 答案："
                                + ", ".join(
                                    answers
                                )
                            )

                            # 自动保存
                            self.bank.add(
                                question,
                                answers,
                                "DeepSeek"
                            )

                            self.log.emit(
                                "✓ 已自动记录到本地题库。"
                            )

                        except Exception as e:

                            self.log.emit(
                                "✗ DeepSeek 请求失败："
                                + str(e)
                            )

                            time.sleep(
                                2
                            )

                            continue

                    # ============================================
                    # 点击答案
                    # ============================================

                    clicked = (
                        self.click_answers(
                            page,
                            answers,
                            options
                        )
                    )

                    if clicked:

                        self.log.emit(
                            "✓ 已选择："
                            + ", ".join(
                                clicked
                            )
                        )

                    else:

                        self.log.emit(
                            "⚠ 没有成功点击答案。"
                        )

                        time.sleep(
                            1
                        )

                        continue

                    # ============================================
                    # 答题后等待
                    # ============================================

                    time.sleep(
                        self.delay
                    )

                    if self.stop_flag:

                        break

                    # ============================================
                    # 点击下一题
                    # ============================================

                    if self.is_completed(
                        page
                    ):

                        self.log.emit(
                            "🎉 检测到考评成功！"
                        )

                        break

                    next_clicked = (
                        self.click_next(
                            page
                        )
                    )

                    if next_clicked:

                        self.log.emit(
                            "→ 已点击“下一题”"
                        )

                    else:

                        # 有些最后一题会直接完成
                        time.sleep(
                            0.5
                        )

                        if self.is_completed(
                            page
                        ):

                            self.log.emit(
                                "🎉 测评完成！"
                            )

                            break

                        self.log.emit(
                            "⚠ 没找到“下一题”按钮。"
                        )

                    # ============================================
                    # 等待下一题加载
                    # ============================================

                    time.sleep(
                        max(
                            0.5,
                            self.delay
                        )
                    )

            except Exception as e:

                self.log.emit(
                    ""
                )

                self.log.emit(
                    "错误："
                    f"{type(e).__name__}: {e}"
                )

            finally:

                try:

                    if browser:

                        browser.close()

                except Exception:

                    pass

                self.log.emit(
                    ""
                )

                self.log.emit(
                    "程序已结束。"
                )


# ============================================================
# 主窗口
# ============================================================

class MainWindow(QWidget):

    def __init__(self):

        super().__init__()

        self.worker = None

        self.setWindowTitle(
            "DeepSeek 足下自动测评助手"
        )

        self.resize(
            850,
            650
        )

        layout = QVBoxLayout()

        # ====================================================
        # API Key
        # ====================================================

        row1 = QHBoxLayout()

        row1.addWidget(
            QLabel(
                "DeepSeek API Key："
            )
        )

        self.api_key = QLineEdit()

        self.api_key.setEchoMode(
            QLineEdit.Password
        )

        row1.addWidget(
            self.api_key
        )

        layout.addLayout(
            row1
        )

        # ====================================================
        # 模型
        # ====================================================

        row2 = QHBoxLayout()

        row2.addWidget(
            QLabel(
                "模型："
            )
        )

        self.model = QLineEdit(
            "deepseek-flash"
        )

        row2.addWidget(
            self.model
        )

        layout.addLayout(
            row2
        )

        # ====================================================
        # Edge CDP
        # ====================================================

        row3 = QHBoxLayout()

        row3.addWidget(
            QLabel(
                "Edge CDP 端口："
            )
        )

        self.port = QLineEdit(
            "9222"
        )

        row3.addWidget(
            self.port
        )

        layout.addLayout(
            row3
        )

        # ====================================================
        # 延迟
        # ====================================================

        row4 = QHBoxLayout()

        row4.addWidget(
            QLabel(
                "每题延迟："
            )
        )

        self.delay = QLineEdit(
            "2"
        )

        row4.addWidget(
            self.delay
        )

        row4.addWidget(
            QLabel(
                "秒"
            )
        )

        layout.addLayout(
            row4
        )

        # ====================================================
        # 按钮
        # ====================================================

        button_layout = QHBoxLayout()

        self.start_button = QPushButton(
            "开始自动测评"
        )

        self.stop_button = QPushButton(
            "停止"
        )

        self.stop_button.setEnabled(
            False
        )

        button_layout.addWidget(
            self.start_button
        )

        button_layout.addWidget(
            self.stop_button
        )

        layout.addLayout(
            button_layout
        )

        # ====================================================
        # 日志
        # ====================================================

        layout.addWidget(
            QLabel(
                "运行日志："
            )
        )

        self.log_box = QTextEdit()

        self.log_box.setReadOnly(
            True
        )

        layout.addWidget(
            self.log_box
        )

        self.setLayout(
            layout
        )

        # ====================================================
        # 信号
        # ====================================================

        self.start_button.clicked.connect(
            self.start_worker
        )

        self.stop_button.clicked.connect(
            self.stop_worker
        )

    # ========================================================
    # 开始
    # ========================================================

    def start_worker(self):

        if (
            self.worker
            and
            self.worker.isRunning()
        ):

            return

        api_key = (
            self.api_key.text()
            .strip()
        )

        model = (
            self.model.text()
            .strip()
        )

        port = (
            self.port.text()
            .strip()
        )

        delay = (
            self.delay.text()
            .strip()
        )

        self.log_box.clear()

        self.start_button.setEnabled(
            False
        )

        self.stop_button.setEnabled(
            True
        )

        self.worker = Worker(
            api_key,
            model,
            port,
            delay
        )

        self.worker.log.connect(
            self.append_log
        )

        self.worker.finished.connect(
            self.worker_finished
        )

        self.worker.start()

    # ========================================================
    # 停止
    # ========================================================

    def stop_worker(self):

        if self.worker:

            self.worker.stop()

    # ========================================================
    # 线程结束
    # ========================================================

    def worker_finished(self):

        self.start_button.setEnabled(
            True
        )

        self.stop_button.setEnabled(
            False
        )

        self.append_log(
            "================================"
        )

        self.append_log(
            "任务结束"
        )

        self.append_log(
            "================================"
        )

    # ========================================================
    # 日志
    # ========================================================

    def append_log(
        self,
        text
    ):

        self.log_box.append(
            text
        )


# ============================================================
# 程序入口
# ============================================================

def main():

    app = QApplication(
        sys.argv
    )

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":

    main()