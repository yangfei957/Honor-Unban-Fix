# Honor-Unban-Fix 开发接手指南

本文面向后续维护者和 AI 编程代理。开始修改前先阅读本文件和
`readme.md`，再检查当前工作树，不要根据旧版项目或历史聊天记录猜测
当前实现。

## 项目定位

- 运行平台：Windows 桌面端。
- 目标页面：桌面微信中的“腾讯游戏安全中心”答题页面。
- 主程序：`auto_solver_refactored.py`。
- 上游项目：`https://github.com/guihuashaoxiang/Honor-Unban`。
- 本修复版仓库：`https://github.com/yangfei957/Honor-Unban-Fix`。
- 当前实现以 Windows UI Automation（UIA）为主，剪贴板 HTML 和
  OpenCV 为后备方案。

本项目只维护桌面端流程。旧的 Android 无障碍实验项目不在本仓库中，
不要把 Android、OCR 或本地大模型方案重新混入这里，除非用户明确要求。

## AI 开始工作前

1. 运行 `git status -sb`，先区分源码改动和本地运行产物。
2. 阅读 `readme.md`、本文件以及相关函数，不要直接重写主流程。
3. 查看最近提交：

   ```powershell
   git log --oneline --decorate -8
   ```

4. 使用项目虚拟环境，不要随意更换全局 Python：

   ```powershell
   .\.venv\Scripts\python.exe --version
   .\.venv\Scripts\python.exe -m pip list
   ```

5. 所有自动化实测先使用 `--max-questions 1`。确认日志、点击和切题都正确
   后，才允许扩大运行范围。
6. 命令默认设置 45 秒超时。长时间运行的答题脚本应单独启动并持续读取
   输出，不要让一次 shell 调用无限等待。
7. 不要删除、回滚或提交用户尚未确认的题库、日志、截图和运行记录。

## 安装与启动

在新电脑上：

```powershell
git clone https://github.com/yangfei957/Honor-Unban-Fix.git
cd Honor-Unban-Fix
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

当前依赖未锁定精确版本。遇到跨电脑差异时，先记录 Python 和依赖版本，
不要立即通过大范围重构规避环境问题。

运行前需要：

- 登录 Windows 桌面版微信。
- 打开“腾讯游戏安全中心”小程序。
- 进入真实答题页并保持窗口可见。
- 不要最小化窗口、锁屏或让其他窗口持续遮挡它。

单题调试：

```powershell
.\.venv\Scripts\python.exe auto_solver_refactored.py --max-questions 1
```

持续运行：

```powershell
.\.venv\Scripts\python.exe auto_solver_refactored.py
```

紧急停止使用 `Ctrl+C`。PyAutoGUI 路径还支持把鼠标移到屏幕左上角触发
Fail-Safe。

## 代码结构

### 窗口定位

- `locate_and_activate_target_window()`：
  - 优先查找标题为“腾讯游戏安全中心”的独立 Chromium 窗口。
  - 新版窗口模式为 `uia_standalone`。
  - 旧版微信标签页模式为 `legacy_html`。
- `ensure_target_active()`：确认窗口句柄、区域和前台状态。
- `SCREEN_REGION` 始终保存目标窗口的当前屏幕区域。

不要重新引入硬编码的绝对屏幕坐标。窗口移动或缩放后，坐标必须来自 UIA
控件边界、动态区域检测或相对窗口区域。

### 页面读取

读取优先级如下：

1. `_get_uia_question_data()` 获取完整题号、题型、题干、选项、选中状态和
   UIA 控件坐标。
2. `_get_uia_page_marker()` 在提交后的切页阶段快速读取题号、完成页和错误
   标记，不要求完整控件树。
3. `get_clipboard_data_robust()` 在 UIA 不完整时使用 `Ctrl+A`、`Ctrl+C`
   读取 HTML。
4. `_parse_html_data()` 和 `_parse_text_data()` 负责后备解析。

独立窗口中 UIA 暂时消失通常是 Chromium 正在切页，不等同于答错，也
不等同于页面结束。

核心题目对象 `q_info` 的常用字段：

```python
{
    "source": "uia",                 # uia / html / uia_marker
    "page_state": "question",        # question / complete / request_error
    "q_num": "第23题",
    "q_type": "单选题",              # 单选题 / 多选题
    "q_text": "题干",
    "options": {"A": "选项内容"},
    "selected_options": ["A"],
    "option_positions": {"A": (x, y)},
}
```

并非所有读取路径都会提供全部字段。使用字段前应通过 `get()` 检查。

### 选项定位与点击

- `find_available_options()`：入口函数。
- UIA 可用时，优先点击对应 `ListItem` 控件。
- `_detect_option_boxes()` 和 `_detect_option_circles()`：OpenCV 后备检测。
- `_visible_option_map()`：根据当前页面可见区域映射选项。
- `verify_and_click()`：点击后重新读取选中状态，确保实际集合与目标集合
  一致。
- `_assert_question_context()`：点击前后校验题号，防止新题出现后继续使用
  上一题坐标。

必须保持以下约束：

- 答案字母只用于本轮点击，不能作为可复用题库答案。
- 多选题提交前必须确认实际选中集合。
- 页面已经切换时必须丢弃旧的 `q_info` 和坐标。
- 图形选项缺少稳定文字时，不得写入文字题库。

### 题库与解题

- `load_qa_bank()`：加载 `master_qa_bank.json`。
- `solve_with_qa_bank()`：按题干和完整选项内容集合匹配。
- `solve_single_choice()`：题库未命中后的单选遍历。
- `solve_multiple_choice()`：题库未命中后的多选组合遍历，优先全选，再
  逐级减少选项数。
- `record_successful_answer()`：只有确认切到下一题后才学习答案。

题库保存选项内容，不保存固定字母。选项顺序每次可能变化。

题库结构：

```json
{
  "题干": [
    {
      "options": ["选项内容1", "选项内容2"],
      "answer": ["正确选项内容"]
    }
  ]
}
```

同一题干可以有多个选项集合变体。修改题库时必须同时核对题干、完整选项
集合和答案内容。

### 提交与切题状态机

`wait_for_next_question()` 返回三种状态：

- `TRANSITION_SUCCESS`：题号变化、题干明确变化或进入完成页。
- `TRANSITION_WRONG`：检测到明确答错反馈，或经过稳定等待后仍确认是同一
  题号。
- `TRANSITION_UNKNOWN`：UIA、HTML、题号和反馈均不足以判断。

当前时间参数：

- 提交后固定等待：1 秒。
- 正常切题等待：10 秒。
- 慢加载保护：额外 10 秒。
- UIA 标记轮询：0.2 秒。
- HTML 后备读取：约每 1 秒一次。

关键不变量：

- `UNKNOWN` 绝不能当作 `WRONG`。
- `UNKNOWN` 时不得使用旧题继续穷举。
- 题号变化优先判成功。
- 题号相同本身不会立即判错；先检查明确反馈和答错弹窗。
- UIA 暂时不可用只是过渡状态。

`TransitionEvidenceInsufficient` 用于安全停止旧题流程；
`StaleQuestionContext` 用于重新读取已经变化的页面。

### 完成任务

`complete_quiz_task()` 负责答题结束后的按钮链，包括“点击完成任务”、
“点击完成验证”和确认操作。完成页是成功状态，不要把它当成读取失败。

## 测试与检查

状态机回归测试：

```powershell
.\.venv\Scripts\python.exe -m unittest tools.test_transition_state -v
```

当前测试覆盖：

- 题号变化判成功。
- 同题号不会立即误判。
- UIA 空白约 6 秒后出现下一题。
- 明确答错反馈和视觉弹窗。
- 慢加载结束仍无证据时返回 `UNKNOWN`。
- 新题出现后拒绝旧题坐标。
- `UNKNOWN` 时不尝试下一个答案。

语法检查：

```powershell
.\.venv\Scripts\python.exe -m py_compile `
  .\auto_solver_refactored.py `
  .\tools\test_transition_state.py
```

提交前检查：

```powershell
git diff --check
git status --short
```

不要使用 `python -m unittest discover`。`tools/test_rtf_parser.py` 名称虽以
`test_` 开头，但它是持续监听剪贴板的诊断工具，不是单元测试。

## 真机桌面实测协议

每次修改点击、提交、切题或题库学习逻辑后：

1. 让用户打开真题页面。
2. 运行 `--max-questions 1`。
3. 记录提交前题号、题型、选项、预期答案和已选集合。
4. 提交后观察日志中的题号变化、答错反馈或 `UNKNOWN`。
5. 截图复核脚本实际点击的选项。
6. 确认题库只在成功切题后更新。
7. 有异常立即停止，不要为了“跑完”而扩大重试或盲点范围。

必要时查看最新文件：

```powershell
Get-ChildItem .\logs -Filter *.log |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 3
```

重点日志关键词：

- `UIA 控件树暂时不可用`
- `题号已变化`
- `慢加载保护期`
- `状态为证据不足`
- `关闭答错确认弹窗`
- `停止使用上一题坐标`
- `已学习并写回主题库`

## 运行产物与 Git 边界

默认只提交经过确认的源码、测试、模板和文档。

通常不要提交：

- `.venv/`
- `__pycache__/`、`*.pyc`
- `logs/`
- `screenshots/`
- `live_solver_*.log`
- 根目录临时截图
- `*.rej`
- 剪贴板诊断导出

`master_qa_bank.json` 是运行时可学习数据。工作树中出现修改时，不要默认
回滚，也不要默认提交；先让用户确认这些新答案是否经过人工复核。

工作树可能长期包含调试产物。不要使用 `git add -A`，应显式暂存本次任务
涉及的文件：

```powershell
git add -- path\to\file1 path\to\file2
```

不要执行 `git reset --hard`、`git checkout -- .` 或删除用户运行数据。

## 已知限制

- `requirements.txt` 未固定版本，跨电脑可能出现依赖差异。
- 微信和小程序更新后，窗口类名、控件类型和 HTML 结构都可能变化。
- UIA 在 Chromium 切页期间可能短暂为空。
- HTML 后备模式比 UIA 慢，频繁调用会显著降低答题速度。
- 图形题没有稳定文字内容，当前不会学习到文字题库。
- OpenCV 后备检测依赖窗口可见、缩放和页面视觉样式。
- `tools/test_rtf_parser.py` 是交互式诊断脚本，会持续运行直到手动停止。

## 修改时优先定位

- 找不到窗口：`locate_and_activate_target_window()`。
- 题号、题型或选项缺失：`_get_uia_question_data()`、
  `_parse_html_data()`。
- 提交后误判：`_get_uia_page_marker()`、
  `_evaluate_transition_observation()`、`wait_for_next_question()`。
- 点击错位或漏选：`find_available_options()`、`_click_option_letters()`、
  `verify_and_click()`。
- 提交按钮或最终按钮：`click_submit_button()`、
  `complete_quiz_task()`。
- 题库误命中或未学习：`solve_with_qa_bank()`、
  `record_successful_answer()`。

修改应尽量局部，先补回归测试，再做单题真机验证。不要用延长所有等待时间
掩盖状态判断问题。

## 给下一位 AI 的推荐任务描述

可以在新电脑上这样开始：

```text
请先阅读仓库根目录 AGENTS.md 和 readme.md，运行 git status -sb，
不要修改或提交现有题库、日志和截图。先复现问题并读取最新日志，再做局部
修复；状态机测试必须通过，真题测试先使用 --max-questions 1。
```
