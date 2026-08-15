# OctoOCR-offline

把扫描件和 PDF 里的文字识别出来、顺手改对的软件。**不用联网，数据不出你的电脑。**

## 能做什么

- 把扫描的 PDF、拍的照片变成可以编辑的文字；
- 自动修标点、合并段落、识别表格；
- 像 Word 一样改文字，改完导出 Word / PDF / 文本文件；
- 带防截图水印、审计日志，适合办公环境。

## 安装（照着做，选你电脑的系统）

### Windows

**第 1 步：装 Python**

1. 浏览器打开 <https://www.python.org/downloads/>，点黄色 `Download Python 3.12.x` 按钮；
2. 运行下载到的安装程序，**先勾选最下面的 `Add python.exe to PATH`**，再点 `Install Now`；
3. 装完点 `Close`。

**第 2 步：下载本软件**

1. 打开本仓库页面，点绿色 `Code` 按钮 → `Download ZIP`；
2. 解压到桌面，把解压出来的文件夹改名为 `octo-ocr`（不改也行，后面命令按你的名字改）。

**第 3 步：安装软件需要的组件**

1. 按键盘 `Win` 键，输入 `powershell`，回车，打开蓝色窗口；
2. 把下面三行**一行一行**复制进去，每行按回车，等它跑完（每行 1~3 分钟，属正常）：

```powershell
cd $env:USERPROFILE\Desktop\octo-ocr
python -m venv .venv
.venv\Scripts\pip install -e .
```

最后出现 `Successfully installed ...` 就是成功。

**第 4 步：下载识别模型（约 2GB，只做一次）**

继续在蓝色窗口里执行：

```powershell
.\scripts\download_models.ps1
```

> 如果提示「禁止运行脚本」，先执行 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`，再重试上面这行。

看到「完成。模型已放入 models 目录」即可。

**第 5 步：启动软件**

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python -m mdun.cli --data-dir . serve
```

窗口里出现「OctoOCR 工作台已启动」后，**不要关闭这个窗口**，打开浏览器访问 <http://127.0.0.1:8788> 就能用了。

### macOS

**第 1 步：打开终端**

点屏幕右上角放大镜，输入「终端」，回车。

**第 2 步：装 Python**

在终端里粘贴下面这行，回车（需要输入开机密码时输一下）：

```bash
brew install python@3.12
```

> 如果提示 `command not found: brew`，先去 <https://brew.sh>，按它主页的命令把 brew 装上，再回来执行上面这行。

**第 3 步：下载本软件**

浏览器打开本仓库 → 绿色 `Code` 按钮 → `Download ZIP`，解压到桌面，文件夹改名 `octo-ocr`。

**第 4 步：安装组件 + 下载模型**

终端里一行一行执行（每行回车）：

```bash
cd ~/Desktop/octo-ocr
python3 -m venv .venv
.venv/bin/pip install -e .
bash scripts/download_models.sh
```

**第 5 步：启动**

```bash
PYTHONPATH=src .venv/bin/python -m mdun.cli --data-dir . serve
```

出现「OctoOCR 工作台已启动」后，浏览器打开 <http://127.0.0.1:8788>。

## 怎么用

1. 打开 <http://127.0.0.1:8788>；
2. 点左上「导入文件」选 PDF 或图片（也可以直接把文件拖进窗口），一两秒后右边出现识别出的文字；
3. 想要更准：点预览栏下方「全文识别」（带表格、公式的文档必点）；
4. 改文字：直接用鼠标点着改；再点「标点修复」「段落修复」自动修；
5. 保存：右上「导出」→ 选格式（Word 用 docx、打印用 pdf、纯文字用 txt），文件自动下载。

## 常见问题

**打不开 127.0.0.1:8788？**
那个黑/蓝窗口就是软件本身，关掉窗口软件就停了。重新执行「启动」那一步即可。

**提示模型缺失？**
说明「下载模型」那步没跑完，重新执行它。

**提示端口被占用？**
换一个端口启动：`... serve --port 8900`，然后访问 <http://127.0.0.1:8900>。

**想彻底卸载？**
删掉整个 `octo-ocr` 文件夹即可，软件不留任何其他东西。

## 电脑要求

Windows 10 64 位或 macOS 13 以上，内存 8GB 以上，硬盘空闲 4GB。普通办公电脑就行，不需要独立显卡。

## 更新

到仓库页面重新 `Download ZIP`，解压覆盖旧的 `octo-ocr` 文件夹即可（你自己的文件和模型不受影响）。

## 开源与许可

本软件按 Apache-2.0 开源。用到的开源组件与各自许可证，可在软件左下角「开源许可」查看；安全问题见 [SECURITY.md](SECURITY.md)。