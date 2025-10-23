<div>
<p align="center">
    <img src="https://static.docs-hub.com/deepseek.png" height="64">
</p>
<div align="center">

[![Version](https://img.shields.io/visual-studio-marketplace/v/colourafredi.vscode-deepseek?label=VS%20Code%20Marketplace)](https://marketplace.visualstudio.com/items?itemName=colourafredi.vscode-deepseek)
[![Rating](https://img.shields.io/visual-studio-marketplace/stars/colourafredi.vscode-deepseek)](https://marketplace.visualstudio.com/items?itemName=colourafredi.vscode-deepseek)
[![Downloads](https://img.shields.io/visual-studio-marketplace/d/colourafredi.vscode-deepseek?label=Downloads)](https://marketplace.visualstudio.com/items?itemName=colourafredi.vscode-deepseek)

<p align="center">Free | No Login Required | Multi-language</p>
<p align="center">免费 | 免登录 | 多语言</p>
</div>
## 🚀 Key Features

*   💻 **Code Operations**: One-click copy, insert code into current file or new file
*   🔍 **Intelligent Analysis**: Code explanation, error detection, refactoring suggestions, test generation
*   ✨ **Code Completion**: AI-powered code suggestions as you type
*   📝 **Custom Prompts**: Support adding and managing predefined prompts to improve questioning efficiency
*   💾 **Local Storage**: Chat history saved locally for replay, continuation and management
*   🌐 **Custom baseUrl Support**: Configure your own baseUrl server for flexible API access
*   🔒 **Privacy Protection**: All information stored locally, no data uploaded
*   🌍 **Multi-language**: Support Chinese, English and other language interfaces
*   🎯 **Model Selection**: Support multiple DeepSeek models for different needs
*   🖥️ **Local Deployment**: Support deploying DeepSeek R1 locally via Ollama with knowledge base, usable without internet

## 📦 Installation

1.  Open VS Code
2.  Press shortcut:
    *   Windows/Linux: `Ctrl + Shift + P`
    *   Mac: `Command + Shift + P`
3.  Press `Ctrl+Shift+P` to open command palette
4.  Delete `>` and enter `ext install colourafredi.vscode-deepseek`
5.  Press Enter to install

<p align="left">
    <img src="https://static.docs-hub.com/install_1739321125692.png" width="300">
</p>

Or directly visit [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=colourafredi.vscode-deepseek) to install

## 🛠️ Main Features

### 1. Code Analysis and Optimization

*   **Code Explanation**: Detailed explanation of code logic and implementation
*   **Error Detection**: Find and fix bugs in code
*   **Code Refactoring**: Optimize code structure, improve code quality
*   **Test Generation**: Automatically generate unit test code
*   **Code Completion**: Get intelligent code suggestions while typing

### 2. Intelligent Dialogue

*   **Context Dialogue**: Support multi-turn conversations, understand context
*   **Streaming Response**: Real-time display of AI answers
*   **Session Management**: Save, export, clean chat history
*   **Custom Prompts**: Support preset common prompts

### 3. Personalization Settings

*   **Server Settings**: Configurable server
*   **Model Selection**: Support multiple DeepSeek models
*   **API Key Management**: Support binding your own API Key
*   **Model Temperature**: Set model temperature (0-2)
*   **token**: Set maximum token count
*   **top_p**: Set top_p value
*   **top_k**: Set top_k value
*   **frequency_penalty**: Set frequency_penalty value
*   **Interface Language**: Switch between Chinese, English and other interface languages

## 💡 Usage Guide

### Quick Start

1.  After installing the plugin, click the `DeepSeek` icon on the left side of `VS Code`
2.  Enter your question in the input box and press Enter to send
3.  Wait for AI response, you can:
    *   Copy the answer content
    *   Insert into current file
    *   Create new file to save

<p align="left">
    <img src="https://static.docs-hub.com/icon_1739321180871.png" width="300">
</p>

<p align="left">
    <img src="https://static.docs-hub.com/bubble_1739333401974.png" width="300">
</p>

### Code Related Features

1.  Select code snippet
2.  Right click to select DeepSeek related commands:
    *   Explain code
    *   Check for errors
    *   Refactor and optimize
    *   Generate tests

<p align="left">
    <img src="https://static.docs-hub.com/right_1739321297150.png" width="300">
</p>

### Code Completion

DeepSeek 插件提供了强大的代码补全功能，可以帮助您更高效地编写代码。

#### 启用/禁用代码补全

您可以通过以下方式启用或禁用代码补全功能：

1. 通过命令面板：
   - 按下 `Ctrl+Shift+P`（Windows/Linux）或 `Cmd+Shift+P`（Mac）打开命令面板
   - 输入 "DeepSeek: 启用代码补全" 或 "DeepSeek: 禁用代码补全" 并选择相应命令

2. 通过设置：
   - 打开 VSCode 设置（`Ctrl+,` 或 `Cmd+,`）
   - 搜索 "DeepSeek"
   - 找到 "Enable Completion" 选项并勾选或取消勾选

#### 使用代码补全

当代码补全功能启用后，它会在您编写代码时自动提供建议：

1. 开始输入代码，当您停止输入几百毫秒后，补全建议会自动显示
2. 如果您看到灰色的加载指示器，表示正在生成补全内容
3. 补全内容会以灰色文本显示在您的光标位置
4. 按 `Tab` 键接受建议，或继续输入忽略建议

#### 配置代码补全

为了使用代码补全功能，您需要配置以下参数：

1. **API 密钥**：
   - 在设置中搜索 "DeepSeek: API Key"
   - 输入您的 DeepSeek API 密钥

2. **基础 URL**：
   - 默认为 DeepSeek 官方 API 地址
   - 如果您使用本地部署或其他兼容服务，可以修改此设置

3. **模型**：
   - 选择用于代码补全的模型
   - 推荐使用 "deepseek-coder" 或其他代码优化模型

4. **其他参数**（可选）：
   - Temperature（温度）：控制生成结果的随机性，值越低结果越确定
   - Max Tokens（最大令牌数）：控制生成内容的最大长度
   - Top P：控制生成结果的多样性
   - Top K：限制每一步考虑的词汇数量
   - Frequency Penalty（频率惩罚）：降低重复内容的可能性

#### 提示和技巧

- 代码补全最适合在编写新代码时使用，而不是修改现有代码
- 补全功能会根据您的编码上下文提供建议，包括前后的代码内容
- 如果补全结果不符合预期，可以继续输入以获取新的建议
- 在注释中描述您的意图可以帮助模型生成更准确的补全
- 对于复杂的函数或类，先输入函数签名或类定义，然后让补全功能帮您实现细节

<p align="left">
    <img src="https://static.docs-hub.com/autocomplete_1741020534602.png" width="300">
</p>

### Preset Management
You can define your own custom prompts for quick use
There are two ways to manage your custom prompts
1. Enter commands in the `Ctrl/Command + Shift + P` command palette
2. Select any code and choose from the right-click menu

<p align="left">
    <img src="https://static.docs-hub.com/rightclick_1740195691511.png" width="300">
</p>
<p align="left">
    <img src="https://static.docs-hub.com/command_1740195708248.png" width="300">
</p>

1. **Add Predefined Prompt**(>deepseek:Add predefined prompt)
   - Add new preset prompt template
   - Set prompt name and content
   - Support variable placeholders

2. **Edit Predefined Prompt**(>deepseek:Edit predefined prompt)
   - Modify existing preset prompts
   - Update prompt name and content
   - Delete unwanted presets

3. **Select Predefined Prompt**(>deepseek:Select predefined prompt)
   - Quickly select prompts from preset list
   - Auto-fill to dialogue box
   - Support search filtering

4. **Custom Question**(>deepseek:Custom question)
   - Start conversation using preset prompts
   - Modify content based on actual needs
   - Quick AI response

Type `/` in the question input box to trigger preset prompt dropdown list for selection

<p align="left">
    <img src="https://static.docs-hub.com/slash_1740195980772.png" width="300">
</p>


## Command Description

*   DeepSeek:Check code below for bugs and suggest fixes 🐛
*   DeepSeek:Explain code below in detail 💬
*   DeepSeek:Refactor code below and tell me what changed 🔧
*   DeepSeek:Add tests for code below 🧪
*   DeepSeek:Add predefined prompt ➕
*   DeepSeek:Edit predefined prompt ✏️
*   DeepSeek:Select predefined prompt 🔍
*   DeepSeek:Custom question ✏️
*   DeepSeek:Clear all custom settings 🗑️
*   DeepSeek:Change display language 🌍
*   DeepSeek:Ask question ❓
*   DeepSeek:Clear list 🗑️
*   DeepSeek:Export markdown 📤

## ⚙️ Configurable Parameters

*   `deepseek.baseURL`: Set server address baseURL
*   `deepseek.model`: Choose model to use
*   `deepseek.apikey`: Set API Key
*   `deepseek.temperature`: Set model temperature (0-2)
*   `deepseek.max_tokens`: Set maximum token count
*   `deepseek.roleDefinition`: Set AI assistant's custom system role definition, default value is "You are an AI programming expert, focused on code and programming. You will help answer questions and solve programming problems, providing clear, professional and practical advice", other role definitions can be found in the [documentation](https://github.com/f/awesome-chatgpt-prompts)
*   `deepseek.lang`: Set interface language
*   `deepseek.top_p`: Set top_p value
*   `deepseek.top_k`: Set top_k value
*   `deepseek.frequency_penalty`: Set frequency_penalty value

## Configuration Method

* File->Preferences->Settings->Extensions->DeepSeek

<p align="left">
    <img src="https://static.docs-hub.com/settings_1739321490502.png" width="300">
</p>

### Configure Official API Key
*   [Official API Key Application](https://platform.deepseek.com/api_keys)
*   [Official Available Models](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)

| Configuration Item | Value                                |
| ----------------- | ------------------------------------ |
| DeepSeek:baseUrl  | https://api.deepseek.com            |
| Deepseek:Apikey   | sk-c50d5356a45c4c7988b3df82fb1295e3 |
| DeepseekModel     | deepseek-chat or deepseek-reasoner   |

<p align="left">
    <img src="https://static.docs-hub.com/setupdeepseek_1739332412446.png" width="300">
</p>

### Configure Locally Deployed DeepSeek R1

*   [DeepSeek R1 Local Deployment Tutorial](https://github.com/zhangrenyang/deepseek/blob/main/deploy_zh.md)
*   [Ollama Official Website](https://ollama.com)
*   [Ollama Model List](https://ollama.com/search)

| Configuration Item | Value                    |
| ----------------- | ------------------------ |
| DeepSeek:baseUrl  | http://localhost:11434   |
| DeepseekModel     | deepseek-r1:1.5b        |

<p align="left">
    <img src="https://static.docs-hub.com/setuplocal_1739332236664.png" width="300">
</p>

### Configure Silicon Flow API Key
*   [Silicon Flow API Key Application](https://cloud.siliconflow.cn/account/ak)
*   [Silicon Flow Available Models](https://cloud.siliconflow.cn/models)

| Configuration Item | Value                                                   |
| ----------------- | ------------------------------------------------------- |
| DeepSeek:baseUrl  | https://api.siliconflow.cn                             |
| Deepseek:Apikey   | sk-kgahvlalrbfjyftxrcoiiliopeblhxsgrxtrrwgiqwwxwxth   |
| DeepseekModel     | deepseek-ai/DeepSeek-V3 or deepseek-ai/DeepSeek-R1     |

<p align="left">
    <img src="https://static.docs-hub.com/setupsilicon_1739332328934.png" width="300">
</p>

### Configure Paixun Computing Cloud API Key
*   [Paixun Computing Cloud API Key Application](https://ppinfra.com/settings/key-management)
*   [Paixun Computing Cloud Available Models](https://ppinfra.com/model-api/pricing)

| Configuration Item | Value                                                   |
| ----------------- | ------------------------------------------------------- |
| DeepSeek:baseUrl  | https://api.ppinfra.com/v3/openai                      |
| Deepseek:Apikey   | sk_ASPYijn-VdsIbkEXtjCFNn0dEkvs6Sko6ZEA4XbWc          |
| DeepseekModel     | deepseek/deepseek-v3/community or deepseek/deepseek-r1/community |

<p align="left">
    <img src="https://static.docs-hub.com/paixun_1739332114194.png" width="300">
</p>

### Configure Tencent Cloud API Key
*   [API Documentation](https://cloud.tencent.com/document/product/1772/115969)
*   [Tencent Cloud API Key Application](https://cloud.tencent.com/document/product/1772/115970)
*   [Create OpenAI Compatible APIKEY](https://console.cloud.tencent.com/lkeap/api)
*   [Tencent Cloud Available Models](https://cloud.tencent.com/document/product/1772/115969)

| Configuration Item | Value                                                   |
| ----------------- | ------------------------------------------------------- |
| DeepSeek:baseUrl  | https://api.lkeap.cloud.tencent.com/v1                 |
| Deepseek:Apikey   | sk-EsdQJe0M4IsohNh4k0zji0bq9fsDDMQ77dmtn2hOMocTJCfj   |
| DeepseekModel     | deepseek-v3 or deepseek-r1                             |

<p align="left">
    <img src="https://static.docs-hub.com/tencent_1740186154056.png" width="300">
</p>

### Configure Baidu Cloud API Key
*   [API Documentation](https://console.bce.baidu.com/iam/#/iam/apikey/list)
*   [Create OpenAI Compatible APIKEY](https://console.bce.baidu.com/iam/#/iam/apikey/list)

| Configuration Item | Value                                                   |
| ----------------- | ------------------------------------------------------- |
| DeepSeek:baseUrl  | https://qianfan.baidubce.com/v2                        |
| Deepseek:Apikey   | bce-v3/ALTAK-VrJzzPHo9HRCH6Lq88QK8/6e9b1f33909b5a43dac2be242351006d72b |
| DeepseekModel     | deepseek-v3 or deepseek-r1                             |

<p align="left">
    <img src="https://static.docs-hub.com/baidu_1740188664080.png" width="300">
</p>

### Configure Alibaba Cloud API Key
*   [API Documentation](https://help.aliyun.com/zh/model-studio/getting-started/what-is-model-studio)
*   [Create OpenAI Compatible APIKEY](https://bailian.console.aliyun.com/?apiKey=1#/api-key)
*   [Alibaba Cloud Available Models](https://bailian.console.aliyun.com/#/model-market/detail/deepseek-v3?tabKey=sdk)

| Configuration Item | Value                                                   |
| ----------------- | ------------------------------------------------------- |
| DeepSeek:baseUrl  | https://dashscope.aliyuncs.com/compatible-mode/v1      |
| Deepseek:Apikey   | sk-cc2054c29cf54fec92503bf7044cf383                    |
| DeepseekModel     | deepseek-v3 or deepseek-r1                             |

<p align="left">
    <img src="https://static.docs-hub.com/aliyun_1740191786952.png" width="300">
</p>

### Configure ByteDance Volcano Engine API Key
*   [API Documentation](https://console.volcengine.com/ark/region:ark+cn-beijing/endpoint)
*   [Volcano Engine Documentation](https://www.volcengine.com/docs/82379/1298454)
*   [Create OpenAI Compatible APIKEY](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey?apikey=%7B%7D)
*   [Volcano Engine Available Models](https://console.volcengine.com/ark/region:ark+cn-beijing/model/detail?Id=deepseek-v3)

| Configuration Item | Value                                                   |
| ----------------- | ------------------------------------------------------- |
| DeepSeek:baseUrl  | https://ark.cn-beijing.volces.com/api/v3               |
| Deepseek:Apikey   | d52e49a1-36ea-55bb-bc6e-65ce789a72f6                  |
| DeepseekModel     | deepseek-v3-241226 or deepseek-r1                      |

<p align="left">
    <img src="https://static.docs-hub.com/vocal_1740192890919.png" width="300">
</p>

### Configure iFLYTEK API Key
*   [iFLYTEK API Documentation](https://www.xfyun.cn/doc/platform/quickguide.htm)
*   [Model Service List](https://training.xfyun.cn/modelService)

| Configuration Item | Value                                                   |
| ----------------- | ------------------------------------------------------- |
| DeepSeek:baseUrl  | https://maas-api.cn-huabei-1.xf-yun.com/v1            |
| Deepseek:Apikey   | sk-U9gPYdkeXmPoJWM33A168717c07544fEc983fF83b884e3785  |
| DeepseekModel     | xdeepseekv3                                            |

<p align="left">
    <img src="https://static.docs-hub.com/xufei_1740194010141.png" width="300">
</p>

### Configure OpenRouter API Key
*   [OpenRouter API Documentation](https://openrouter.ai/deepseek/deepseek-chat:free)
*   [Create APIKEY](https://openrouter.ai/settings/keys)
*   [OpenRouter Model List](https://openrouter.ai/models)

| Configuration Item | Value                                                   |
| ----------------- | ------------------------------------------------------- |
| DeepSeek:baseUrl  | https://openrouter.ai/api/v1                           |
| Deepseek:Apikey   | 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 |
| DeepseekModel     | deepseek/deepseek-chat:free                            |

<p align="left">
    <img src="https://static.docs-hub.com/openrouter_1740194731668.png" width="300">
</p>

## 🤝 Community Exchange

- QQ Group: 957284835 [Click to Join](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=KWl8ZyDCDrBRn4NCXUnr5MkyMTl0nwSK&authKey=iGZm2aZDWgj83khMCftofy7j8YIf0ulFSr4gaeXRbcOpTMWA1RRg%2BHRJ0A%2FVdPaa&noverify=0&group_code=957284835)
- Issue Feedback: [GitHub Issues](https://github.com/zhangrenyang/deepseek/issues)

## 🎁 Bonus Activities

* Get 20 million free DeepSeek Tokens from Silicon Flow, can use advanced models like `DeepSeek V3` and `DeepSeek R1`, limited quantity, first come first served
- [Click to Get Bonus](https://cloud.siliconflow.cn/i/Cz4wrwb8)
- Or scan QR code to get bonus
<p align="left">
    <img src="https://static.docs-hub.com/s_f_1738808704414.png" width="300">
</p>

* Get 50 million free stable full-version tokens from Paixun Computing Cloud
- [Click to Get Bonus](https://ppinfra.com/user/register?invited_by=KYLOWS)
- Or scan QR code to get bonus
<p align="left">
    <img src="https://static.docs-hub.com/5000token_1739329056034.png" width="300">
</p>

* Get free 30k RPM and 5M TPM unlimited speed from Volcano Engine (worth 130 yuan), enjoy super stable full-version DeepSeek R1 and V3
- [Click to Get Bonus](https://www.volcengine.com/experience/ark?utm_term=202502dsinvite&ac=DSASUQY5&rc=Y2SKA17R)
- Or scan QR code to get bonus
<p align="left">
    <img src="https://static.docs-hub.com/5000token_1739329056034.png" width="300">
</p>



## 🚀 特色功能

*   💻 **代码操作**：一键复制、插入代码到当前文件或新文件
*   🔍 **智能分析**：代码解释、错误检测、重构建议、测试生成
*   ✨ **代码补全**：AI 驱动的代码输入建议
*   📝 **自定义提示**：支持添加和管理预定义提示词，提高提问效率
*   💾 **本地存储**：会话记录保存在本地，随时回放、继续和管理
*   🌐 **自定义baseUrl支持**：可配置自己的baseUrl服务器，灵活访问 API
*   🔒 **隐私保护**：所有信息本地存储，不上传任何数据
*   🌍 **多语言**：支持中文、英文等多种语言界面
*   🎯 **模型选择**：支持多种 DeepSeek 模型，满足不同需求
*   🖥️ **本地部署**：支持通过Ollama在本地部署DeepSeek R1,支持知识库，无需联网即可使用

## 📦 安装方式

1.  打开 VS Code
2.  按下快捷键：
    *   Windows/Linux: `Ctrl + Shift + P`
    *   Mac: `Command + Shift + P`
3.  按下 `Ctrl+Shift+P` 打开命令面板
4.  删除`>`后输入 `ext install colourafredi.vscode-deepseek`
5.  按回车键进行安装

<p align="left">
    <img src="https://static.docs-hub.com/install_1739321125692.png" width="300">
</p>

或者直接访问 [VS Code 市场](https://marketplace.visualstudio.com/items?itemName=colourafredi.vscode-deepseek) 安装

## 🛠️ 主要功能

### 1. 代码分析和优化

*   **代码解释**：详细讲解代码逻辑和实现
*   **错误检测**：发现并修复代码中的 BUG
*   **代码重构**：优化代码结构，提升代码质量
*   **测试生成**：自动生成单元测试代码
*   **代码补全**：在输入代码时获得智能代码建议

### 2. 智能对话

*   **上下文对话**：支持多轮对话，理解上下文
*   **流式响应**：实时显示 AI 回答
*   **会话管理**：保存、导出、清理会话记录
*   **自定义提示**：支持预设常用提示词

### 3. 个性化配置

*   **服务器设置**：可配置服务器
*   **模型选择**：支持多种 DeepSeek 模型
*   **API Key 管理**：支持绑定自己的 API Key
*   **模型温度**：设置模型温度（0-2）
*   **token**：设置最大 token 数
*   **top\_p**:设置 top\_p 值
*   **top\_k**:设置 top\_k 值
*   **frequency\_penalty**:设置 frequency\_penalty 值
*   **界面语言**：可切换中文英文等多种界面语言

## 💡 使用指南

### 快速开始

1.  安装插件后，点击 `VS Code` 左侧的 `DeepSeek` 图标
2.  在输入框中输入问题，按回车发送
3.  等待 AI 响应，可以：
    *   复制回答内容
    *   插入到当前文件
    *   创建新文件保存

<p align="left">
    <img src="https://static.docs-hub.com/icon_1739321180871.png" width="300">
</p>

<p align="left">
    <img src="https://static.docs-hub.com/bubble_1739333401974.png" width="300">
</p>

### 代码相关功能

1.  选中代码片段
2.  右键选择 DeepSeek 相关命令：
    *   解释代码
    *   检查错误
    *   重构优化
    *   生成测试

<p align="left">
    <img src="https://static.docs-hub.com/right_1739321297150.png" width="300">
</p>

### 代码补全

DeepSeek 插件提供了强大的代码补全功能，可以帮助您更高效地编写代码。

#### 启用/禁用代码补全

您可以通过以下方式启用或禁用代码补全功能：

1. 通过命令面板：
   - 按下 `Ctrl+Shift+P`（Windows/Linux）或 `Cmd+Shift+P`（Mac）打开命令面板
   - 输入 "DeepSeek: 启用代码补全" 或 "DeepSeek: 禁用代码补全" 并选择相应命令

2. 通过设置：
   - 打开 VSCode 设置（`Ctrl+,` 或 `Cmd+,`）
   - 搜索 "DeepSeek"
   - 找到 "Enable Completion" 选项并勾选或取消勾选

#### 使用代码补全

当代码补全功能启用后，它会在您编写代码时自动提供建议：

1. 开始输入代码，当您停止输入几百毫秒后，补全建议会自动显示
2. 如果您看到灰色的加载指示器，表示正在生成补全内容
3. 补全内容会以灰色文本显示在您的光标位置
4. 按 `Tab` 键接受建议，或继续输入忽略建议

#### 配置代码补全

为了使用代码补全功能，您需要配置以下参数：

1. **API 密钥**：
   - 在设置中搜索 "DeepSeek: API Key"
   - 输入您的 DeepSeek API 密钥

2. **基础 URL**：
   - 默认为 DeepSeek 官方 API 地址
   - 如果您使用本地部署或其他兼容服务，可以修改此设置

3. **模型**：
   - 选择用于代码补全的模型
   - 推荐使用 "deepseek-coder" 或其他代码优化模型

4. **其他参数**（可选）：
   - Temperature（温度）：控制生成结果的随机性，值越低结果越确定
   - Max Tokens（最大令牌数）：控制生成内容的最大长度
   - Top P：控制生成结果的多样性
   - Top K：限制每一步考虑的词汇数量
   - Frequency Penalty（频率惩罚）：降低重复内容的可能性

#### 提示和技巧

- 代码补全最适合在编写新代码时使用，而不是修改现有代码
- 补全功能会根据您的编码上下文提供建议，包括前后的代码内容
- 如果补全结果不符合预期，可以继续输入以获取新的建议
- 在注释中描述您的意图可以帮助模型生成更准确的补全
- 对于复杂的函数或类，先输入函数签名或类定义，然后让补全功能帮您实现细节

<p align="left">
    <img src="https://static.docs-hub.com/autocomplete_1741020534602.png" width="300">
</p>


### 预设管理
你可以自己定义一些自定义提示词方便快速使用
有两种方式可以管理你的自定义提示词
1. 在`Ctrl/Command + Shift + P`命令面板中输入命令
2. 选中任意代码右键选择菜单 

<p align="left">
    <img src="https://static.docs-hub.com/rightclick_1740195691511.png" width="300">
</p>
<p align="left">
    <img src="https://static.docs-hub.com/command_1740195708248.png" width="300">
</p>

1. **增加预定义提示词**(>deepseek:增加预定义提示词)
   - 添加新的预设提示词模板
   - 可以设置提示词名称和内容
   - 支持变量占位符

2. **编辑预定义提示词**(>deepseek:编辑预定义提示词)
   - 修改已有的预设提示词
   - 可以更新提示词名称和内容
   - 删除不需要的预设

3. **选择预定义提示词**(>deepseek:选择预定义提示词)
   - 从预设列表中快速选择提示词
   - 自动填充到对话框
   - 支持搜索过滤

4. **自定义提问**(>deepseek:自定义提问)
   - 使用预设提示词发起对话
   - 可以根据实际需求修改内容s
   - 快速获得 AI 回答

在提问的输入框中可以输入`/`来触发预设提示词下拉列表进行选择

<p align="left">
    <img src="https://static.docs-hub.com/slash_1740195980772.png" width="300">
</p>

也可以在这里删除预设提示词


<p align="left">
    <img src="https://static.docs-hub.com/deleteprompt_1740921738067.png" width="300">
</p>

## 命令说明

*   DeepSeek:检查下面代码是否有 BUG 并给出修复建议 🐛
*   DeepSeek:详细讲解下面代码 💬
*   DeepSeek:重构下面代码并告诉我你改动了哪里 🔧
*   DeepSeek:为下面的代码添加测试 🧪
*   DeepSeek:增加预定义提示词 ➕
*   DeepSeek:编辑预定义提示词 ✏️
*   DeepSeek:选择预定义提示词 🔍
*   DeepSeek:自定义提问 ✏️
*   DeepSeek:清除所有自定义设置🗑️
*   DeepSeek:修改显示语言 🌍
*   DeepSeek:发起提问 ❓
*   DeepSeek:清空列表 🗑️
*   DeepSeek:导出 markdown📤

## ⚙️ 可配置参数

*   `deepseek.baseURL`：设置服务器地址baseURL
*   `deepseek.model`：选择使用的模型
*   `deepseek.apikey`：设置 API Key
*   `deepseek.temperature`：设置模型温度（0-2）
*   `deepseek.max_tokens`：设置最大 token 数
*   `deepseek.roleDefinition`：设置 AI 助手的自定义系统角色定义,默认值为 你是一位编程AI专家，专注于代码和编程领域。你将帮助回答问题并解决编程问题，提供清晰、专业且实用的建议,其它的角色定义参考[此文档](https://github.com/zhangrenyang/awesome-chatgpt-prompts)
*   `deepseek.lang`：设置界面语言
*   `deepseek.top_p`：设置 top\_p 值
*   `deepseek.top_k`：设置 top\_k 值
*   `deepseek.frequency_penalty`：设置 frequency\_penalty 值

## 配置方式

* 文件->首选项->设置->扩展->DeepSeek

<p align="left">
    <img src="https://static.docs-hub.com/settings_1739321490502.png" width="300">
</p>

### 配置官方API Key
*   [官方API Key申请](https://platform.deepseek.com/api_keys)
*   [官方可用模型](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)

| 配置项             | 值                                   |
| --------------- | ----------------------------------- |
| DeepSeek:baseUrl  | https://api.deepseek.com          |
| Deepseek:Apikey | sk-c50d5356a45c4c7988b3df82fb1295e3 |
| DeepseekModel   | deepseek-chat 或者 deepseek-reasoner  |

<p align="left">
    <img src="https://static.docs-hub.com/setupdeepseek_1739332412446.png" width="300">
</p>

### 配置本地部署的DeepSeek R1

*   [DeepSeek R1 本地部署教程](https://github.com/zhangrenyang/deepseek/blob/main/deploy_zh.md)
*   [Ollama 官网](https://ollama.com)
*   [Ollama 模型列表](https://ollama.com/search)

| 配置项            | 值                        |
| -------------- | ------------------------ |
| DeepSeek:baseUrl | http://localhost:11434 |
| DeepseekModel  | deepseek-r1:1.5b         |

<p align="left">
    <img src="https://static.docs-hub.com/setuplocal_1739332236664.png" width="300">
</p>

### 配置硅基流动的API Key
*   [硅基流动的API Key申请](https://cloud.siliconflow.cn/account/ak)
*   [硅基流动可用模型](https://cloud.siliconflow.cn/models)

| 配置项             | 值                                                   |
| --------------- | --------------------------------------------------- |
| DeepSeek:baseUrl  | https://api.siliconflow.cn                      |
| Deepseek:Apikey | sk-kgahvlalrbfjyftxrcoiiliopeblhxsgrxtrrwgiqwwxwxth |
| DeepseekModel   | deepseek-ai/DeepSeek-V3或者deepseek-ai/DeepSeek-R1    |


<p align="left">
    <img src="https://static.docs-hub.com/setupsilicon_1739332328934.png" width="300">
</p>


### 配置派欧算力云的API Key
*   [派欧算力云的API Key申请](https://ppinfra.com/settings/key-management)
*   [派欧算力云可用模型](https://ppinfra.com/model-api/pricing)

| 配置项             | 值                                                   |
| --------------- | --------------------------------------------------- |
| DeepSeek:baseUrl  | https://api.ppinfra.com/v3/openai                      |
| Deepseek:Apikey | sk_ASPYijn-VdsIbkEXtjCFNn0dEkvs6Sko6ZEA4XbWc |
| DeepseekModel   | deepseek/deepseek-v3/community或者deepseek/deepseek-r1/community    |

<p align="left">
    <img src="https://static.docs-hub.com/paixun_1739332114194.png" width="300">
</p>

### 配置腾讯云的API Key
*   [接口文档](https://cloud.tencent.com/document/product/1772/115969)
*   [腾讯云的API Key申请](https://cloud.tencent.com/document/product/1772/115970)
*   [创建兼容OpenAI的APIKEY](https://console.cloud.tencent.com/lkeap/api)
*   [腾讯云可用模型](https://cloud.tencent.com/document/product/1772/115969)

| 配置项             | 值                                                   |
| --------------- | --------------------------------------------------- |
| DeepSeek:baseUrl  | https://api.lkeap.cloud.tencent.com/v1                      |
| Deepseek:Apikey | sk-EsdQJe0M4IsohNh4k0zji0bq9fsDDMQ77dmtn2hOMocTJCfj |
| DeepseekModel   | deepseek-v3或者deepseek-r1  |

<p align="left">
    <img src="https://static.docs-hub.com/tencent_1740186154056.png" width="300">
</p>

### 配置百度云的API Key
*   [接口文档](https://console.bce.baidu.com/iam/#/iam/apikey/list)
*   [创建兼容OpenAI的APIKEY](https://console.bce.baidu.com/iam/#/iam/apikey/list)

| 配置项             | 值                                                   |
| --------------- | --------------------------------------------------- |
| DeepSeek:baseUrl  | https://qianfan.baidubce.com/v2                      |
| Deepseek:Apikey | bce-v3/ALTAK-VrJzzPHo9HRCH6Lq88QK8/6e9b1f33909b5a43dac2be242351006d72b |
| DeepseekModel   | deepseek-v3或者deepseek-r1  |

<p align="left">
    <img src="https://static.docs-hub.com/baidu_1740188664080.png" width="300">
</p>


### 配置阿里云的API Key
*   [接口文档](https://help.aliyun.com/zh/model-studio/getting-started/what-is-model-studio)
*   [创建兼容OpenAI的APIKEY](https://bailian.console.aliyun.com/?apiKey=1#/api-key)
*   [阿里云可用模型](https://bailian.console.aliyun.com/#/model-market/detail/deepseek-v3?tabKey=sdk)

| 配置项             | 值                                                   |
| --------------- | --------------------------------------------------- |
| DeepSeek:baseUrl  | https://dashscope.aliyuncs.com/compatible-mode/v1                      |
| Deepseek:Apikey | sk-cc2054c29cf54fec92503bf7044cf383 |
| DeepseekModel   | deepseek-v3或者deepseek-r1  |

<p align="left">
    <img src="https://static.docs-hub.com/aliyun_1740191786952.png" width="300">
</p>


### 配置字节跳动火山引擎的API Key
*   [接口文档](https://console.volcengine.com/ark/region:ark+cn-beijing/endpoint)
*   [火山引擎文档](https://www.volcengine.com/docs/82379/1298454)
*   [创建兼容OpenAI的APIKEY](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey?apikey=%7B%7D)
*   [火山引擎可用模型](https://console.volcengine.com/ark/region:ark+cn-beijing/model/detail?Id=deepseek-v3)

| 配置项             | 值                                                   |
| --------------- | --------------------------------------------------- |
| DeepSeek:baseUrl  |https://ark.cn-beijing.volces.com/api/v3                      |
| Deepseek:Apikey |d52e49a1-36ea-55bb-bc6e-65ce789a72f6 |
| DeepseekModel   | deepseek-v3-241226或者deepseek-r1  |

<p align="left">
    <img src="https://static.docs-hub.com/vocal_1740192890919.png" width="300">
</p>


### 配置科大讯飞的API Key
*   [科大讯飞接口文档](https://www.xfyun.cn/doc/platform/quickguide.htm)
*   [模型服务列表](https://training.xfyun.cn/modelService)

| 配置项             | 值                                                   |
| --------------- | --------------------------------------------------- |
| DeepSeek:baseUrl  |https://maas-api.cn-huabei-1.xf-yun.com/v1                      |
| Deepseek:Apikey |sk-U9gPYdkeXmPoJWM33A168717c07544fEc983fF83b884e3785 |
| DeepseekModel   | xdeepseekv3  |

<p align="left">
    <img src="https://static.docs-hub.com/xufei_1740194010141.png" width="300">
</p>


### 配置openrouter的API Key
*   [openrouter接口文档](https://openrouter.ai/deepseek/deepseek-chat:free)
*   [创建APIKEY](https://openrouter.ai/settings/keys)
*   [openrouter模型列表](https://openrouter.ai/models)

| 配置项             | 值                                                   |
| --------------- | --------------------------------------------------- |
| DeepSeek:baseUrl  |https://openrouter.ai/api/v1                      |
| Deepseek:Apikey |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 |
| DeepseekModel   | deepseek/deepseek-chat:free  |

<p align="left">
    <img src="https://static.docs-hub.com/openrouter_1740194731668.png" width="300">
</p>


## 🤝 社区交流

- QQ 群：957284835 [点击加入](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=KWl8ZyDCDrBRn4NCXUnr5MkyMTl0nwSK&authKey=iGZm2aZDWgj83khMCftofy7j8YIf0ulFSr4gaeXRbcOpTMWA1RRg%2BHRJ0A%2FVdPaa&noverify=0&group_code=957284835)
- 问题反馈：[GitHub Issues](https://github.com/zhangrenyang/deepseek/issues)

## 🎁 送福利活动

* 免费领取硅基流动 2000 万 DeepSeek Tokens，可以使用`DeepSeek V3`和`DeepSeek R1`等高级模型，数量有限，先到先得
- [点击领取福利](https://cloud.siliconflow.cn/i/Cz4wrwb8)
- 或扫描二维码领取福利
<p align="left">
    <img src="https://static.docs-hub.com/s_f_1738808704414.png" width="300">
</p>


* 免费领取派欧算力云超稳定的满血版5000 万 tokens
- [点击领取福利](https://ppinfra.com/user/register?invited_by=KYLOWS)
- 或扫描二维码领取福利
<p align="left">
    <img src="https://static.docs-hub.com/5000token_1739329056034.png" width="300">
</p>


* 免费领取火山引擎持3万RPM和500万TPM不限速(价值130元)，畅享超稳定的满血版DeepSeek R1 和 V3
- [点击领取福利](https://www.volcengine.com/experience/ark?utm_term=202502dsinvite&ac=DSASUQY5&rc=Y2SKA17R)
- 或扫描二维码领取福利
<p align="left">
    <img src="https://static.docs-hub.com/5000token_1739329056034.png" width="300">
</p>


## FAQ

### 1. self-signed certificate
在使用debian 12系统,最新的vscode  for linux版的时候可能会报错

![](https://static.docs-hub.com/selfsigned_1741146833762.png)

### 方法1: 在VS Code设置中禁用证书验证

1. 打开VS Code设置
2. 搜索 `http.proxyStrictSSL` 或 `http.systemCertificates`
3. 取消勾选这些选项

### 方法2: 通过命令行添加环境变量

打开终端，使用以下命令启动VS Code:

```
NODE_TLS_REJECT_UNAUTHORIZED=0 code
```

### 方法3: 永久设置环境变量

编辑您的shell配置文件(如`.bashrc`或`.zshrc`):

```
echo "export NODE_TLS_REJECT_UNAUTHORIZED=0" >> ~/.bashrc
source ~/.bashrc
```

