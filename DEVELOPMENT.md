# DEVELOPMENT.md — 开发与验证约定

给要改这个项目的人（和 AI agent）。这里只放**长期有效**的东西：约定、流程、以及踩过的坑。
任务进度、某次排查的经过、一次性结论不写在这里。

写之前先问一句：这是"以后每次都得遵守的规则"，还是"这次发生了什么"？后者不进这个文件。

---

## 1. 项目形态

- 单包 Python 桌面应用，唯一可导入包是 `afterframe/`。
- **无构建配置、无测试框架、无 CI**。验证靠手动启动 + 临时脚本（用完即删）。
- 运行依赖只有 PySide6 与 psutil；音频解码另需 `ffmpeg`（见 README「依赖」）。

模块职责（**新增或改名模块后要同步这张表**）：

```
afterframe/
├── __init__.py         # 包声明与 __version__（版本号的唯一来源）
├── constants.py        # 尺寸、颜色、动画参数、应用信息、设置键、字体
├── theme.py            # 逐页面的侧边栏/标题栏配色与渐变过渡
├── window.py           # 主窗口、启动动画与擦除过渡、弹簧拖拽、最小化动画
├── page_stack.py       # 侧边栏 + 页面切换动画容器
├── dashboard.py        # 系统监控仪表盘、冷灰玻璃卡片与详情面板
├── settings_page.py    # 设置页（音乐目录 / PCM 引擎 / 启动过渡 / 磨砂档位 / 悬停标签）
├── settings_store.py   # 偏好的存储与可写性回退（QSettings 写失败时不报错也不落盘）
├── toy_page.py         # 音乐律动棋盘格 + 播放器界面 + 歌词 + 黑胶唱片交互
├── elastic_slider.py   # 弹簧滑块模型（音乐页的进度/音量条与设置页的磨砂档位共用）
├── scratch_engine.py   # PCM 转盘音频引擎（ffmpeg 解码 + QAudioSink，真倒放搓碟）
├── ncm.py              # 网易云 .ncm 外壳解析（纯标准库 AES + 密钥流），解成临时 flac
├── media_log.py        # 压掉媒体后端的日志噪音（FFmpeg 流清单）
├── color_extractor.py  # 封面取色（调色板 / 主色 / 压暗），驱动音乐页配色
└── main.py             # 应用入口

run.py                  # 便捷启动脚本
requirements.txt        # PySide6 + psutil
```

## 2. 改完必做的三步

```powershell
python -m py_compile <改动文件>
```

2. **逐个 `import` 全部模块**——能查出 `py_compile` 查不出的问题，最典型的是
   "新增常量忘了加进使用处的 `from .constants import (...)` 列表"。
3. **启动应用 8–10 秒**，确认存活且 stderr 里没有 `Traceback`。

配套规矩：

- 临时脚本用 `_` 前缀，**用完立即删除**，不要提交。
- 调外部命令（git / python / ffmpeg）不要设 `$ErrorActionPreference = 'Stop'`：git 把正常信息写在
  stderr 上，会被当成致命错误而中断脚本；成败看 `$LASTEXITCODE`。反过来，排查时也别用 `2>$null`
  把 stderr 吞掉——崩溃线索往往只在那里。
- **判断"进程崩了"不能只看退出码**：手动关窗时退出码也可能是 1 而日志干净。看 stderr 里有没有
  `Traceback` / `QPaintDevice` / abort。
- **改文本要用编辑工具，不要用 shell 重写文件**：PowerShell 这类 shell 会按本地代码页读写，把 UTF-8
  的中文写成乱码，还可能顺手把整份文件的换行改成 CRLF。这类损坏不报错，只是内容悄悄变了。

## 3. 测量纪律（探针很容易给出错误结论）

- **探针必须有"牙"**：先证明"目标行为在探针里确实能发生"，再断言"它没有发生"。落在空处的探针会
  永远通过，把 bug 说成"不存在"。
- **优先断言性质/不变式**（例如"整圈必为 360°"），而不是手算的具体数字。
- **比较两个版本/强度时固定测量面**（同一图层、同一尺寸、同一 dpr），否则两个变量一起动。
- **参数"看起来合理"不等于它在生效**：改观感参数时做一次反向验证——推到极值必须看到明显变化，
  变化为 0 就说明它被覆盖了或根本没走到。同理，若某段渲染代码"改了却毫无像素变化"，它很可能是
  死代码，不要留着当装饰。
- **中间产物要落盘或打印后再下结论**（音频流、渲染图、关键标量），别靠推理补空白。
- 涉及播放头、动画、节流、时序的 bug，**必须用真实后端 + 真实音频文件复现**：替身引擎会恰好绕开
  唯一出问题的那条路径。

### 3.1 离屏（offscreen）平台的三个坑

用 `QT_QPA_PLATFORM=offscreen` 做无头验证很方便，但它和真机**不是同一套后端**：

- `devicePixelRatioF()` 恒为 1。依赖 dpr 的代码（纹理瓦片、按设备像素生成的遮罩等）在离屏下走的是
  另一条分支——**涉及 dpr 的量必须按真实 dpr 复核**，别凭离屏结果下结论。
- 测绘制开销时，若目标是 `QPixmap`，必须建成设备像素（`QPixmap(w*dpr, h*dpr)` +
  `setDevicePixelRatio(dpr)`，再按逻辑尺寸绘制）。在 DPR=1 下量会**低估约 6 倍**。
- **字体数据库可能是空的**：`QFontDatabase.families()` 返回 0，文字会画成空心方框，
  且字体相关的日志/行为都不会出现。**"字体相不相关"的问题在离屏下验不了。**

## 4. 代码层面的硬约束（踩过才知道）

- 新增常量必须**同时**改两处：`constants.py`（或所在模块顶部）与使用处的 `import` 列表。
- `QPainter` 未 `end()` 时抛异常 = 进程 abort 且**没有 Python 回溯**（症状是"直接崩溃、什么都没
  打印"）——此时必须看 stderr。
- `setFixedSize()` 把 min/max 都钉死，`QWidget.setGeometry()` 的尺寸动画会被夹回去；要做尺寸动画
  只能固定宽度、放开高度。
- 弹窗类子控件要 `event.accept()` 吞掉 press（否则事件上传到父页面，会命中弹窗下面的东西）；
  **只吞 press，不吞 release**，否则从页面起手的拖动无法在弹窗上收尾。
- 绘制顺序即真相：任何不透明填充/贴图都会盖掉之前画的白洗、柔光之类。**参数不生效先怀疑顺序。**
- 尺寸变化时的每帧重建，先问"这一帧真的需要重建吗"：先复用/拉伸，稳定后再重建。
- Qt 没有"直接模糊一张 QPixmap"的接口，用"缩小 + 平滑放大"近似，并且**必须缓存**。
  注意反向的坑：把文字**先**按缩小后的字号去画，会因为没有字形而得到一张全透明的遮罩——
  要按全尺寸画好、再缩小、再放大回来。
- 纹理画刷（胶片噪点）：瓦片按**设备像素**建 + `setDevicePixelRatio(ratio)`，粒子才等于 1 个物理
  像素；偏移不要按帧率重掷（按帧重掷读起来是"整层在抖"）。
- 无边框窗口的缩放抓取只能靠**主窗口事件过滤器**在子控件之前截获；`QWindow.startSystemResize()`
  与原生 `WM_NCHITTEST` 两条路都实测无效。
- 页面 UI 大量是在 `paintEvent` 里直接绘制的（不是 QLabel），动画统一挂页面已有的 16ms `_tick`。
- 调图标/形状尺寸时看**实测像素台阶**：增量不足一个像素的改动在视觉上等于没改。
- 列表类控件只创建视口附近的行并按滚动位置复用。**位置不是"内容还有效"的代理**：换一批数据时
  "第一个可见行号"完全可能没变，只依据它做提前返回会让行留着上一批的文字。

### 4.1 音频（PCM 转盘引擎）

- 推送式音频设备（`QAudioSink`）按**自己的时钟**消费数据：每帧必须写够"流逝的真实时间"对应的
  帧数。少写不等于放慢——设备只会把缺口填成静音。
- 变速必须靠**重采样**；1× 保留整片拷贝的快路径。
- 音高上限要保守：页面把**鼠标角度**映射成转速，鼠标能把唱片转得比手快几十倍，任何向上的变调都会
  变成"花栗鼠"。超过上限时应当**跳播并保持跟手**，绝不能让音频越拖越落后。
- 播放头归属要明确：引擎在非搓碟时自己推进，页面只在搓碟期间写它。拆状态后要 grep 一遍所有读取点。

## 5. 提交约定

- 提交信息：**英文标题 + 中文正文**，写"为什么"（根因、取舍），不是"改了什么"。
- 未修复或未确认的问题**必须在提交信息里显式标注**（`KNOWN` / `KNOWN LIMITATION`），并写清已排除的
  可能，避免后来者误以为已解决。
- 视觉与手感类改动要能给出**实测数字**，不要"看着差不多"。
- 文档（README 等）与代码在同一次提交里同步更新。

### 5.1 备份（无远程仓库时的里程碑备份）

只在**代码变了**的里程碑做，纯文档提交不必重跑产物：

```powershell
git status --short                                        # 必须为空
git bundle create AfterFrame-backup.bundle main           # 本分支的完整历史
git archive --format=zip -o AfterFrame-source.zip HEAD    # 纯源码快照
git bundle verify AfterFrame-backup.bundle                # 应回 "records a complete history"
```

> 用 `main` 而不是 `--all`：`--all` 会把 `refs/remotes/origin/main` 也打进去，于是 bundle 里
> 可能混进"已经被重写掉、只存在于远端引用里的旧提交"。只打包本分支，产物才和你要发布的东西
> 严格一致。

- **备份必须验证过还原才算数**：clone 到临时目录后逐文件 `git hash-object` 与源仓库对比，0 差异
  才通过；能顺带 `compileall` + `import` 一遍更好——只对哈希只能证明字节一样，证明不了源码还能用。
- 不要备份 `.venv` / `__pycache__`（体积大又写死了绝对路径）。
- 还原：`git clone -b main <bundle> <目录>` → `python -m venv .venv` → `pip install -r requirements.txt`。
  ⚠️ **`-b main` 不能省。** `git bundle create <file> main` 只打包 `refs/heads/main`，**不写 bundle
  自己的 HEAD**，所以直接 `git clone <bundle>` 会报 `remote HEAD refers to nonexistent ref`，并且
  留下一个**空工作区** —— 提交其实都在里面，但检出不出来，看起来就像"备份是空的"。要么加
  `-b main`，要么 clone 之后手动 `git checkout main`。实测过：不带 `-b main` 得到 0 个文件，
  带上得到 25 个、哈希全同。

### 5.2 打包成单文件 exe（Nuitka）

```powershell
# 1. Nuitka 的缓存与临时目录。**必须设**，理由见下表的头两条。
$env:NUITKA_CACHE_DIR = "$PWD\_build_tmp\cache"
$env:TMPDIR = "$PWD\_build_tmp\tmp"; $env:TEMP = $env:TMPDIR; $env:TMP = $env:TMPDIR

# 2. 编译
.\.venv\Scripts\python.exe -m nuitka --standalone --onefile `
  --windows-console-mode=disable `
  --windows-icon-from-ico=afterframe.ico `
  --include-data-file=afterframe.ico=afterframe.ico `
  --enable-plugin=pyside6 `
  --include-qt-plugins=multimedia `
  --remove-output `
  --output-filename=AfterFrame.exe run.py
```

`--remove-output` 让中间产物编完即删，只在当前目录留下 `AfterFrame.exe`（约 96 MB）。

**每个参数都不是可选的**，而且它们失败的方式差别很大 —— 有的立刻报错，有的**静默降级**：

| 参数 | 不写会怎样 |
|---|---|
| `NUITKA_CACHE_DIR` | Nuitka 把编译器探测结果缓存到 `%LOCALAPPDATA%\Nuitka\...`。写入被拦时编译**直接失败**（`SConsLockFailure: Timeout waiting for lock`）。`%TEMP%` 同理：Nuitka 与它派生的 SCons、`cl.exe` 都要在那里建临时文件。这两个变量只对**当前 shell 会话**有效，换窗口要重设 |
| `--windows-console-mode=disable` | 运行时会弹一个黑色控制台窗口 |
| `--windows-icon-from-ico` | exe 文件本身没有图标（**注意**：这只管 exe 图标，窗口图标是另一回事，见下） |
| `--include-data-file` | `constants.resource_path()` 找不到 `afterframe.ico`，**窗口**与任务栏图标退回默认。两个图标参数管的是两件不同的事，都要写 |
| `--enable-plugin=pyside6` | Qt 的 DLL 与插件不会被收集 |
| `--include-qt-plugins=multimedia` | **静默降级**：Qt 找不到媒体后端，`QMediaPlayer` 不可用，于是封面取不到、搓碟退回模拟效果。**不报错** —— 见下 |

#### 为什么 `--include-qt-plugins=multimedia` 必须显式写

Nuitka 4.2.2 的 `PySidePyQtPlugin._getSensiblePlugins()` 里，默认包含的 Qt 插件白名单写的是
**`mediaservice`** —— 那是 PySide6 6.5 及更早的目录名。PySide6 6.6 起改名为 **`multimedia`**，
而白名单是用 `hasPluginFamily(name)` 过滤的，名字对不上就**整个目录被跳过，且没有任何提示**。

后果不是崩溃，而是"能用但变弱"：`afterframe/scratch_engine.py` 用
`_MULTIMEDIA_OK and shutil.which("ffmpeg")` 判断能否启用 PCM 引擎，前者为假时 `ffmpeg_available()`
永远返回假 —— **真倒放搓碟静默变成模拟效果**，同时内嵌封面也读不到。

**自查方法**：编完看 `AfterFrame.exe` 的体积，以及产物树里有没有那个后端：

```powershell
Get-ChildItem run.dist -Recurse -Filter '*mediaplugin*'   # 应有 ffmpegmediaplugin.dll
```

带了多媒体组件时约 **96 MB**，漏掉时约 **78 MB** —— **18 MB 的差距就是它**。

#### 控制台窗口闪一下

`ffmpeg` 与 `ffprobe` 都是控制台程序，而 GUI 进程没有自己的控制台，Windows 会给每个子进程新建
一个。**从源码运行时看不见**：`python.exe` 本来就有控制台，子进程直接继承。打包后没有可继承的
控制台，窗口就显形了 —— 切歌时会闪**两个**（一次读歌词、一次读曲目详情）。

所有 `subprocess` 调用都要经过 `constants.no_window_kwargs()`（内部是 `CREATE_NO_WINDOW`）。
漏掉一处不会报错，只是多一个黑框，所以新增外部命令调用时记得带上它。

## 6. 可自定义项

改观感/手感时，绝大多数旋钮都在这些地方。**注意**：这些常量大多带一段"为什么是这个值"的实测
依据，那份全文在私有的界面笔记里（不随仓库发布）；这里只列**在哪调、调什么**。

### 6.1 `constants.py`

- `APP_NAME`：启动动画与窗口标题显示的名称。
- `APP_VERSION`：左下角竖排的版本号、监控页右上角的 `V1.0 // ACTIVE`、设置页关于行。**它由
  `afterframe/__init__.py` 的 `__version__` 拼出**（`"v" + __version__`），所以**发布新版本只改
  `__init__.py` 那一处**；`APP_VERSION` 是显示形式（带 `v`，界面再 `.upper()`），不要单独改它。
  > 这两处曾经各写各的：`__version__` 是 `0.1.0`，而界面显示 `v1.0`。因为**没有任何代码读
  > `__version__`**，这个不一致对用户不可见，也没有任何检查能发现 —— 直到有人去找。
- `WINDOW_WIDTH` / `WINDOW_HEIGHT`：启动小窗尺寸。
- `MAIN_WINDOW_WIDTH` / `MAIN_WINDOW_HEIGHT`：主窗口默认尺寸。
- `MAIN_WINDOW_MIN_WIDTH` / `MAIN_WINDOW_MIN_HEIGHT`：主窗口最小尺寸（默认 600×560，由三个页面的
  实际布局需求推导而来，调小会导致内容被压扁或截断）。
- `RESIZE_BORDER` / `RESIZE_CORNER`：边缘缩放抓取区宽度、四角斜向抓取区边长（逻辑像素，默认
  10 / 24，后者建议不小于前者）。
- `MAIN_WINDOW_RESIZE_BOUNCE`：松手弹跳总开关（`False` 则直接吸附到释放尺寸）。
- `RESIZE_SPRING_STIFFNESS` / `RESIZE_SPRING_DAMPING`：缩放弹簧的刚度与阻尼。**阻尼是"果冻感"的
  关键**——默认 0.28，调小（如 0.24）更弹更抖，调大（如 0.35）更收敛利落；刚度调小则整体更慢更软。
- `MAIN_WINDOW_RESIZE_OVERSHOOT` / `RESIZE_RELEASE_VELOCITY_GAIN`：普通缩放松手时的踢力上限与速度
  换算系数，两者共同决定弹跳幅度。
- `MAIN_WINDOW_RESIZE_SQUEEZE` / `RESIZE_SQUEEZE_SOFTNESS` / `RESIZE_SQUEEZE_POWER` /
  `RESIZE_SQUEEZE_MAX`：越过最小尺寸时的挤压开关、软区间长度、起手软硬、压缩量渐近上限。
- `RESIZE_OPEN_VELOCITY_GAIN` / `RESIZE_OPEN_VELOCITY_MAX`：挤压释放时张开窗口的初速度及其上限。
- `INFO_SCROLL_SPEED_PX_S` / `INFO_SCROLL_HEAD_PAUSE_MS` / `INFO_SCROLL_TAIL_PAUSE_MS`：歌曲名与
  专辑信息的滚动速度与首尾停顿时长。
- `BTN_PRESS_KICK` / `BTN_PRESS_STIFFNESS` / `BTN_PRESS_DAMPING`：播放控制按钮点击时的挤压幅度、
  回弹速度与抖动次数。
- `VOLUME_ICON_PUSH_PX` / `VOLUME_ICON_WALL_KICK` / `VOLUME_ICON_MAX_OFFSET`：音量条把喇叭推开的
  持续推力、越界冲量、最大位移上限。
- 各种 `*_DURATION`：启动、切换、最小化等动画时长。其中 `CHROME_FLAT_DURATION`（默认 160）是
  **最小化 / 关闭之前**把磨砂外壳淡成平色、以及恢复后再淡回来的时长——它是"动画真正开始之前"
  多出来的一段；`CHROME_WASH_HIDES_FROST_ALPHA`（默认 200）决定外壳白洗多不透明时**跳过**这段过渡。
- `BAR_COLOR` / `BACKGROUND_COLOR` / `TEXT_COLOR`：主题颜色。
- **黑胶唱片**：`VINYL_*` 区块。`VINYL_MS_PER_DEG` 与 `VINYL_SPIN_DEG_PER_MS` 是配套的（一圈 = 3 秒
  音频，保证 PCM 引擎下唱片角度与播放头锁定）；`VINYL_RELEASE_TAU_MS` 控制松手后转速回落；
  `VINYL_PEEK_FRACTION` 控制收起时露出的比例、`VINYL_PULL_DRAG_PX` 与 `VINYL_STOW_DRAG_PX` 分别控制
  抽出与丢回的拖动阈值、`VINYL_LABEL_RADIUS_RATIO` 控制可触发丢回的中心标签范围；`VINYL_SHEEN_ALPHA`
  控制旋转光泽强度。
- **磨砂玻璃**：`FROSTED_CHROME_STATE` / `FROSTED_CHROME_FLAGS` / `FROSTED_CHROME_TINT`（`window.py`
  的 `_apply_chrome_glass()` 使用）；**档位表**是 `FROSTED_LEVELS`（(标签, 每页白洗 alpha)，`None` =
  该页不用材质）与 `DEFAULT_FROSTED_LEVEL`，加一档只需加一个元组、控件会自动多一段。`AccentFlags`
  是关键：实测 `2` 只剩一小部分大结构对比度（背后窗口基本被抹平），`0/1/4` 保留得多且互测无差别。
- **「音乐色彩」效果**：`COLOR_*` 区块。四组东西：**背景色雾**（`COLOR_MIST_*`：团数、半径、透明度、
  漂移幅度与速度、以及它按页面几分之一来画——那是它唯一的"模糊"；颜色来自封面调色板，取不到时回落
  中性冷色）、**两团融进雾里的漩涡**（位置钉死、只自转，`COLOR_SHAPE_SPIN_DEG_PER_S` 默认 4°/s 即
  90 秒一圈、两团反向；密度 `COLOR_SHAPE_MIST_ALPHA`）、**小圆斑**（只在两团之间的空白带里缓慢摆动，
  `COLOR_BUBBLE_*`）。观感旋钮：色雾透出多少 `COLOR_FROST_ALPHA` / `COLOR_FROST_DARKEN`（前置磨砂层）、
  背景本体柔软度 `COLOR_MIST_DIVISOR`（**数字越大越糊**）、色团大小与浓度
  `COLOR_MIST_BLOB_SIZE` / `COLOR_MIST_BLOB_ALPHA`、漂移 `COLOR_MIST_DRIFT_*`；胶片噪点 `COLOR_NOISE_*`
  （瓦片按设备像素生成，1 个粒子 = 1 个物理像素）；整层刷新间隔 `COLOR_FRAME_STEP_MS`、拖窗口时延迟
  重建 `COLOR_RESIZE_SETTLE_MS`。

**字体**：全界面统一使用 `UI_FONT_FAMILY` / `UI_FONT_STACK`（默认黑体/无衬线族，降级到
Segoe UI → Arial）；侧边栏与标题栏的图标字形单独使用 `Segoe UI Symbol`。字体栈**末尾挂了
`Segoe UI Symbol` 与 `Segoe UI Emoji`**：歌词里常见的 `˶ ˃ ᵕ ˂ ᐟ` 这类修饰字母与符号前面几个家族
都没有，不挂符号字体时 Qt 会去够点阵字体「Fixedsys」并反复失败（症状是歌词卡顿 + stderr 刷屏）。
多出来的家族**只在更靠前的家族缺字形时才会被用到**，所以普通文字的渲染逐像素不变。
`ui_font()` 按 `(字号, 字重)` 缓存原型并返回副本——调用方会改它（如 `setWeight`），直接返回同一个
对象会让后一次调用污染前一次。

### 6.2 其它文件

- **侧边栏尺寸**：`page_stack.py` 的 `Sidebar` 中 `WIDTH`、`ICON_SIZE`、`ACCENT_WIDTH`。
- **弹簧拖拽手感**：`window.py` 的 `_update_spring_physics()` 中 `stiffness` 与 `damping`。
- **最小化 / 关闭动画**：`window.py` 的 `_MinimizeAnimator`（顶层覆盖层）播一个 **CRT 关机式的
  就地坍缩**，然后才真正最小化；时长是 `constants.MINIMIZE_SHUTDOWN_DURATION`。开播之前先让磨砂
  外壳淡成平色（`CHROME_FLAT_DURATION`），快照因此拍到的是窗口"真实的样子"而不是磨砂状态。
  动画**不飞向任务栏**，所以不存在"对准任务栏图标"的问题。
  > 早先的实现是飞向任务栏图标，而那个位置拿不到（Windows 11 的任务栏图标不是普通窗口），
  > 只能回退到任务栏中心——那条限制随实现一起换掉了，**别再照旧描述写文档**。
- **侧边栏 / 标题栏配色**：`theme.py` 的 `PAGE_THEMES` 按页面索引调整，每项可改 `chrome_base`
  （垫在白洗下面的不透明底色——没材质时以及最小化/关闭预过渡的终点就是它）、`chrome_bg`（白洗）、
  边框、图标常态/悬停色、文字色与控制按钮配色；`ThemeAnimator` 的 `duration` 控制渐变时长。
  **`chrome_bg` 的 alpha 就是"磨砂能透出多少"这个旋钮**：透出比例约等于 `1 - alpha/255`。
  浅色页调薄时要连着看深色文字在最坏壁纸（纯黑）上的对比度，别掉到 WCAG AA 的 4.5:1 以下。
- **进度条 / 音量条手感**：`elastic_slider.py` 的 `ElasticSlider.update()` 中数值跟随的
  `stiffness`/`damping` 与条宽过渡系数；`toy_page.py` 的 `_draw_progress_bar` 中 `0.8 * expand`
  决定展开后的最大厚度。
- **可视化效果列表**：`toy_page.py` 的 `_VISUALIZER_ITEMS` 里增删 `(标签, 键)` 项（面板会按它重建、
  高度自适应），再在 `ToyPage._draw_background` 里为新键加一个绘制分支。
- **歌词复制闪光**：`toy_page.py` 顶部的 `LYRICS_COPY_FLASH_*`（时长 / 衰减常数 / 峰值 / 截断阈值）。

**设置存在哪里**：全部偏好经 `afterframe/settings_store.py` 的 `settings()` 读写，落在**仓库根目录的
`afterframe_settings.ini`**（属于本机状态、不是源码，已在 `.gitignore` 里）。以前直接用 `QSettings`
（Windows 上就是注册表 `HKCU\Software\AfterFrame\AfterFrame`），但那个位置**不一定可写**——不可写时
`setValue()` **不报错也不落盘**，于是每一个设置都在静默地自我遗忘。现在是**文件优先**：只有**项目
目录本身不可写**时才退回注册表，两处都不可写就用注册表只读，并由 `settings_store.store_kind()` 如实
报告 `ini` / `registry` / `read-only`，不假装成功。判定"能不能写"的手法：写一个标记值 → `sync()` →
**直接读文件自己的字节**确认落盘（`QSettings` 对 ini 有进程内缓存，用另一个实例读回会谎报成功）。

## 7. 文档同步

**公开 README 是"门面"，不是手册**：它只回答「这是什么 / 长什么样 / 怎么跑 / 有什么限制」。
深入的取舍、实测数字、试过又被否的方案一律**不进 README**。往 README 里加东西前先问一句：
这是给**第一次点进来的人**看的吗？

> 维护者可能另有更详细的界面笔记（含实测数据与历史方案），但那类笔记**不随仓库发布**：
> 不要在本文件或 README 里引用读者看不到的文件。读者手上只有这个仓库，任何"详见某处"
> 都必须指向仓库里真实存在的文件。

改完代码后要核对的同步点：

- **常量名**：本文件 §6 引用了大量常量名。改名/删除常量后逐个确认它们还在
  （`git grep -n '<常量名>' afterframe/`），已改名的常量最常在这里露馅。
- **模块职责**：新增或改名模块后，本文件 §1 的那张模块表要跟着改（README 是门面，不列模块）。
- **死链**：改名或移走文件后，查一遍有没有指向**不进仓库的文件**的引用
  （按本仓库的约定，私有笔记是 `AGENTS.md` / `NOTES.md` / `DEVNOTES.md`）。更彻底的做法是按
  **打包产物里的字节**扫（`git archive` 出来的 zip），而不是扫工作区——工作区里私有文件还在，
  扫描会误判成"引用有效"。
- **截图**：README 的图在 `images/`（WebP，q90）。换图后确认 Markdown 路径仍然有效；
  重新压缩别用原 PNG（三张合计 3.2 MB，压完 194 KB）。
