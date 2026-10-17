# 源码版安装与运行指南

本页对应仓库中实际提供的源码与脚本。项目支持不配置外部模型的本地演示，也支持按需使用科大讯飞星火 MaaS。

## 环境要求

- Windows PowerShell，Python 3.11 或更高版本。
- Node.js 20.19+ 或 22.12+，以及 npm。
- 可选的扫描 PDF OCR 需要单独安装 Tesseract；普通文本资料导入不需要 OCR。

## 安装

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Push-Location src/frontend
npm ci
Pop-Location
```

## 本地演示

```powershell
.\scripts\run-local.ps1 -PythonExecutable "$PWD\.venv\Scripts\python.exe"
```

默认前端地址为 `http://127.0.0.1:5173`，后端地址为 `http://127.0.0.1:8000`。运行脚本加载课程种子数据并创建本地 SQLite 数据库，无需下载或提交他人的运行数据库。停止时在启动窗口按 `Ctrl+C`。

如需避开已使用的端口：

```powershell
.\scripts\run-local.ps1 -BackendPort 8010 -AutoSelectFrontendPort -PythonExecutable "$PWD\.venv\Scripts\python.exe"
```

## 使用外部模型

星火 MaaS 入口为：

```powershell
.\scripts\run-competition-spark.ps1
```

该入口要求在本机环境中提供自己的 `XFYUN_SPARK_API_KEY`，并使用已安装项目依赖的 Python 环境。模型、超时和重试等参数可查看脚本开头的 `param` 定义。其他环境变量见 [配置示例](local.env.example)。

真实密钥仅保存在本机环境配置中，不要提交到仓库。通过命令行直接输入密钥可能被终端历史记录保存。模型与向量服务为可选能力，网络或服务异常时按配置回退到规则策略或关键词检索。

## 验证入口

```powershell
.\scripts\run-local.ps1 -SmokeOnly -PythonExecutable "$PWD\.venv\Scripts\python.exe"
.\scripts\verify.ps1
```

完整验证脚本会执行多项依赖与测试检查，运行前应确认本机具备脚本所需的 Python、Node.js、npm 和浏览器环境。

## 配套资料

- [系统开发说明书](../文档与演示视频/01-系统开发说明书.docx)
- [测试说明书](../文档与演示视频/02-测试说明书.docx)
- [部署与运行说明书](../文档与演示视频/03-部署与运行说明.docx)
- [参赛时的评委部署说明](评委安装部署与运行说明.md)

参赛材料中的安装包入口和历史云端地址可能与源码仓库不同；从本仓库运行时，以本页和 `scripts/` 下实际提供的脚本为准。
