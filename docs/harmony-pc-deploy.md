# OctoOCR-offline 鸿蒙 PC 部署方案（融合开发引擎）

适用：华为鸿蒙电脑（麒麟 X90 等 aarch64 平台），通过「融合开发引擎」的 openEuler Linux
环境运行本软件。

实测机型：**HAD-W32 MateBook Pro（32GB + 1TB，麒麟 X90，鸿蒙 6.x）**——
依赖安装 → 识别 → 鸿蒙浏览器访问全链路通过，168 页 PDF 连续识别性能可接受。

## 总流程

提供两种安装方式：

- **方案一（在线）**：NAT 模式下联网装依赖（§4），适合虚拟机可短暂联网的场景
- **方案二（完全离线，傻瓜式）**：部署包自带 Python 运行时 + 全部依赖轮子，
  host-only 断网状态下一条命令装完（§8），**推荐给最终用户**

1. 鸿蒙侧：App Gallery 安装融合开发引擎，启动 openEuler 虚拟机
2. 准备部署包：源码 + 模型 + 部署脚本，通过「文件共享」送入虚拟机（/mnt/linux_share）
3. 安装：方案一（NAT 模式联网装）或 方案二（离线包直接装）
4. 切换到 **host-only（仅主机）模式**，本机浏览器才能访问服务

> 关键结论：NAT 模式下宿主机访问不到虚拟机，仅主机模式虚拟机没有外网——
> 在线方案必须「NAT 装依赖、host-only 访问」两步分开；离线方案则全程无需外网。

---

## 1. 安装并启动融合开发引擎

1. 鸿蒙电脑打开 **App Gallery**，搜索并安装「融合开发引擎」
   （仅主用户——首次开机创建的用户——可用）
2. 打开引擎，创建并启动虚拟机（当前版本仅支持 **openEuler**）

## 2. 准备部署包（在任意可联网的电脑上，如开发机）

```bash
git clone https://github.com/1ampa55ag3/octo-ocr
cd octo-ocr
bash scripts/download_models.sh        # 下载模型（约 286MB；或直接拷贝现成的 models/）
```

部署包结构（放入一个目录，比如 deploy/）：

```text
deploy/
├── octo-ocr/                    源码 src/ + 模型 models/ + scripts/
├── deploy_harmony.sh            一键部署脚本（本仓库 scripts/ 内）
├── requirements-harmony.txt     依赖清单（含已修复的版本冲突）
└── wheels/                      （可选）离线补丁轮子，见 §7
```

## 3. 文件共享进虚拟机

1. 鸿蒙侧：把 deploy/ 目录放到任意位置（如桌面）
2. 融合开发引擎 → 「文件共享」→ 选择该目录
3. 虚拟机内访问路径固定为 **/mnt/linux_share**

> 注意：共享目录内的文件是 root 属主，直接在里面建 venv/跑服务会有权限问题。
> 部署脚本会自动把代码复制到 ~/octo-ocr 再操作，无需手动处理。

## 4. NAT 模式下部署依赖

1. 融合开发引擎设置 → 网络模式 → **NAT**（此模式下虚拟机才能访问互联网）
2. 虚拟机终端执行：

```bash
bash /mnt/linux_share/deploy_harmony.sh
```

脚本自动完成：环境体检 → 复制代码到 ~/octo-ocr → 网络自检（清华/阿里/官方 pip 镜像
依次尝试）→ 查找 Python（没有则用 HarmonyBrew 安装 python@3.11）→ 创建 venv 并安装
依赖 → 模型完整性检查（缺失则自动补下）→ 导入验证 → 冒烟识别样例 PDF。

依赖清单内置三个已验证的修复：

1. **numpy 版本冲突**：rapid-layout 要求 numpy>=2，rapid-latex-ocr 却锁 numpy<2——
   后者限制实测多余，rapid-latex-ocr 以 --no-deps 单独安装；
2. **opencv**：rapidocr 会连带安装完整版 opencv-python（依赖 X11 图形库，服务器
   环境没有）；两个 opencv 包共享 cv2 文件、卸载会误删，因此强制重装
   opencv-python-headless 使其成为 cv2 的实际提供者；
3. **未声明依赖**：rapid_latex_ocr / rapid_layout 内部 import 但未声明的
   chardet / requests / tqdm，已在清单中显式声明。

若验证导入时报缺系统库，执行（openEuler 包名）：

```bash
sudo dnf install -y mesa-libGL libxcb
```

## 5. 切换到 host-only 模式使用

依赖装完后虚拟机不再需要外网，切换网络模式以允许宿主机访问：

1. 融合开发引擎设置 → 网络模式 → **仅主机（host-only）**
2. 虚拟机内查看 IP：

```bash
ip addr    # 记下 eth0 的 inet 地址，如 172.16.105.2
```

3. 启动服务（--host 0.0.0.0 使服务监听所有网卡）：

```bash
cd ~/octo-ocr
PYTHONPATH=src .venv/bin/python -m mdun.cli --data-dir . serve --host 0.0.0.0 --port 8788
```

4. 鸿蒙浏览器访问：**http://<虚拟机IP>:8788**

> 安全提示：--host 0.0.0.0 会监听全部网卡，仅建议在可信内网/仅主机网络使用；
> OfflineGuard 仍封锁程序的一切出网行为，数据不出本机。

## 6. 方案二：完全离线安装（host-only 断网可用，傻瓜式）

部署包额外包含：

- `python-runtime.tar.gz`：自带 Python 3.11 aarch64 运行时（python-build-standalone，含 pip）
- `wheels/`：全部依赖轮子（cp311 manylinux aarch64，含两个 opencv 变体）
- `install_offline.sh`：离线一键安装脚本

**准备离线部署包**（在任意可联网的电脑上，一条命令）：

```bash
python3 scripts/build_offline_package.py ~/offline-package
# 再把 src/ 拷贝为 ~/offline-package/octo-ocr/src，模型放入 models/，
# 并放入 scripts/install_offline.sh 与 scripts/requirements-harmony.txt
```

**虚拟机内安装**（host-only 断网状态下即可，无需 NAT）：

```bash
bash /mnt/linux_share/install_offline.sh
```

脚本自动：复制代码与模型到 ~/octo-ocr → 解压自带 Python → `--no-index` 离线安装全部
轮子（含 numpy2 冲突与 opencv 共享文件的既定修复）→ 模型自检 → 导入验证 → 冒烟识别。
全程零联网、零 dnf、零 venv。

**启动**（使用自带运行时）：

```bash
cd ~/octo-ocr
PYTHONPATH=src python/bin/python3 -m mdun.cli --data-dir . serve --host 0.0.0.0 --port 8788
```

## 7. 日常使用与维护

- 虚拟机重启后 IP 可能变化：用 ip addr 重新查询
- 服务启动命令见 §5/§6；所有操作都在 ~/octo-ocr 下进行（勿在共享目录里直接操作）
- 更新版本：替换 ~/octo-ocr/src 即可；依赖不变则无需重装
- 性能基准（可选）：`cd ~/octo-ocr && PYTHONPATH=src python/bin/python3 bench_linux.py 文档.pdf`

## 8. 故障排查

| 现象 | 处理 |
|---|---|
| pip 镜像全部不可达 | 网络模式必须为 NAT；检查 /etc/resolv.conf DNS；unset http_proxy/https_proxy |
| ResolutionImpossible（numpy 冲突） | 使用包内 requirements-harmony.txt（已含修复），勿手改版本 |
| cv2 导入失败（libxcb/libGL 缺失） | sudo dnf install -y mesa-libGL libxcb；若 cv2 文件被误删，pip install --force-reinstall --no-deps opencv-python-headless |
| No module named chardet/requests/tqdm | 新清单已显式包含；离线环境用 wheels/ 目录：pip install --no-index --find-links wheels chardet requests tqdm |
| 浏览器打不开服务 | 确认：host-only 模式 + ss -tlnp 显示 0.0.0.0:8788 + 访问的是 ip addr 查到的 IP |
| 共享目录里操作报权限错误 | 一律在 ~/octo-ocr 下操作（脚本已自动复制） |
| 找不到 Python | HarmonyBrew：brew install python@3.11 |
| 命令行中文显示不全 | 双指缩放命令行界面即可恢复（华为官方说明） |
