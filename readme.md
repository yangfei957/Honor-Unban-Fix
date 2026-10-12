# Honor-Unban-Fix 桌面端答题助手（二次修复版）

这是一个运行在 Windows 桌面端的微信小程序答题自动化工具。脚本面向“腾讯游戏安全中心”答题页面，负责读取题目、匹配题库、选择答案、提交结果，并在答题结束后完成页面上的后续验证操作。

## 点个 Star，给维护者加点动力

如果这个修复版帮你少走了弯路，欢迎顺手点一下右上角的 **Star**。
Star 不会让错误答案自动变正确，但会让维护者在下次页面改版时少叹两口气，
修复速度也可能获得一点非常不严谨的精神加成。

稳定版本和更新说明请查看 [Releases](https://github.com/yangfei957/Honor-Unban-Fix/releases)。

## 项目来源

本仓库是基于以下项目进行兼容性修复和功能维护的**非官方二次修复版**：

- 原项目：[guihuashaoxiang/Honor-Unban](https://github.com/guihuashaoxiang/Honor-Unban)

本仓库并非原作者发布的官方后续版本，也不代表原作者立场。原项目已有代码、资源及相关权利归原作者和相应权利人所有；本仓库新增的修复内容仅用于技术研究和本地测试。使用、修改或再分发时，请同时遵守原项目声明、适用许可及第三方依赖许可。

## 使用声明

本项目仅供 Python、Windows UI Automation、剪贴板 HTML 解析和桌面自动化技术研究使用。

- 请勿将本项目用于商业服务、破坏平台规则或其他违法违规用途。
- 自动化操作可能违反相关软件或服务的用户协议，使用者应自行确认规则并承担相应风险。
- 页面结构、风控策略和客户端行为可能随时变化，本项目不承诺永久可用或完全准确。
- 脚本不会要求或保存微信、QQ、游戏账号或 GitHub 密码。

## 本修复版的主要改动

- 兼容新版独立 Chromium 小程序窗口和旧版微信标签页。
- 启动时自动定位“腾讯游戏安全中心”窗口，无需固定窗口位置。
- 优先使用 Windows UI Automation 读取题号、题型、选项和选中状态。
- UIA 暂时不可用时，可回退到剪贴板 HTML 解析，并在 UIA 恢复后自动切回。
- 根据选项文字内容匹配题库，不依赖可能被打乱的 A、B、C、D 顺序。
- 点击后复核页面实际选中项，减少坐标偏差或漏选造成的错误提交。
- 使用“提交前后题号变化”作为答题成功的主要判断依据。
- 支持单选题、多选题、长页面滚动和图形选项的受控遍历。
- 未命中题库时按题型遍历候选答案；成功后将文字题答案写回题库。
- 遇到网络请求失败或页面证据不足时停止当前流程，避免继续盲点。
- 答题结束后自动执行“点击完成任务”“点击完成验证”和“确认”。
- 支持通过 `--max-questions` 限制单次运行成功答题数量，便于调试。

## 工作流程

```text
定位答题窗口
    ↓
读取题号、题型、题干、选项和选中状态
    ↓
按题干与选项内容查询 master_qa_bank.json
    ↓
命中题库：按答案内容映射到当前选项
未命中：根据单选/多选规则受控遍历
    ↓
点击选项并复核实际选中状态
    ↓
点击提交，检查题号是否变化
    ↓
成功则记录答案并进入下一题
    ↓
完成全部题目和最终验证
```

## 运行环境

- Windows 10 或 Windows 11
- 64 位 Python 3.14（已在 Python 3.14.6 上从空环境验证）
- Windows 桌面版微信
- 可在桌面微信中正常打开的“腾讯游戏安全中心”答题页面

## 安装

```powershell
git clone https://github.com/yangfei957/Honor-Unban-Fix.git
cd Honor-Unban-Fix

python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --only-binary="numpy,opencv-python" -r requirements.txt
```

不需要激活虚拟环境；文档中所有命令都显式使用项目内的
`.venv\Scripts\python.exe`，避免把依赖装到全局 Python 或其他虚拟环境。

安装后先执行环境自检：

```powershell
.\.venv\Scripts\python.exe -c "import sys; print('Python:', sys.version); import numpy; print('NumPy:', numpy.__version__); import cv2; print('OpenCV:', cv2.__version__); import pyautogui, pywinauto, win32gui; from bs4 import BeautifulSoup; print('Imports: OK')"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest tools.test_transition_state -v
```

自检应输出 `NumPy: 2.5.1`、`OpenCV: 5.0.0`、`Imports: OK`，
`pip check` 应输出 `No broken requirements found.`，单元测试应全部通过。

主要依赖包括：

- `pywinauto`：窗口定位和 UI Automation 控件访问
- `pywin32`：窗口消息与 Windows 剪贴板访问
- `beautifulsoup4`：剪贴板 HTML 解析
- `pyautogui`：截图及兼容模式下的桌面输入
- `opencv-python`、`numpy`：按钮和选项区域的图像检测

项目只使用 `opencv-python`，不依赖 `airtest`、`opencv-contrib-python`
或任何 OpenCV headless 包。这些包都会提供同名的 `cv2`，混装后容易
出现 NumPy ABI 冲突或导入到错误的 OpenCV 二进制文件。

## 使用方法

1. 登录桌面版微信。
2. 打开“腾讯游戏安全中心”小程序并进入实际答题页面。
3. 保持答题窗口可见，不要最小化或被系统锁屏遮挡。
4. 在项目目录运行：

```powershell
.\.venv\Scripts\python.exe auto_solver_refactored.py
```

调试时可以只允许脚本成功回答指定数量的题目：

```powershell
.\.venv\Scripts\python.exe auto_solver_refactored.py --max-questions 1
```

脚本启动后会先进行只读环境检查。只有成功识别题目、选项和提交控件后，才会进入答题流程。

## 题库说明

题库文件为 `master_qa_bank.json`。

- 题库答案保存的是**选项内容**，不是固定选项字母，因此可以适应选项顺序变化。
- 同一题干可以保存多个选项集合变体。
- 文字题成功后会自动更新对应题库记录。
- 图形题在无法获得稳定选项内容时不会写入文字题库，避免空内容污染数据。
- 每次运行还会在对应的截图目录生成 `solution_map.json`，用于保留本轮成功答案记录。

提交新的题库数据前，建议先检查题干、选项集合和答案内容是否属于同一道题，尤其要注意题干相同但选项不同的视频题。

## 项目结构

```text
Honor-Unban-Fix/
├── AGENTS.md                   # AI 与开发者接手指南
├── auto_solver_refactored.py   # 主程序
├── master_qa_bank.json         # 文字题题库
├── requirements.txt            # Python 依赖
├── templates/                  # 历史模板资源（当前主程序不加载）
├── tools/                      # 坐标、合并和解析辅助工具
├── logs/                       # 运行日志（自动生成）
└── screenshots/                # 调试截图和答案记录（自动生成）
```

## 开发文档

需要在另一台电脑上继续开发，或交给 AI 编程工具接手时，请先阅读
[AGENTS.md](AGENTS.md)。其中记录了当前架构、关键状态机约束、题库结构、
测试命令、真题调试流程、已知限制和 Git 提交边界。

## 常见问题

### `numpy.core.multiarray failed to import`

这表示旧环境中混装了多套 OpenCV，或 OpenCV 与 NumPy 使用了不同
ABI。最简单可靠的处理是删除旧 `.venv`，然后按上面的“安装”步骤
重新创建。

如果必须修复现有虚拟环境，执行：

```powershell
.\.venv\Scripts\python.exe -m pip uninstall -y airtest opencv-python opencv-contrib-python opencv-python-headless opencv-contrib-python-headless numpy
.\.venv\Scripts\python.exe -m pip install --only-binary="numpy,opencv-python" -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

最后重新执行安装段落中的环境自检。`pip list` 中只应有
`opencv-python 5.0.0.93`，不应再出现 `opencv-contrib-python`、
`opencv-python-headless` 或 `airtest`。

### 找不到答题窗口

确认桌面微信中的目标页面已经打开，窗口标题为“腾讯游戏安全中心”。不要只停留在微信聊天页面，也不要最小化小程序窗口。

### UIA 控件树偶尔读取不到

脚本会尝试回退到剪贴板 HTML 模式。若 HTML 也无法解析，请确认当前页面允许使用 `Ctrl+A`、`Ctrl+C` 复制出题目内容，并检查最新日志。

### 点击后没有提交或选项数量不正确

脚本会复核选中状态并拒绝在证据不足时提交。请查看 `logs/` 中最新日志，确认识别到的题号、选项集合、选中集合和提交按钮坐标。

### 出现“请求失败，请稍后再试”

这通常是小程序网络请求或服务端状态异常。修复版会停止本轮操作，避免把网络失败误判为答案错误。恢复网络或重新进入答题页面后再运行脚本。

### 如何紧急停止

可在运行脚本的终端按 `Ctrl+C`。使用 PyAutoGUI 兼容路径时，也可以将鼠标快速移动到屏幕左上角触发 Fail-Safe。

## 反馈建议

提交问题时建议附上以下信息，并提前删除账号、昵称等个人信息：

- Windows 和桌面微信版本
- 出错题号及题型
- `logs/` 中对应时间段的日志
- 必要的页面截图
- 是否使用 UIA 或剪贴板 HTML 模式

请勿在 Issue、日志或截图中公开账号凭据、Cookie、访问令牌或其他敏感信息。
