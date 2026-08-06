# auto_solver_refactored.py

# 导入标准库
import os
import re
import time
import json
import logging
import argparse
import ctypes
from itertools import combinations
from collections import defaultdict

# Chromium 的渲染子窗口使用物理像素。必须在 GUI 库初始化前
# 启用 DPI awareness，否则 125%/150% 缩放下会把鼠标消息发到错误句柄。
if os.name == "nt":
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

# 导入第三方库
import pyautogui
import pyperclip
from airtest.core.cv import Template
import numpy as np
import cv2
from pywinauto import Desktop
from pywinauto.findwindows import find_windows

# ============================ 新增依赖库导入 (可选，但强烈推荐) ============================
try:
    # 导入用于访问Windows剪贴板高级格式 (HTML) 的库
    import win32clipboard
    import win32gui
    import win32api
    import win32con
    # 导入用于解析HTML内容的库
    from bs4 import BeautifulSoup
    # 标记为Windows环境，可以启用高级功能
    IS_WINDOWS = True
except ImportError:
    # 如果缺少库，则标记为非Windows环境，并禁用相关功能
    IS_WINDOWS = False
    print("警告：未找到 'pywin32' 或 'beautifulsoup4' 库。基于HTML的题目内容和选中状态验证功能将不可用。")
    print("请运行 'pip install pywin32 beautifulsoup4' 来安装这些库以获得最佳体验。")
# =========================================================================================


# ============================ 动态路径与全局变量配置 ============================
# 使用当前时间戳为本次运行创建唯一的标识符
RUN_TIMESTAMP = time.strftime('%Y%m%d_%H%M%S')

# 日志文件存放目录
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR): os.makedirs(LOG_DIR)
LOG_FILE_PATH = os.path.join(LOG_DIR, f"{RUN_TIMESTAMP}.log")

# 截图文件存放基础目录
SCREENSHOT_BASE_DIR = "screenshots"
# 为本次运行创建一个单独的截图文件夹，方便管理和回溯
SCREENSHOT_RUN_DIR = os.path.join(SCREENSHOT_BASE_DIR, RUN_TIMESTAMP)
if not os.path.exists(SCREENSHOT_RUN_DIR): os.makedirs(SCREENSHOT_RUN_DIR)

# 全局变量，用于在程序运行期间存储数据
solved_questions = {}  # 存储本次运行成功解答的题目及其答案
qa_bank = {}           # 存储从文件中加载的题库数据


TRANSITION_SUCCESS = "success"
TRANSITION_WRONG = "wrong"
TRANSITION_UNKNOWN = "unknown"


class TransitionEvidenceInsufficient(RuntimeError):
    """提交后无法确认成功或答错，必须停止使用旧题上下文。"""


class StaleQuestionContext(RuntimeError):
    """页面已经切到新题，但调用方仍持有上一题的坐标或选项。"""


# ==================== 日志配置 START ====================
# 获取一个日志记录器实例
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # 设置日志记录的最低级别为INFO

# 防止重复添加处理器
if not logger.handlers:
    # 创建一个文件处理器，用于将日志写入文件
    file_handler = logging.FileHandler(LOG_FILE_PATH, mode='w', encoding='utf-8')
    # 创建一个控制台处理器，用于将日志输出到屏幕
    console_handler = logging.StreamHandler()
    
    # 定义日志格式
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 将处理器添加到日志记录器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
# ==================== 日志配置 END ====================


# ==============================================================================
# ============================ 全局配置 (请根据您的环境修改) =============================
# ==============================================================================

# --- 主要运行配置 ---
# 目标窗口/区域在屏幕上的位置和大小。格式: (左上角x坐标, 左上角y坐标, 宽度, 高度)
# 可以使用 pyautogui.displayMousePosition() 在终端中实时查看鼠标坐标来确定此区域。
# 桌面HTML模式会在启动时自动发现微信小程序窗口并覆盖此值。
SCREEN_REGION = (0, 0, 0, 0)
TARGET_TAB_TITLE = "腾讯游戏安全中心"

# 当前桌面微信布局的归一化几何参数。坐标相对于整个 WeChatAppEx 窗口，
# 因而窗口等比例缩放或移动后仍然有效。
OPTION_CENTER_X_RATIO = 0.5000
OPTION_FIRST_Y_RATIO = 0.2957
OPTION_STEP_Y_RATIO = 0.1525
SUBMIT_CENTER_X_RATIO = 0.5000
SUBMIT_CENTER_Y_RATIO = 0.8850
PAGE_FOCUS_X_RATIO = 0.0750
PAGE_FOCUS_Y_RATIO = 0.1100
TARGET_WINDOW = None
TARGET_MODE = "legacy_html"
TASK_FINISHED = False

# ============================ 题库配置 ============================
# 是否启用题库模式。如果为 True，脚本会优先使用题库中的答案。
USE_QA_BANK = True
# 主题库文件名。脚本将从此文件加载和更新题库。
QA_BANK_FILE = "master_qa_bank.json"

# ============================ 图像识别相似度配置 ============================
# 选项图片(如 A.png, B.png)的识别阈值。范围 0.0 ~ 1.0，值越高代表要求匹配越精确。
# 如果选项标识经常识别失败，可以适当降低此值。根据自己屏幕清晰度来调整。
SIMILARITY_THRESHOLD_OPTION = 0.6
# “提交”按钮图片的识别阈值。范围 0.0 ~ 1.0，值越高代表要求匹配越精确。根据自己屏幕清晰度来调整。
SIMILARITY_THRESHOLD_SUBMIT = 0.6

# 滚动页面的方式。
# 'PC_WHEEL': 模拟桌面电脑的鼠标滚轮滚动，速度快，推荐在PC端模拟器或网页上使用。
# 'MOBILE_DRAG': 模拟手机屏幕的拖动操作（从下往上拖动以向下滚动），适用于无法使用滚轮的场景。
# 'BOTH': 两种方式都执行一次，兼容性更强。
SCROLL_MODE = 'PC_WHEEL'

# --- 延时与重试配置 ---
# ============================ 【新增】解题重试配置 ============================
# 当一道题目解答失败时 (例如，所有选项都试过但题目未刷新)，允许的最大重试次数。
# 这可以应对临时的UI卡顿或网络问题。
MAX_SOLVE_ATTEMPTS = 1
# 每次解题重试之间的等待时间（秒）。
RETRY_DELAY_BETWEEN_ATTEMPTS = 0.3
# =========================================================================

# ============================ 【新增】精细延时控制 (高级) ============================
# 以下配置项控制脚本在特定操作后的等待时间，单位为秒。
# 如果您的计算机或模拟器反应较慢，导致操作失败（如复制不完整、点击后状态未更新），
# 可以适当增加这些值。通常情况下，保持默认值即可。
# =================================================================================
# 脚本启动后，在进行初始环境校验前的等待时间。给用户留出切换窗口的时间。
# 默认值: 3.0
INITIAL_VALIDATION_DELAY = 0.2

# --- 已有延时配置 ---
# 提交后首次读取页面的等待时间，以及过渡页最长等待时间。
FIXED_POST_SUBMIT_DELAY = 1.0
QUESTION_TRANSITION_TIMEOUT = 10.0
QUESTION_TRANSITION_GRACE_TIMEOUT = 10.0
QUESTION_TRANSITION_POLL_INTERVAL = 0.2
QUESTION_HTML_FALLBACK_INTERVAL = 1.0
QUESTION_SAME_EVIDENCE_MAX_AGE = 1.2
# 每次点击选项后的等待时间（秒）。如果点击后UI反应慢，可适当增加此值。
POST_TOUCH_DELAY = 0.05

# 初始化时，点击“提交”按钮激活窗口后的等待时间，以确保窗口状态稳定。
# 默认值: 1.0
POST_ACTIVATION_CLICK_DELAY = 1.0

# 在主循环中，如果检测到题目内容没有变化，脚本将等待此时间后再次检查。
# 默认值: 2
POLLING_INTERVAL_NO_CHANGE = 0.3

# 在主循环中，如果无法获取到题目信息（可能应用卡死或已结束），脚本等待此时间后重试。
# 默认值: 5.0
RETRY_DELAY_ON_ERROR = 0.5

# 模拟“全选”(Ctrl+A)后，等待系统响应的时间。
# 默认值: 0.1
DELAY_AFTER_SELECT_ALL = 0.03

# 模拟“复制”(Ctrl+C)后，等待内容进入剪贴板的时间。
# 默认值: 0.2
DELAY_AFTER_COPY = 0.06

# 在多选题验证点击中，完成一系列点击操作后，等待UI稳定再进行HTML验证的延时。
# 默认值: 0.5
DELAY_BEFORE_VERIFY_CLICK = 0.06

# 当滚动模式为 'BOTH' 时，在两种滚动方式（拖动和滚轮）之间的延时，防止操作冲突。
# 默认值: 0.3
DELAY_BETWEEN_SCROLL_METHODS = 0.5

# 每次滚动操作后的等待时间（秒），确保页面内容已加载完毕。
POST_SCROLL_DELAY = 1.5
# # 【已弃用】单选题遍历模式下的最大尝试次数。现在由逻辑自动决定。
# MAX_SINGLE_CHOICE_ATTEMPTS = 2
# # 【已弃用】多选题遍历模式下的最大尝试次数。现在由逻辑自动决定。
# MAX_MULTI_CHOICE_ATTEMPTS = 3
# 当屏幕上找不到“提交”按钮时，尝试向下滚动的最大次数。
MAX_SCROLL_ATTEMPTS = 3
# 当遇到指定题号时，脚本将自动停止。设置为空字符串 "" 可禁用此功能。例如: "第78题",未修复。
STOP_AT_QUESTION_NUM = None

# ===========================================================================


# ------------------- 资源与模板定义 -------------------
# 存放模板图片的目录 (如 option_A_1.png, option_A_2.png, option_B_1.png 等)
TEMPLATES_DIR = "templates"
if not os.path.exists(TEMPLATES_DIR): 
    os.makedirs(TEMPLATES_DIR)
    logger.warning(f"模板目录 '{TEMPLATES_DIR}' 不存在，已自动创建。请将模板图片放入其中。")

def load_option_templates(directory, threshold=0.7):
    """
    从指定目录加载选项模板图片 (例如, option_A_1.png)。
    支持同一选项有多个模板 (例如 option_A_1.png, option_A_2.png)，以提高识别率。
    
    Args:
        directory (str): 存放模板图片的目录路径。
        threshold (float): 图像匹配的相似度阈值。

    Returns:
        dict: 一个字典，键是选项名 ( 'A', 'B', ...)，值是对应的Template对象列表。
              如果关键模板缺失，则返回空字典。
    """
    logger.info(f"开始从 '{directory}' 目录加载选项模板...")
    option_templates = defaultdict(list)
    try:
        filenames = os.listdir(directory)
    except FileNotFoundError:
        logger.error(f"模板目录 '{directory}' 未找到！脚本无法继续。")
        return {}
    
    # 使用正则表达式匹配文件名，格式为 "option_字母_序号.png"
    pattern = re.compile(r"option_([A-D])_(\d+)\.png")
    for filename in sorted(filenames):
        match = pattern.match(filename)
        if match:
            option_name = match.group(1)
            full_path = os.path.join(directory, filename)
            # 使用配置的阈值创建Template对象
            template = Template(full_path, threshold=threshold)
            option_templates[option_name].append(template)
            logger.info(f"  -> 已加载模板: {filename} for Option {option_name}")
            
    # 校验是否所有必需的选项 (A, B, C, D) 都有模板
    required_options = {'A', 'B', 'C', 'D'}
    loaded_options = set(option_templates.keys())
    if not required_options.issubset(loaded_options):
        missing = required_options - loaded_options
        logger.error(f"模板文件不完整！templates文件夹中缺少选项 {sorted(list(missing))} 的模板图片。")
        return {}
        
    logger.info("选项模板加载完成。")
    return dict(option_templates)

# 使用全局配置的相似度阈值来加载模板
TEMPLATE_SUBMIT = Template(os.path.join(TEMPLATES_DIR, "submit_button.png"), threshold=SIMILARITY_THRESHOLD_SUBMIT)
TEMPLATE_OPTIONS = load_option_templates(TEMPLATES_DIR, threshold=SIMILARITY_THRESHOLD_OPTION)

# 如果选项模板加载失败，则无法进行答题，直接退出
if not TEMPLATE_OPTIONS:
    logger.critical("由于选项模板加载失败，脚本无法继续运行。")
    exit()

# 打印关键配置信息，方便用户检查
logger.info(f"=========== 配置加载 ===========")
logger.info(f"日志文件将保存至: {LOG_FILE_PATH}")
logger.info(f"本次运行截图将保存至: {SCREENSHOT_RUN_DIR}")
logger.info(f"投屏区域 (Region): {SCREEN_REGION}")
logger.info(f"启用题库模式: {'是' if USE_QA_BANK else '否'}")
logger.info(f"启用HTML验证: {'是' if IS_WINDOWS else '否 (环境不支持)'}")
logger.info(f"选项识别阈值: {SIMILARITY_THRESHOLD_OPTION}")
logger.info(f"提交按钮识别阈值: {SIMILARITY_THRESHOLD_SUBMIT}")


# --- 桌面微信窗口与操作核心函数 ---

def locate_and_activate_target_window():
    """兼容旧版微信标签页和新版独立 Chromium 答题窗口。"""
    global SCREEN_REGION, TARGET_WINDOW, TARGET_MODE
    try:
        desktop = Desktop(backend="uia")

        # 新版会把小程序显示为独立 Chromium 窗口，优先走快速定位。
        for handle in find_windows():
            try:
                if win32gui.GetClassName(handle) != "Chrome_WidgetWin_0":
                    continue
                if win32gui.GetWindowText(handle).strip() != TARGET_TAB_TITLE:
                    continue
                if win32gui.IsIconic(handle):
                    logger.info("答题窗口已最小化，正在恢复")
                    win32gui.ShowWindow(handle, win32con.SW_RESTORE)
                    time.sleep(0.2)
                window = desktop.window(handle=handle)
                rect = window.rectangle()
                if rect.width() <= 0 or rect.height() <= 0:
                    continue
                TARGET_WINDOW = window
                TARGET_MODE = "uia_standalone"
                SCREEN_REGION = (rect.left, rect.top, rect.width(), rect.height())
                _set_target_topmost(True)
                window.set_focus()
                time.sleep(0.1)
                logger.info(
                    f"已定位新版独立答题窗口: handle={window.handle}, "
                    f"region={SCREEN_REGION}"
                )
                return True
            except Exception:
                continue

        # 兼容旧版：答题页是 WeChatAppEx 窗口中的标签。
        for handle in find_windows():
            try:
                window = desktop.window(handle=handle)
                tabs = [
                    item for item in window.descendants(control_type="TabItem")
                    if item.window_text().strip() == TARGET_TAB_TITLE
                ]
                if not tabs:
                    continue
                rect = window.rectangle()
                if rect.width() <= 0 or rect.height() <= 0:
                    continue
                TARGET_WINDOW = window
                TARGET_MODE = "legacy_html"
                SCREEN_REGION = (rect.left, rect.top, rect.width(), rect.height())
                tabs[0].click_input()
                time.sleep(0.25)
                logger.info(
                    f"已定位旧版微信答题标签: handle={window.handle}, "
                    f"region={SCREEN_REGION}"
                )
                return True
            except Exception:
                continue
    except Exception as exc:
        logger.error(f"枚举微信窗口失败: {exc}")
    logger.error(f"没有找到“{TARGET_TAB_TITLE}”答题窗口。")
    return False


def _set_target_topmost(enabled):
    """答题期间临时置顶，避免 WindowFromPoint 命中覆盖在上方的 Chromium 窗口。"""
    if TARGET_WINDOW is None or not IS_WINDOWS:
        return False
    try:
        insert_after = win32con.HWND_TOPMOST if enabled else win32con.HWND_NOTOPMOST
        win32gui.SetWindowPos(
            TARGET_WINDOW.handle,
            insert_after,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE
            | win32con.SWP_NOSIZE
            | win32con.SWP_NOACTIVATE
            | win32con.SWP_SHOWWINDOW,
        )
        return True
    except Exception as exc:
        logger.warning(f"设置答题窗口置顶状态失败: {exc}")
        return False


def ensure_target_active():
    """快速确认目标窗口仍在前台；只有失效时才重新枚举 UIA 标签。"""
    global SCREEN_REGION
    if TARGET_WINDOW is None:
        return locate_and_activate_target_window()
    try:
        if not win32gui.IsWindow(TARGET_WINDOW.handle):
            return locate_and_activate_target_window()
        if win32gui.IsIconic(TARGET_WINDOW.handle):
            logger.info("答题窗口已最小化，正在恢复")
            win32gui.ShowWindow(TARGET_WINDOW.handle, win32con.SW_RESTORE)
            time.sleep(0.2)
        rect = TARGET_WINDOW.rectangle()
        if rect.width() <= 0 or rect.height() <= 0:
            return locate_and_activate_target_window()
        SCREEN_REGION = (rect.left, rect.top, rect.width(), rect.height())
        if win32gui.GetForegroundWindow() != TARGET_WINDOW.handle:
            TARGET_WINDOW.set_focus()
            time.sleep(0.05)
        return True
    except Exception:
        return locate_and_activate_target_window()


def _uia_option_elements():
    """返回新版独立窗口当前题目的选项控件，键为选项字母。"""
    if TARGET_WINDOW is None:
        return {}
    options = {}
    try:
        for element in TARGET_WINDOW.descendants(control_type="ListItem"):
            text = (element.window_text() or "").strip()
            match = re.match(r"^([A-Z])[.、．]\s*(.*)$", text, re.S)
            if match:
                options[match.group(1)] = element
    except Exception as exc:
        logger.warning(f"读取 UIA 选项控件失败: {exc}")
    return options


def _get_uia_question_data():
    """从新版 Chromium 窗口的 UI Automation 控件树读取题目。"""
    if TARGET_WINDOW is None:
        return None
    try:
        elements = TARGET_WINDOW.descendants()
        texts = [(element.window_text() or "").strip() for element in elements]
        page_text = " ".join(text for text in texts if text)
        if "点击完成任务" in page_text or "安全的知识又增加了" in page_text:
            return {
                "page_state": "complete",
                "source": "uia",
                "q_num": "",
                "q_type": "",
                "q_text": "",
                "options": {},
                "selected_options": [],
                "option_positions": {},
            }

        question_indexes = [
            index for index, text in enumerate(texts)
            if re.fullmatch(r"第\d+题", text)
        ]
        if not question_indexes:
            return None
        question_index = question_indexes[-1]
        q_num = texts[question_index]

        q_type = ""
        type_index = None
        for index in range(question_index + 1, len(elements)):
            if texts[index] in ("单选", "多选"):
                q_type = f"{texts[index]}题"
                type_index = index
                break
        if type_index is None:
            return None

        option_entries = []
        for index in range(type_index + 1, len(elements)):
            if elements[index].element_info.control_type != "ListItem":
                continue
            match = re.match(r"^([A-Z])[.、．]\s*(.*)$", texts[index], re.S)
            if match:
                option_entries.append(
                    (index, match.group(1), match.group(2).strip(), elements[index])
                )
        if not option_entries:
            return None

        first_option_index = option_entries[0][0]
        question_parts = []
        for index in range(type_index + 1, first_option_index):
            if elements[index].element_info.control_type != "Text":
                continue
            text = texts[index]
            if text and text not in (q_num, "单选", "多选"):
                question_parts.append(text)
        q_text = "".join(question_parts).strip()
        if not q_text:
            return None

        options = {}
        selected_options = []
        option_positions = {}
        for _, letter, content, element in option_entries:
            options[letter] = content
            class_name = (element.element_info.class_name or "").lower()
            if "active" in class_name or "selected" in class_name:
                selected_options.append(letter)
            rect = element.rectangle()
            option_positions[letter] = (
                int(round((rect.left + rect.right) / 2 - SCREEN_REGION[0])),
                int(round((rect.top + rect.bottom) / 2 - SCREEN_REGION[1])),
            )

        return {
            "source": "uia",
            "q_num": q_num,
            "q_type": q_type,
            "q_text": q_text,
            "options": options,
            "selected_options": sorted(selected_options),
            "option_positions": option_positions,
        }
    except Exception as exc:
        logger.warning(f"解析 UIA 题目失败: {exc}")
        return None


def _get_uia_page_marker():
    """快速读取页面阶段标记，不要求题干和选项控件完整出现。"""
    if TARGET_WINDOW is None:
        return None
    try:
        elements = TARGET_WINDOW.descendants()
        text_entries = [
            (
                (element.window_text() or "").strip(),
                element.element_info.control_type,
            )
            for element in elements
        ]
        page_text = " ".join(text for text, _ in text_entries if text)

        if "点击完成任务" in page_text or "安全的知识又增加了" in page_text:
            return {"page_state": "complete", "source": "uia_marker"}

        if "请求失败" in page_text or "请稍后再试" in page_text:
            return {
                "page_state": "request_error",
                "source": "uia_marker",
                "message": page_text,
            }

        feedback_markers = ("答错", "回答错误", "再试试", "答案错误")
        feedback_detected = any(marker in page_text for marker in feedback_markers)
        feedback_action = next(
            (
                text
                for text, control_type in text_entries
                if control_type in ("Button", "Hyperlink")
                and text in ("确定", "知道了", "再试一次", "继续")
            ),
            None,
        )

        question_numbers = [
            text
            for text, _ in text_entries
            if re.fullmatch(r"第\d+题", text)
        ]
        if question_numbers:
            return {
                "page_state": "question",
                "source": "uia_marker",
                "q_num": question_numbers[-1],
                "feedback_detected": feedback_detected,
                "feedback_action": feedback_action,
            }
        if feedback_detected:
            return {
                "page_state": "feedback",
                "source": "uia_marker",
                "feedback_detected": True,
                "feedback_action": feedback_action,
            }
        return None
    except Exception:
        # Chromium 切页时控件树短暂消失是正常状态，轮询路径不刷警告。
        return None


def _find_uia_button(button_text):
    """查找可执行的按钮或超链接，保留旧函数名以兼容现有调用。"""
    if TARGET_WINDOW is None:
        return None
    try:
        actions = [
            element for element in TARGET_WINDOW.descendants()
            if element.element_info.control_type in ("Button", "Hyperlink")
            and (element.window_text() or "").strip() == button_text
        ]
        return actions[-1] if actions else None
    except Exception:
        return None
def _uia_scroll_wheel(delta):
    """向新版 Chromium 渲染窗口发送滚轮消息，不移动真实鼠标。"""
    try:
        absolute_point = (
            SCREEN_REGION[0] + SCREEN_REGION[2] // 2,
            SCREEN_REGION[1] + SCREEN_REGION[3] // 2,
        )
        target_handle = win32gui.WindowFromPoint(absolute_point)
        if not target_handle:
            return False
        l_param = win32api.MAKELONG(*absolute_point)
        w_param = (delta & 0xFFFF) << 16
        win32gui.PostMessage(
            target_handle, win32con.WM_MOUSEWHEEL, w_param, l_param
        )
        time.sleep(0.1)
        return True
    except Exception as exc:
        logger.warning(f"UIA 页面滚动失败: {exc}")
        return False


def _scroll_uia_element_into_view(element_getter, max_steps=10):
    """反复滚动并重新读取控件，直到整个控件位于窗口可见区域。"""
    virtual_top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    virtual_bottom = virtual_top + win32api.GetSystemMetrics(
        win32con.SM_CYVIRTUALSCREEN
    )
    viewport_top = max(SCREEN_REGION[1] + 4, virtual_top + 4)
    viewport_bottom = min(
        SCREEN_REGION[1] + SCREEN_REGION[3] - 4,
        virtual_bottom - 4,
    )
    for _ in range(max_steps):
        element = element_getter()
        if element is None:
            return None
        rect = element.rectangle()
        if rect.top >= viewport_top and rect.bottom <= viewport_bottom:
            return element
        delta = 480 if rect.top < viewport_top else -480
        if not _uia_scroll_wheel(delta):
            return None
    return None


def _uia_page_has_text(expected_text):
    if TARGET_WINDOW is None:
        return False
    try:
        return any(
            expected_text in (element.window_text() or "")
            for element in TARGET_WINDOW.descendants()
        )
    except Exception:
        return False


def _click_uia_button(button_text):
    action = _scroll_uia_element_into_view(
        lambda: _find_uia_button(button_text)
    )
    if action is None:
        return False
    try:
        control_type = action.element_info.control_type
        if control_type == "Hyperlink":
            logger.info(f"Invoke UIA 超链接“{button_text}”")
            action.invoke()
            return True

        rect = action.rectangle()
        position = (
            int(round((rect.left + rect.right) / 2 - SCREEN_REGION[0])),
            int(round((rect.top + rect.bottom) / 2 - SCREEN_REGION[1])),
        )
        logger.info(f"点击 UIA 按钮“{button_text}”: {position}")
        click_at_region_pos(position)
        return True
    except Exception as exc:
        logger.warning(f"执行 UIA 动作“{button_text}”失败: {exc}")
        return False
def _click_uia_option_letter(letter):
    element = _scroll_uia_element_into_view(
        lambda: _uia_option_elements().get(letter)
    )
    if element is None:
        logger.warning(f"UIA 中找不到或无法滚动到选项 {letter}")
        return False
    try:
        rect = element.rectangle()
        position = (
            int(round((rect.left + rect.right) / 2 - SCREEN_REGION[0])),
            int(round((rect.top + rect.bottom) / 2 - SCREEN_REGION[1])),
        )
        if not (0 <= position[0] < SCREEN_REGION[2] and 0 <= position[1] < SCREEN_REGION[3]):
            logger.warning(f"选项 {letter} 坐标超出窗口: {position}")
            return False
        logger.info(f"点击 UIA 选项 {letter}: {position}")
        click_at_region_pos(position)
        return True
    except Exception as exc:
        logger.warning(f"点击 UIA 选项 {letter} 失败: {exc}")
        return False
def click_at_region_pos(region_pos):
    """
    在 SCREEN_REGION 内的相对坐标上执行点击。

    新版独立 Chromium 窗口使用窗口消息点击，不移动真实鼠标；
    旧版继续使用 PyAutoGUI。
    """
    if not region_pos:
        return
    absolute_x = SCREEN_REGION[0] + region_pos[0]
    absolute_y = SCREEN_REGION[1] + region_pos[1]

    if TARGET_MODE in ("uia_standalone", "standalone_html"):
        try:
            target_handle = win32gui.WindowFromPoint((absolute_x, absolute_y))
            client_x, client_y = win32gui.ScreenToClient(
                target_handle, (absolute_x, absolute_y)
            )
            l_param = win32api.MAKELONG(client_x, client_y)
            win32gui.PostMessage(
                target_handle, win32con.WM_MOUSEMOVE, 0, l_param
            )
            win32gui.PostMessage(
                target_handle,
                win32con.WM_LBUTTONDOWN,
                win32con.MK_LBUTTON,
                l_param,
            )
            win32gui.PostMessage(
                target_handle, win32con.WM_LBUTTONUP, 0, l_param
            )
            return
        except Exception as exc:
            logger.warning(f"窗口消息点击失败，回退 PyAutoGUI: {exc}")

    pyautogui.click(absolute_x, absolute_y)
def _scroll_with_drag():
    """私有函数：通过模拟鼠标拖动来实现滚动。"""
    logger.info("执行[拖动滚动]...")
    region_x, region_y, region_w, region_h = SCREEN_REGION
    # 计算拖动的起点和终点
    drag_center_x = region_x + region_w // 2
    start_y = region_y + region_h * 0.70
    end_y = region_y + region_h * 0.30
    pyautogui.moveTo(drag_center_x, start_y, duration=0.2)
    pyautogui.mouseDown()
    pyautogui.moveTo(drag_center_x, end_y, duration=0.5)
    pyautogui.mouseUp()

def _scroll_with_wheel():
    """私有函数：通过模拟鼠标滚轮来实现滚动。"""
    logger.info("执行[PC滚轮滚动]...")
    region_x, region_y, region_w, region_h = SCREEN_REGION
    # 将鼠标移动到区域中心以确保滚动作用于目标窗口
    center_x = region_x + region_w // 2
    center_y = region_y + region_h // 2
    pyautogui.moveTo(center_x, center_y, duration=0.2)
    # 负值表示向下滚动
    pyautogui.scroll(-500)

def scroll_in_region():
    """根据全局配置 SCROLL_MODE 来执行滚动操作。"""
    if SCROLL_MODE == 'MOBILE_DRAG':
        _scroll_with_drag()
    elif SCROLL_MODE == 'PC_WHEEL':
        _scroll_with_wheel()
    elif SCROLL_MODE == 'BOTH':
        _scroll_with_drag()
        time.sleep(DELAY_BETWEEN_SCROLL_METHODS)
        _scroll_with_wheel()
    else: # 默认为拖动模式
        _scroll_with_drag()


# ============================ 【核心升级】剪贴板解析函数 ============================

def _get_html_from_clipboard():
    """
    【仅Windows】尝试从剪贴板中读取 'HTML Format' 内容。
    当在网页或某些应用中复制内容时，除了纯文本，还会附带HTML格式的数据。
    
    Returns:
        str or None: 如果成功，返回HTML内容的字符串；否则返回None。
    """
    if not IS_WINDOWS: return None
    try:
        win32clipboard.OpenClipboard()
        # 注册并获取 "HTML Format" 的格式ID
        html_format = win32clipboard.RegisterClipboardFormat("HTML Format")
        if win32clipboard.IsClipboardFormatAvailable(html_format):
            data = win32clipboard.GetClipboardData(html_format)
            # HTML格式数据有一个头部，描述了HTML内容的起始和结束位置
            # 我们需要解析这个头部来找到真正的HTML片段
            match = re.search(b"StartFragment:(\\d+)", data)
            if match:
                start_index = int(match.group(1))
                # 从起始位置解码为utf-8字符串，忽略可能出现的解码错误
                return data[start_index:].decode('utf-8', errors='ignore')
    except Exception as e:
        logger.warning(f"读取剪贴板HTML格式时出错: {e}")
    finally:
        if IS_WINDOWS:
            win32clipboard.CloseClipboard()
    return None

def _parse_html_data(html_content):
    """
    使用 BeautifulSoup 解析HTML字符串，智能提取问题、选项（文本或图片URL）和选中状态。
    这是脚本获取题目信息最可靠的方式。

    Args:
        html_content (str): 包含题目信息的HTML代码片段。

    Returns:
        dict or None: 解析成功则返回包含题目信息的字典，否则返回None。
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        page_text = soup.get_text(" ", strip=True)
        if (
            "点击完成任务" in page_text
            or "安全的知识又增加了" in page_text
        ):
            return {
                "page_state": "complete",
                "q_num": "",
                "q_type": "",
                "q_text": "",
                "options": {},
                "selected_options": [],
            }
        
        # 1. 提取题号和题目类型
        title_count_div = soup.find('div', class_='ts_title_count')
        if not title_count_div: return None
        q_num_tag = title_count_div.find('i')
        q_type_tag = title_count_div.find('em')
        q_num = q_num_tag.get_text(strip=True) if q_num_tag else ""
        q_type = f"{q_type_tag.get_text(strip=True)}题" if q_type_tag else ""

        # 2. 提取问题文本
        q_text_div = soup.find('div', class_='ts_title_text')
        if not q_text_div: return None
        q_text = q_text_div.get_text(strip=True)

        # 3. 提取选项和选中状态
        options_wrapper = soup.find('div', class_='options-wrapper')
        if not options_wrapper: return None
        
        options = {}
        selected_options = []
        # 找到所有选项的列表项 (li 标签)
        option_lis = options_wrapper.find_all('li', class_=True)

        for li in option_lis:
            # 提取选项字母，不假定只有 A-D。
            option_letter_span = li.find('span')
            text_content = option_letter_span.get_text(strip=True) if option_letter_span else li.get_text(strip=True)
            match = re.match(r'([A-Z])\.', text_content)
            if not match and option_letter_span: # 有时字母不在span里, 需要从li的完整文本匹配
                 match = re.match(r'([A-Z])\.', li.get_text(strip=True))

            if match:
                option_letter = match.group(1)
                
                # ======================= 【核心升级点】 =======================
                # 智能判断选项是图片还是文字
                img_tag = li.find('img')
                if img_tag and img_tag.has_attr('src'):
                    # 如果li标签内有<img>，则这是一个图片选项，我们使用图片的URL作为其内容。
                    option_content = img_tag['src']
                else:
                    # 否则，这是一个文字选项，我们提取其文本内容。
                    full_text = li.get_text(strip=True)
                    # 移除开头的 "A."、"B." 等，得到纯净的选项文本。
                    option_content = re.sub(r'^[A-Z]\.', '', full_text, count=1).strip()
                
                options[option_letter] = option_content
                
                # 通过检查li标签的class属性是否包含 'active' 来判断此选项是否被选中。
                classes = li.get('class', [])
                if any('active' in c for c in classes):
                    selected_options.append(option_letter)
        
        # 如果成功提取到所有关键信息，则构建并返回结果字典
        if q_num and q_text and options:
            return {
                "q_num": q_num,
                "q_type": q_type,
                "q_text": q_text,
                "options": options, # 选项内容可能是文本或图片URL
                "selected_options": sorted(selected_options) # 返回已排序的选中选项列表
            }
    except Exception as e:
        logger.error(f"解析HTML时发生严重错误: {e}", exc_info=True)
    return None

def _parse_text_data(clipboard_text):
    """
    【备用方案】解析纯文本格式的剪贴板内容。
    功能有限，无法识别图片选项和已选中状态。
    在当前版本中，此函数主要作为历史参考，因为HTML解析更优越。

    Args:
        clipboard_text (str): 从剪贴板获取的纯文本。

    Returns:
        dict or None: 解析成功则返回字典，否则None。
    """
    lines = [line.strip() for line in clipboard_text.split('\n') if line.strip()]
    q_info = {"options": {}}
    question_text_lines = []
    is_question_line = False
    for line in lines:
        match_q_num = re.search(r'^(第\d+题)\s*(单选|多选)', line)
        if match_q_num:
            q_info['q_num'] = match_q_num.group(1)
            q_info['q_type'] = f"{match_q_num.group(2)}题"
            is_question_line = True
            continue
        match_option = re.search(r'^([A-Z])\.(.*)', line)
        if match_option:
            is_question_line = False
            q_info['options'][match_option.group(1)] = match_option.group(2).strip()
            continue
        if is_question_line:
            question_text_lines.append(line)
    if question_text_lines:
        q_info['q_text'] = " ".join(question_text_lines)
    
    if 'q_text' in q_info and 'q_num' in q_info and q_info['options']:
        q_info['selected_options'] = []  # 纯文本模式无法获知选中状态
        return q_info
    return None

def get_clipboard_data_robust():
    """
    健壮的剪贴板数据获取和解析函数。
    它会模拟 "全选" (Ctrl+A) 和 "复制" (Ctrl+C)，然后优先尝试用HTML格式解析剪贴板内容。
    这是获取当前屏幕题目信息的主要入口点。

    Returns:
        dict or None: 成功解析则返回包含题目信息的字典，否则返回None。
    """
    if not ensure_target_active():
        return None

    if TARGET_MODE in ("uia_standalone", "standalone_html"):
        parsed_data = _get_uia_question_data()
        if parsed_data:
            if TARGET_MODE == "standalone_html":
                logger.info("UIA 控件树已恢复，切回精确控件模式。")
                globals()["TARGET_MODE"] = "uia_standalone"
            if parsed_data.get("page_state") == "complete":
                logger.info("✅ [UIA解析成功] 检测到答题完成页。")
            else:
                logger.info(
                    f"✅ [UIA解析成功] 题目: {parsed_data['q_num']}, "
                    f"选项={sorted(parsed_data['options'])}, "
                    f"已选={parsed_data['selected_options'] or '无'}"
                )
            return parsed_data
        if TARGET_MODE == "uia_standalone":
            logger.warning("UIA 控件树暂时不可用，尝试剪贴板 HTML 模式。")

    logger.info("正在通过剪贴板获取题目信息 (HTML模式)...")
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.CloseClipboard()
    except Exception as exc:
        logger.warning(f"清空旧剪贴板失败: {exc}")
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
    # 模拟键盘操作，确保题目区域被选中并复制
    pyautogui.hotkey('ctrl', 'a'); time.sleep(DELAY_AFTER_SELECT_ALL)
    pyautogui.hotkey('ctrl', 'c'); time.sleep(DELAY_AFTER_COPY)
    
    html_content = _get_html_from_clipboard()
    if not html_content:
        logger.error("❌ 未能从剪贴板获取HTML内容。请确保目标窗口支持HTML复制。")
        return None
        
    parsed_data = _parse_html_data(html_content)
    if parsed_data:
        if TARGET_MODE == "uia_standalone":
            logger.info("HTML 解析有效，后续切换到独立窗口 HTML 模式。")
            globals()["TARGET_MODE"] = "standalone_html"
        parsed_data.setdefault("source", "html")
        if parsed_data.get('page_state') == 'complete':
            logger.info("✅ [HTML解析成功] 检测到答题完成页。")
        else:
            logger.info(
                f"✅ [HTML解析成功] 题目: {parsed_data['q_num']}, "
                f"已选: {parsed_data['selected_options'] or '无'}"
            )
        return parsed_data
    else:
        plain_text = pyperclip.paste()
        if "请求失败" in plain_text or "请稍后再试" in plain_text:
            logger.error(f"检测到小程序网络错误提示: {plain_text.strip()}")
            return {
                "page_state": "request_error",
                "message": plain_text.strip(),
            }
        logger.error("❌ HTML内容解析失败，无法获取题目信息。")
        # 将解析失败的HTML内容保存到文件，以便于调试分析问题
        failed_html_path = os.path.join(LOG_DIR, f"failed_parse_{RUN_TIMESTAMP}.html")
        with open(failed_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.error(f"失败的HTML内容已保存至: {failed_html_path}")
        return None

# --- 逻辑函数 ---

def _position_page(anchor):
    """把页面移动到顶部或底部，并保持微信答题标签处于活动状态。"""
    if not ensure_target_active():
        return False
    _, _, width, height = SCREEN_REGION
    if width <= 0 or height <= 0:
        return False
    focus_pos = (
        int(round(width * PAGE_FOCUS_X_RATIO)),
        int(round(height * PAGE_FOCUS_Y_RATIO)),
    )
    click_at_region_pos(focus_pos)
    pyautogui.press(anchor)
    time.sleep(0.12)
    return True


def position_page_at_bottom():
    return _position_page('end')


def _capture_region_rgb():
    region_x, region_y, region_width, region_height = SCREEN_REGION
    virtual_x = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    virtual_y = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    virtual_right = virtual_x + win32api.GetSystemMetrics(
        win32con.SM_CXVIRTUALSCREEN
    )
    virtual_bottom = virtual_y + win32api.GetSystemMetrics(
        win32con.SM_CYVIRTUALSCREEN
    )
    visible_left = max(region_x, virtual_x)
    visible_top = max(region_y, virtual_y)
    visible_right = min(region_x + region_width, virtual_right)
    visible_bottom = min(region_y + region_height, virtual_bottom)
    if visible_right <= visible_left or visible_bottom <= visible_top:
        logger.warning("答题窗口完全位于可见屏幕外，无法截图")
        return None
    try:
        visible_image = np.array(pyautogui.screenshot(region=(
            visible_left,
            visible_top,
            visible_right - visible_left,
            visible_bottom - visible_top,
        )))
    except Exception as exc:
        logger.warning(f"截图失败，跳过本次视觉检测: {exc}")
        return None

    # 保留相对 SCREEN_REGION 的坐标系，屏外部分填黑。
    canvas = np.zeros((region_height, region_width, 3), dtype=np.uint8)
    offset_x = visible_left - region_x
    offset_y = visible_top - region_y
    canvas[
        offset_y:offset_y + visible_image.shape[0],
        offset_x:offset_x + visible_image.shape[1],
    ] = visible_image[:, :, :3]
    return canvas


def _detect_option_boxes(screen_rgb=None):
    """检测当前视口内完整或部分可见的灰色/蓝色圆角选项框。"""
    if screen_rgb is None:
        screen_rgb = _capture_region_rgb()
    if screen_rgb is None:
        return []
    height, width = screen_rgb.shape[:2]
    gray = cv2.cvtColor(screen_rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    gray_border = np.max(
        np.abs(screen_rgb.astype(np.int16) - 217), axis=2
    ) <= 10
    mask = np.where((edges > 0) | gray_border, 255, 0).astype(np.uint8)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)
    )
    contours, _ = cv2.findContours(
        mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )

    raw_boxes = []
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        center_x = x + box_width / 2
        if not (0.60 * width <= box_width <= 0.82 * width):
            continue
        if not (0.04 * height <= box_height <= 0.25 * height):
            continue
        if not (0.40 * width <= center_x <= 0.60 * width):
            continue
        raw_boxes.append((x, y, box_width, box_height))

    # Canny 通常会同时产生边框内外两个轮廓，按中心位置去重。
    boxes = []
    for box in sorted(raw_boxes, key=lambda item: (item[1], item[0])):
        x, y, box_width, box_height = box
        center = (x + box_width / 2, y + box_height / 2)
        duplicate_index = None
        for index, existing in enumerate(boxes):
            ex, ey, ew, eh = existing
            existing_center = (ex + ew / 2, ey + eh / 2)
            if (
                abs(center[0] - existing_center[0]) <= 8
                and abs(center[1] - existing_center[1]) <= 15
            ):
                duplicate_index = index
                break
        if duplicate_index is None:
            boxes.append(box)
        elif box_width * box_height > boxes[duplicate_index][2] * boxes[duplicate_index][3]:
            boxes[duplicate_index] = box

    if boxes:
        # 题干区域偶尔也会形成近似圆角框；真正选项框在同一页面等宽。
        max_width = max(box[2] for box in boxes)
        boxes = [box for box in boxes if box[2] >= max_width * 0.98]

    boxes.sort(key=lambda item: item[1])
    return [
        (int(round(x + box_width / 2)), int(round(y + box_height / 2)))
        for x, y, box_width, box_height in boxes
    ]


def _detect_option_circles(screen_rgb=None):
    """检测图形题左侧的单选/多选圆圈中心。"""
    if screen_rgb is None:
        screen_rgb = _capture_region_rgb()
    if screen_rgb is None:
        return []
    height, width = screen_rgb.shape[:2]
    gray = cv2.cvtColor(screen_rgb, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 1.5)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=100,
        param1=100,
        param2=28,
        minRadius=max(18, int(height * 0.014)),
        maxRadius=max(30, int(height * 0.025)),
    )
    if circles is None:
        return []
    centers = []
    for x, y, radius in np.round(circles[0]).astype(int):
        if not (0.05 * width <= x <= 0.22 * width):
            continue
        if not (0.04 * height <= y <= 0.96 * height):
            continue
        if any(abs(x - old_x) < 8 and abs(y - old_y) < 8 for old_x, old_y in centers):
            continue
        centers.append((int(x), int(y)))
    centers.sort(key=lambda item: item[1])
    return centers


def _visible_option_map(q_info, anchor):
    if anchor == 'middle':
        if not _position_page('home'):
            return {}
        pyautogui.press('pagedown')
        time.sleep(0.12)
    elif not _position_page(anchor):
        return {}
    centers = _detect_option_boxes()
    detector = 'border'
    if not centers:
        centers = _detect_option_circles()
        detector = 'circle'
    letters = sorted(q_info.get('options', {}).keys())
    if not centers or len(centers) > len(letters):
        logger.warning(f"{anchor} 视图选项框检测异常: {centers}")
        return {}
    if anchor == 'home':
        visible_letters = letters[:len(centers)]
    elif anchor == 'middle':
        visible_letters = letters[1:1 + len(centers)]
    else:
        visible_letters = letters[-len(centers):]
    mapping = dict(zip(visible_letters, centers))
    logger.info(f"{anchor} 视图动态选项坐标({detector}): {mapping}")
    return mapping


def _click_option_letters(option_letters, q_info):
    """在顶部/底部视图中找到并点击所有指定选项。"""
    if (q_info or {}).get("source") == "uia":
        for letter in option_letters:
            if not _click_uia_option_letter(letter):
                return False
            time.sleep(POST_TOUCH_DELAY)
        return True

    remaining = list(option_letters)
    for anchor in ('end', 'middle', 'home'):
        mapping = _visible_option_map(q_info, anchor)
        for letter in list(remaining):
            position = mapping.get(letter)
            if position is None:
                continue
            click_at_region_pos(position)
            time.sleep(POST_TOUCH_DELAY)
            remaining.remove(letter)
        if not remaining:
            return True
    logger.error(f"动态视图中找不到选项: {remaining}")
    return False


def _detect_submit_button(screen_rgb=None):
    """通过蓝色实心区域检测提交按钮，排除蓝色页头和选项边框。"""
    if screen_rgb is None:
        screen_rgb = _capture_region_rgb()
    if screen_rgb is None:
        return None
    height, width = screen_rgb.shape[:2]
    hsv = cv2.cvtColor(screen_rgb, cv2.COLOR_RGB2HSV)
    blue_mask = cv2.inRange(
        hsv,
        np.array([90, 80, 80], dtype=np.uint8),
        np.array([125, 255, 255], dtype=np.uint8),
    )
    count, _, stats, centroids = cv2.connectedComponentsWithStats(blue_mask)
    candidates = []
    for index in range(1, count):
        x, y, box_width, box_height, area = map(int, stats[index])
        if not (y > 0.45 * height):
            continue
        if not (0.20 * width < box_width < 0.85 * width):
            continue
        if not (35 < box_height < 0.25 * height):
            continue
        fill_ratio = area / float(box_width * box_height)
        if fill_ratio < 0.45:
            continue
        center_x, center_y = centroids[index]
        candidates.append((area, (int(round(center_x)), int(round(center_y)))))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def find_submit_button_with_scroll(q_num, screenshot_dir):
    if not position_page_at_bottom():
        return None, True
    position = _detect_submit_button()
    logger.info(f"动态提交按钮坐标: {position}")
    return position, True


def click_submit_button():
    if TARGET_MODE == "uia_standalone":
        if _click_uia_button("提交"):
            return True
        logger.error("UIA 中未找到“提交”按钮。")
        return False

    if not position_page_at_bottom():
        return False
    position = _detect_submit_button()
    if position is None:
        logger.error("未检测到蓝色提交按钮，拒绝盲点。")
        return False
    logger.info(f"点击动态提交按钮: {position}")
    click_at_region_pos(position)
    return True
def complete_quiz_task():
    """完成答题、完成验证，并关闭成功提示。"""
    global TASK_FINISHED
    if not ensure_target_active():
        logger.error("无法激活微信窗口，未能完成验证。")
        return False

    if TARGET_MODE == "uia_standalone":
        if not _click_uia_button("点击完成任务"):
            logger.error("UIA 中未找到“点击完成任务”按钮。")
            return False

        time.sleep(0.6)
        verification_invoked = False
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if _uia_page_has_text("解除成功"):
                break
            if not verification_invoked and _find_uia_button("点击完成验证"):
                if not _click_uia_button("点击完成验证"):
                    logger.error("“点击完成验证”执行失败。")
                    return False
                verification_invoked = True
            time.sleep(0.35)

        if not _uia_page_has_text("解除成功"):
            logger.error("完成验证后未检测到“解除成功”。")
            return False

        logger.info("已检测到“解除成功”。")
        if _find_uia_button("确认"):
            _click_uia_button("确认")
            time.sleep(0.2)
        TASK_FINISHED = True
        logger.info("完成验证成功，整个任务结束。")
        return True

    position = _detect_submit_button()
    if position is None:
        position_page_at_bottom()
        position = _detect_submit_button()
    if position is None:
        logger.error("完成页未检测到蓝色“点击完成任务”按钮，拒绝盲点。")
        return False
    logger.info(f"点击“点击完成任务”按钮: {position}")
    click_at_region_pos(position)

    time.sleep(0.6)
    for attempt in range(3):
        page_info = get_clipboard_data_robust()
        if page_info and page_info.get("page_state") == "complete":
            time.sleep(0.35)
            continue
        TASK_FINISHED = True
        logger.info("已离开答题完成页，整个答题任务结束。")
        return True

    logger.warning("点击后页面仍显示为答题完成页，请人工确认完成任务按钮状态。")
    return False
def find_available_options(q_info):
    """返回 HTML 中的完整选项集合；实际坐标在每次点击前动态检测。"""
    return {letter: None for letter in sorted(q_info.get('options', {}).keys())}


def validate_all_options_visible():
    """启动预检：确认当前题目、选项和提交按钮均可读取。"""
    logger.info("=" * 20 + " 开始初始环境校验 " + "=" * 20)
    time.sleep(INITIAL_VALIDATION_DELAY)
    q_info = get_clipboard_data_robust()
    if q_info and q_info.get("page_state") == "complete":
        logger.info("[校验结束] 当前已经是答题完成页。")
        return True
    if not q_info:
        logger.critical("[校验失败] 当前窗口没有可解析的题目。")
        return False

    if q_info.get("source") == "uia":
        submit_button = _find_uia_button("提交")
        if q_info.get("options") and submit_button is not None:
            logger.info(
                f"[校验通过] UIA 选项={sorted(q_info['options'])}, "
                f"提交按钮={submit_button.rectangle()}"
            )
            return True
        logger.critical(
            f"[校验失败] UIA 选项={sorted(q_info.get('options', {}))}, "
            f"提交按钮={submit_button}"
        )
        return False

    option_mapping = _visible_option_map(q_info, 'end')
    submit_pos = _detect_submit_button()
    if option_mapping and submit_pos:
        logger.info(
            f"[校验通过] 可见选项={option_mapping}, 提交按钮={submit_pos}"
        )
        return True
    logger.critical(
        f"[校验失败] 可见选项={option_mapping}, 提交按钮={submit_pos}"
    )
    return False
def initialize_and_activate():
    """定位并激活答题窗口；初始化阶段不点击网页内容。"""
    logger.info("正在定位并激活电脑版微信答题窗口...")
    return locate_and_activate_target_window()

def load_qa_bank():
    """在脚本启动时从JSON文件加载题库数据到全局变量 qa_bank。"""
    global qa_bank
    if not USE_QA_BANK:
        logger.info("配置为不使用题库，跳过加载。")
        return
    
    if os.path.exists(QA_BANK_FILE):
        try:
            with open(QA_BANK_FILE, 'r', encoding='utf-8') as f:
                qa_bank = json.load(f)
            logger.info(f"✅ 成功从 '{QA_BANK_FILE}' 加载 {len(qa_bank)} 条题目。")
        except Exception as e:
            logger.error(f"❌ 加载题库 '{QA_BANK_FILE}' 失败: {e}")
            qa_bank = {}
    else:
        logger.warning(f"⚠️ 题库文件 '{QA_BANK_FILE}' 不存在，将仅使用遍历模式答题。")
        qa_bank = {}

def dismiss_answer_feedback(expected_q_num=None):
    """检测并关闭答错后的中央确认弹窗，避免遮罩拦截后续点击。"""
    if TARGET_MODE == "uia_standalone":
        for button_text in ("确定", "知道了", "再试一次", "继续"):
            if _click_uia_button(button_text):
                time.sleep(0.15)
                return True

    screen_rgb = _capture_region_rgb()
    if screen_rgb is None:
        return False
    height, width = screen_rgb.shape[:2]
    white_mask = np.where(
        np.all(screen_rgb >= 242, axis=2), 255, 0
    ).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(white_mask)
    candidates = []
    for index in range(1, count):
        x, y, box_width, box_height, area = map(int, stats[index])
        center_x = x + box_width / 2
        if not (0.20 * width <= box_width <= 0.70 * width):
            continue
        if not (0.08 * height <= box_height <= 0.40 * height):
            continue
        if not (0.15 * height <= y <= 0.75 * height):
            continue
        if not (0.35 * width <= center_x <= 0.65 * width):
            continue
        candidates.append((area, (x, y, box_width, box_height)))
    if not candidates:
        return False
    _, (x, y, box_width, box_height) = max(
        candidates, key=lambda item: item[0]
    )
    confirm_pos = (
        int(round(x + box_width / 2)),
        int(round(y + box_height * 0.78)),
    )
    if expected_q_num:
        marker = _get_uia_page_marker()
        marker_q_num = marker.get("q_num") if marker else None
        if (
            not marker
            or marker.get("page_state") != "question"
            or marker_q_num != expected_q_num
        ):
            logger.info(
                "视觉弹窗点击前题号已变化或暂不可用，取消旧题点击: "
                f"expected={expected_q_num}, actual={marker_q_num or '未知'}"
            )
            return False
    logger.info(f"关闭答错确认弹窗: {confirm_pos}")
    click_at_region_pos(confirm_pos)
    time.sleep(0.15)
    return True


def _evaluate_transition_observation(observation, current_q_num, current_q_text):
    """把一次页面观测归类为成功、明确答错或证据不足。"""
    if not observation:
        return {
            "status": TRANSITION_UNKNOWN,
            "same_question": False,
            "reason": "页面没有可用标记",
        }

    page_state = observation.get("page_state")
    if page_state == "complete":
        return {
            "status": TRANSITION_SUCCESS,
            "same_question": False,
            "reason": "已进入答题完成页",
        }
    if page_state == "request_error":
        return {
            "status": TRANSITION_UNKNOWN,
            "same_question": False,
            "reason": "小程序请求失败",
            "request_error": True,
        }
    new_q_num = observation.get("q_num")
    if current_q_num and new_q_num:
        if new_q_num != current_q_num:
            return {
                "status": TRANSITION_SUCCESS,
                "same_question": False,
                "reason": f"题号已变化: {current_q_num} -> {new_q_num}",
            }
        if (
            observation.get("feedback_detected")
            and observation.get("feedback_action")
        ):
            return {
                "status": TRANSITION_WRONG,
                "same_question": True,
                "reason": "检测到明确的答错反馈",
            }
        return {
            "status": TRANSITION_UNKNOWN,
            "same_question": True,
            "reason": f"题号仍为 {current_q_num}",
        }

    if page_state == "feedback":
        return {
            "status": TRANSITION_WRONG,
            "same_question": True,
            "reason": "检测到独立答错反馈页",
        }

    new_q_text = observation.get("q_text")
    normalized_old_text = re.sub(r"\s+", "", current_q_text or "")
    normalized_new_text = re.sub(r"\s+", "", new_q_text or "")
    if (
        normalized_old_text
        and normalized_new_text
        and normalized_new_text != normalized_old_text
    ):
        return {
            "status": TRANSITION_SUCCESS,
            "same_question": False,
            "reason": "题号缺失，但题干已变化",
        }

    return {
        "status": TRANSITION_UNKNOWN,
        "same_question": False,
        "reason": "缺少题号或题干变化证据",
    }


def wait_for_next_question(current_q_num, current_q_text):
    """提交后等待确定证据，并返回 success/wrong/unknown 三态。"""
    logger.info(f"提交后等待 {FIXED_POST_SUBMIT_DELAY} 秒检查题号...")
    time.sleep(FIXED_POST_SUBMIT_DELAY)
    started_at = time.monotonic()
    normal_deadline = started_at + QUESTION_TRANSITION_TIMEOUT
    final_deadline = normal_deadline + QUESTION_TRANSITION_GRACE_TIMEOUT
    next_full_read_at = started_at + QUESTION_HTML_FALLBACK_INTERVAL
    next_feedback_check_at = started_at
    last_same_seen_at = None
    last_wait_log_at = 0.0
    grace_logged = False

    while True:
        now = time.monotonic()
        observations = []

        marker = _get_uia_page_marker()
        if marker:
            observations.append(marker)

        if now >= next_full_read_at:
            full_data = get_clipboard_data_robust()
            if full_data:
                observations.append(full_data)
            next_full_read_at = (
                time.monotonic() + QUESTION_HTML_FALLBACK_INTERVAL
            )

        for observation in observations:
            evidence = _evaluate_transition_observation(
                observation, current_q_num, current_q_text
            )
            if evidence.get("request_error"):
                dismiss_answer_feedback(current_q_num)
                raise RuntimeError(
                    "小程序请求失败，已停止本轮答题以避免误判答案。"
                )
            if evidence["status"] == TRANSITION_SUCCESS:
                logger.info(evidence["reason"])
                if observation.get("page_state") == "complete":
                    complete_quiz_task()
                return TRANSITION_SUCCESS
            if evidence["status"] == TRANSITION_WRONG:
                logger.info(evidence["reason"])
                feedback_action = observation.get("feedback_action")
                if not (
                    feedback_action and _click_uia_button(feedback_action)
                ):
                    dismiss_answer_feedback(current_q_num)
                return TRANSITION_WRONG
            if evidence["same_question"]:
                last_same_seen_at = time.monotonic()
                if last_same_seen_at >= next_feedback_check_at:
                    logger.info(
                        f"题号仍为 {current_q_num}，检查是否存在答错弹窗。"
                    )
                    if dismiss_answer_feedback(current_q_num):
                        return TRANSITION_WRONG
                    next_feedback_check_at = (
                        time.monotonic() + QUESTION_HTML_FALLBACK_INTERVAL
                    )

        now = time.monotonic()
        same_question_is_recent = (
            last_same_seen_at is not None
            and now - last_same_seen_at <= QUESTION_SAME_EVIDENCE_MAX_AGE
        )
        if now >= normal_deadline and not grace_logged:
            if same_question_is_recent:
                logger.info(
                    f"题号在 {QUESTION_TRANSITION_TIMEOUT:.1f} 秒内始终为 "
                    f"{current_q_num}，本次答案错误。"
                )
                dismiss_answer_feedback(current_q_num)
                return TRANSITION_WRONG
            grace_logged = True
            logger.warning(
                "正常等待期内题号仍不可用，进入慢加载保护期；"
                "保护期内不会使用上一题继续作答。"
            )

        if now >= final_deadline:
            if same_question_is_recent:
                logger.info(
                    f"慢加载保护结束时题号仍为 {current_q_num}，"
                    "本次答案错误。"
                )
                dismiss_answer_feedback(current_q_num)
                return TRANSITION_WRONG
            logger.warning(
                "慢加载保护结束后仍没有新题号、原题号或明确反馈，"
                "状态为证据不足。"
            )
            return TRANSITION_UNKNOWN

        if now - last_wait_log_at >= 1.0 and not observations:
            phase = "慢加载保护期" if grace_logged else "正常等待期"
            logger.info(f"提交后处于无题目过渡页（{phase}），继续等待...")
            last_wait_log_at = now
        time.sleep(QUESTION_TRANSITION_POLL_INTERVAL)

def write_solution_map_to_file():
    """在脚本结束时，将本次运行解出的所有题目和答案写入一个JSON文件。"""
    if not solved_questions:
        logger.info("没有成功解答任何题目，无需生成答案映射文件。")
        return
    map_file_path = os.path.join(SCREENSHOT_RUN_DIR, "solution_map.json")
    logger.info(f"正在将 {len(solved_questions)} 条解题记录写入答案映射文件: {map_file_path}")
    try:
        with open(map_file_path, 'w', encoding='utf-8') as f:
            # 使用 atexit 注册的函数会在程序退出时调用
            # indent=4 使得json文件格式化，易于阅读
            json.dump(solved_questions, f, ensure_ascii=False, indent=4)
        logger.info("答案映射文件写入成功。")
    except Exception as e:
        logger.error(f"写入答案映射文件失败: {e}")

# ============================ 【核心升级】带验证的解答函数 ============================

def _assert_question_context(q_info, observation, stage):
    """在执行旧题点击前后，拦截已经切换到新题或完成页的上下文。"""
    if not q_info or not observation:
        return
    expected_q_num = q_info.get("q_num")
    if not expected_q_num:
        return
    if observation.get("page_state") == "complete":
        raise StaleQuestionContext(
            f"{stage}时页面已进入完成页，停止使用 {expected_q_num} 的坐标。"
        )
    actual_q_num = observation.get("q_num")
    if actual_q_num and actual_q_num != expected_q_num:
        raise StaleQuestionContext(
            f"{stage}时题号已从 {expected_q_num} 变为 {actual_q_num}，"
            "停止使用上一题坐标。"
        )


def verify_and_click(options_to_select, options_pos, q_info=None, max_retries=2):
    """
    【高可靠性点击函数】点击指定选项后，通过读取剪贴板HTML来验证是否真的选中成功。
    如果验证失败，会进行重试。这是确保多选题正确选择的关键。

    Args:
        options_to_select (list): 期望被选中的选项列表，例如 ['A', 'C']。
        options_pos (dict): 各选项的屏幕坐标字典。
        max_retries (int, optional): 最大重试次数。 Defaults to 2.

    Returns:
        bool: 如果最终验证成功，返回True；否则返回False。
    """
    # 如果环境不支持HTML验证，则退化为直接点击，并假定成功。
    if not IS_WINDOWS:
        for opt in options_to_select:
            click_at_region_pos(options_pos.get(opt))
            time.sleep(POST_TOUCH_DELAY)
        return True

    expected_selection = set(options_to_select)
    
    for attempt in range(max_retries):
        logger.info(f"  -> 第 {attempt+1}/{max_retries} 次尝试点击并验证: {options_to_select}")
        _assert_question_context(q_info, _get_uia_page_marker(), "点击前")
        
        # 1. 先获取当前的选中状态
        current_data = q_info if q_info is not None else get_clipboard_data_robust()
        if not current_data:
            logger.warning("  -> 点击前无法获取剪贴板数据，将直接执行点击。")
            current_selection = set()
        else:
            current_selection = set(current_data.get('selected_options', []))
        
        # 单选项再次点击通常不会取消，直接点击目标即可替换当前选择。
        if current_data and current_data.get('q_type') == "单选题":
            click_order = [] if current_selection == expected_selection else sorted(expected_selection)
        else:
            to_select = expected_selection - current_selection
            to_deselect = current_selection - expected_selection
            click_order = sorted(to_deselect) + sorted(to_select)

        if click_order and not _click_option_letters(click_order, current_data or q_info):
            logger.warning("  -> 动态选项框点击失败，准备重试。")
            continue
        
        # 3. 验证结果
        time.sleep(DELAY_BEFORE_VERIFY_CLICK) # 等待UI反应
        verified_data = get_clipboard_data_robust()
        _assert_question_context(q_info, verified_data, "点击复核")
        actual_selection = set(verified_data.get('selected_options', [])) if verified_data else set()
        if q_info is not None and verified_data:
            q_info['selected_options'] = sorted(actual_selection)
            q_info['q_type'] = verified_data.get('q_type', q_info.get('q_type'))

        if actual_selection == expected_selection:
            logger.info(f"  -> ✅ 验证成功，选项 {sorted(list(expected_selection))} 已被正确选中。")
            return True
        else:
            logger.warning(f"  -> ❌ 验证失败。期望选中: {sorted(list(expected_selection))}, 实际选中: {sorted(list(actual_selection))}")
    
    logger.error(f"  -> ❌ 经过 {max_retries} 次尝试后，仍无法正确选中选项 {options_to_select}。")
    return False

def solve_with_qa_bank(q_info, options_pos, submit_pos):
    """
    使用已加载的题库尝试解答问题。
    它会先匹配问题文本，如果匹配成功，再匹配当前屏幕上的选项集合是否与题库中记录的一致。
    这种方式可以处理同一问题有不同选项顺序或内容变体的情况。

    Args:
        q_info (dict): 当前题目的信息。
        options_pos (dict): 可见选项的坐标。
        submit_pos (tuple): 提交按钮的坐标。

    Returns:
        str or list: 如果解答成功，返回正确答案列表。如果题库无答案或答案错误，返回 'FALLBACK' 请求使用遍历模式。
    """
    q_text = q_info['q_text']
    
    # 1. 检查题库中是否存在该问题文本
    if q_text not in qa_bank:
        logger.info(f"题库中未找到题目: '{q_text[:30]}...'")
        return 'FALLBACK'

    # 2. 图形选项在新版 UIA 中只有字母，没有可复用内容，禁止空值误命中。
    current_option_values = list(q_info['options'].values())
    if (
        any(not str(value).strip() for value in current_option_values)
        or len(set(current_option_values)) != len(current_option_values)
    ):
        logger.info("选项内容为空或重复，按图形题处理，不使用文字题库。")
        return 'FALLBACK'
    current_options_set = set(current_option_values)
    
    # 3. 遍历该问题的所有已知答案变种 (variants)
    for variant in qa_bank[q_text]:
        known_options_set = set(variant['options'])
        
        # 4. 如果当前选项集合与题库中某个变种的选项集合完全匹配
        if current_options_set == known_options_set:
            correct_answer_texts = variant['answer']
            logger.info(f"✅ 在题库中找到题目和完全匹配的选项集，预设答案: {correct_answer_texts}")

            # 将答案文本反向映射回选项字母 (A, B, C, D)
            options_text_to_letter = {v: k for k, v in q_info['options'].items()}
            letters_to_click = [options_text_to_letter[ans] for ans in correct_answer_texts if ans in options_text_to_letter]
            
            if not letters_to_click or len(letters_to_click) != len(correct_answer_texts):
                logger.error("严重错误：题库答案与当前选项无法完全对应，这不应该发生。")
                return 'FALLBACK'

            logger.info(f"--- [题库模式] 尝试解答，点击选项: {letters_to_click} ---")
            # 使用带验证的点击函数
            if verify_and_click(letters_to_click, options_pos, q_info):
                if not click_submit_button():
                    return 'FALLBACK'
                transition_result = wait_for_next_question(
                    q_info.get('q_num'), q_text
                )
                if transition_result == TRANSITION_SUCCESS:
                    logger.info(f"🎉 [题库模式] 解答成功！")
                    return correct_answer_texts # 返回正确答案
                if transition_result == TRANSITION_UNKNOWN:
                    raise TransitionEvidenceInsufficient(
                        f"{q_info.get('q_num')} 提交后状态证据不足，"
                        "禁止用上一题继续穷举。"
                    )
                if transition_result == TRANSITION_WRONG:
                    logger.warning(f"[题库模式] 提交后题目未刷新，题库答案可能已失效或错误。")
            
            # 如果题库答案错误，则回退到遍历模式
            logger.error(f"[题库模式] 解答失败。将回退到遍历模式。")
            return 'FALLBACK'
    
    # 遍历完所有变种，没有找到匹配的选项集
    logger.info(f"题库中虽有同名问题，但选项集不匹配。这是一个新变种，将使用遍历模式解答。")
    return 'FALLBACK'

def solve_single_choice(q_info, options_pos, submit_pos):
    """
    【遍历模式】解答单选题。依次尝试每个选项，直到成功。

    Args:
        q_info (dict): 当前题目信息。
        options_pos (dict): 可见选项坐标。
        submit_pos (tuple): 提交按钮坐标。

    Returns:
        list or None: 成功则返回包含正确答案文本的列表，失败则返回None。
    """
    logger.info(f"--- [遍历模式] 开始解答单选题: {q_info['q_num']} ---")
    # 按字母顺序尝试
    for option_name in sorted(options_pos.keys()):
        logger.info(f"尝试单选项 [{option_name}]...")
        # 使用带验证的点击
        if verify_and_click([option_name], options_pos, q_info):
            if not click_submit_button():
                continue
            transition_result = wait_for_next_question(
                q_info.get('q_num'), q_info['q_text']
            )
            if transition_result == TRANSITION_SUCCESS:
                correct_answer_text = q_info['options'][option_name]
                logger.info(f"🎉 [遍历模式] 单选题 [{q_info['q_num']}] 的正确答案是: [{correct_answer_text}]")
                return [correct_answer_text] # 以列表形式返回
            if transition_result == TRANSITION_UNKNOWN:
                raise TransitionEvidenceInsufficient(
                    f"{q_info.get('q_num')} 提交后状态证据不足，"
                    "禁止尝试下一个单选项。"
                )
            if transition_result == TRANSITION_WRONG:
                logger.info(f"选项 [{option_name}] 错误，继续...")
    logger.error(f"单选题 {q_info['q_text']} 在所有尝试后仍未解决。")
    return None

def solve_multiple_choice(q_info, options_pos, submit_pos):
    """
    【遍历模式】解答多选题。从2个选项的组合开始，依次尝试所有可能的组合。

    Args:
        q_info (dict): 当前题目信息。
        options_pos (dict): 可见选项坐标。
        submit_pos (tuple): 提交按钮坐标。

    Returns:
        list or None: 成功则返回包含所有正确答案文本的列表，失败则返回None。
    """
    logger.info(f"--- [遍历模式] 开始解答多选题: {q_info['q_num']} ---")
    option_letters = sorted(options_pos.keys())
    # 多选题至少选2个；优先全选，再逐级减少选项数量。
    start_size = 2 if len(option_letters) > 1 else 1
    
    for i in range(len(option_letters), start_size - 1, -1):
        # 生成所有长度为 i 的组合
        for combo in combinations(option_letters, i):
            current_combo = list(combo)
            logger.info(f"尝试多选组合: {current_combo}")
            
            if verify_and_click(current_combo, options_pos, q_info):
                if not click_submit_button():
                    continue
                transition_result = wait_for_next_question(
                    q_info.get('q_num'), q_info['q_text']
                )
                if transition_result == TRANSITION_SUCCESS:
                    correct_answer_texts = [q_info['options'][letter] for letter in current_combo]
                    logger.info(f"🎉 [遍历模式] 多选题 [{q_info['q_num']}] 的正确答案是: {correct_answer_texts}")
                    return correct_answer_texts
                if transition_result == TRANSITION_UNKNOWN:
                    raise TransitionEvidenceInsufficient(
                        f"{q_info.get('q_num')} 提交后状态证据不足，"
                        "禁止尝试下一个多选组合。"
                    )
                if transition_result == TRANSITION_WRONG:
                    logger.info(f"组合 {current_combo} 错误，继续...")
    
    logger.error(f"多选题 {q_info['q_text']} 在所有组合尝试后仍未解决。")
    return None

def record_successful_answer(q_info, correct_answer):
    """把成功答案同时写入运行记录和可复用主题库。"""
    q_text = q_info['q_text']
    current_option_values = list(q_info['options'].values())
    if (
        not correct_answer
        or any(not str(value).strip() for value in current_option_values)
        or len(set(current_option_values)) != len(current_option_values)
        or any(not str(value).strip() for value in correct_answer)
    ):
        logger.info("图形选项缺少可复用内容，本题不写入文字题库。")
        return
    current_options_sorted = sorted(current_option_values)
    new_entry = {"options": current_options_sorted, "answer": list(correct_answer)}

    solved_variants = solved_questions.setdefault(q_text, [])
    if not any(entry.get('options') == current_options_sorted for entry in solved_variants):
        solved_variants.append(new_entry)

    if not USE_QA_BANK:
        return

    variants = qa_bank.setdefault(q_text, [])
    replaced = False
    for index, entry in enumerate(variants):
        if sorted(entry.get('options', [])) == current_options_sorted:
            variants[index] = new_entry
            replaced = True
            break
    if not replaced:
        variants.append(new_entry)

    temp_path = f"{QA_BANK_FILE}.tmp"
    try:
        with open(temp_path, 'w', encoding='utf-8') as file:
            json.dump(qa_bank, file, ensure_ascii=False, indent=4)
        os.replace(temp_path, QA_BANK_FILE)
        logger.info(f"已学习并写回主题库: {q_text} -> {correct_answer}")
    except Exception as exc:
        logger.error(f"写回主题库失败: {exc}")
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


# ============================ 主循环 (已集成重试机制) ============================
def main_loop(max_questions=None):
    """脚本主循环；max_questions 可限制本次成功答题数量。"""
    last_question_key = None
    completed_questions = 0
    consecutive_read_failures = 0
    
    while True:
        if TASK_FINISHED:
            logger.info("完成任务按钮已点击，主循环立即结束。")
            break
        logger.info("\n" + "="*20 + " 新一轮检测循环 " + "="*20)
        q_info = get_clipboard_data_robust()
        
        if q_info and q_info.get('page_state') == 'complete':
            logger.info("检测到答题完成页，准备点击完成任务。")
            complete_quiz_task()
            break

        if not q_info or not q_info.get('q_text'):
            consecutive_read_failures += 1
            if consecutive_read_failures >= 6:
                logger.info("连续 6 次没有题目，判定答题已结束或页面已退出。")
                break
            logger.warning(
                f"暂时无法获取题目 ({consecutive_read_failures}/6)，"
                f"{RETRY_DELAY_ON_ERROR} 秒后重试。"
            )
            time.sleep(RETRY_DELAY_ON_ERROR)
            continue

        consecutive_read_failures = 0
        current_q_text = q_info['q_text']
        current_question_key = (q_info.get('q_num'), current_q_text)
        
        # 连续视频题可能共用题干，题号和题干共同标识当前题目。
        if current_question_key != last_question_key:
            logger.info(f"检测到新题目: {q_info['q_num']} - {current_q_text}")
            
            # 检查是否到达预设的停止题号
            if STOP_AT_QUESTION_NUM and q_info.get('q_num') == STOP_AT_QUESTION_NUM:
                logger.info(f"已到达预设的停止题号: {STOP_AT_QUESTION_NUM}。脚本将正常停止。")
                capture_region(filename=os.path.join(SCREENSHOT_RUN_DIR, f"{q_info['q_num']}_stop_screenshot.png"))
                break

            correct_answer = None
            restart_detection = False
            # ======================= 新增：重试循环 =======================
            for attempt in range(MAX_SOLVE_ATTEMPTS):
                logger.info(f"--- 开始第 {attempt + 1}/{MAX_SOLVE_ATTEMPTS} 次尝试解答 [{q_info['q_num']}] ---")

                try:
                    # 选项和提交按钮均在真正点击前动态定位，避免重复截图。
                    submit_pos = None
                    options_pos = find_available_options(q_info)
                    if not options_pos:
                        logger.error(f"在题目 {q_info['q_num']} 找不到任何选项，此次尝试失败。");
                        time.sleep(RETRY_DELAY_BETWEEN_ATTEMPTS)
                        continue # 继续下一次重试

                    # 开始解题
                    use_fallback = False
                    # 如果启用题库，优先使用题库
                    if USE_QA_BANK:
                        bank_result = solve_with_qa_bank(q_info, options_pos, submit_pos)
                        if bank_result == 'FALLBACK':
                            use_fallback = True
                        else:
                            correct_answer = bank_result

                    # 如果不使用题库，或者题库解答失败，则使用遍历模式
                    if not USE_QA_BANK or use_fallback:
                        if q_info['q_type'] == "单选题":
                            correct_answer = solve_single_choice(q_info, options_pos, submit_pos)
                        else: # 默认为多选题
                            correct_answer = solve_multiple_choice(q_info, options_pos, submit_pos)

                    # 如果成功解出答案，则跳出重试循环
                    if correct_answer:
                        logger.info(f"🎉 在第 {attempt + 1} 次尝试中成功解答 [{q_info['q_num']}]！")
                        break
                    else:
                        logger.warning(f"第 {attempt + 1} 次尝试解答失败。将在 {RETRY_DELAY_BETWEEN_ATTEMPTS} 秒后重试...")
                        time.sleep(RETRY_DELAY_BETWEEN_ATTEMPTS)
                except StaleQuestionContext as exc:
                    logger.warning(f"{exc} 立即重新读取当前题目。")
                    restart_detection = True
                    break
                except TransitionEvidenceInsufficient as exc:
                    logger.critical(f"{exc} 本轮安全停止，未继续点击旧题。")
                    return
            # ======================= 重试循环结束 =======================

            if restart_detection:
                continue

            # 在所有重试结束后，检查最终是否成功
            if correct_answer:
                record_successful_answer(q_info, correct_answer)
                completed_questions += 1
                if max_questions and completed_questions >= max_questions:
                    logger.info(
                        f"已成功完成 {completed_questions} 题，按参数要求停止。"
                    )
                    return

                # 更新上一题标识，防止重复解答。
                last_question_key = current_question_key
            else:
                # 如果所有重试都失败了，才终止脚本
                logger.critical(f"题目 {q_info['q_num']} 在 {MAX_SOLVE_ATTEMPTS} 次尝试后仍未能成功解答，脚本终止！")
                break
        else:
            logger.info(f"题目未变({q_info.get('q_num', '未知')})，等待{POLLING_INTERVAL_NO_CHANGE}秒..."); 
            time.sleep(POLLING_INTERVAL_NO_CHANGE)

# ============================ 程序入口 ============================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Honor-Unban 自动答题")
    parser.add_argument(
        "--max-questions",
        type=int,
        default=None,
        help="成功回答指定题数后退出；默认持续运行",
    )
    args = parser.parse_args()

    try:
        # 1. 加载题库（如果启用）
        load_qa_bank()

        # 2. 初始化并激活窗口
        if not initialize_and_activate():
            exit()

        # 3. 运行环境预检
        if not validate_all_options_visible():
            exit()
        
        # 4. 进入主循环
        main_loop(args.max_questions)

    except pyautogui.FailSafeException:
        # pyautogui的紧急停止机制：将鼠标快速移动到屏幕左上角
        logger.critical("Fail-Safe触发！鼠标移动到屏幕左上角，脚本已紧急停止。")
    except Exception as e:
        # 捕获所有其他未预料到的异常
        logger.exception("脚本运行过程中发生未处理的异常！")
    finally:
        # 无论脚本是正常结束还是异常中断，都尝试保存已解出的答案
        _set_target_topmost(False)
        write_solution_map_to_file()
        logger.info("脚本执行结束。")
