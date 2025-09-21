---
title: 【生成式AI時代下的機器學習(2025)】第二講：一堂課搞懂 AI Agent 的原理 (AI如何透過經驗調整行為、使用工具和做計劃) - YouTube
description: >-
  投影片連結：https://docs.google.com/presentation/d/1kTxukwlmx2Sc9H7aGPTiNiPdk4zN_NoH/edit?usp=sharing&ouid=115046073158939078465&rtpof=true&sd=true5:45
  此處應為 AlphaZ...
author: YouTube
source: https://www.youtube.com/watch?v=M2Yg1kwPpts
created: "2025-09-08"
tags:
  - hover-notes
  - youtube
---

![00:07:03](hover-notes-images/screenshot-01K4M1XRN4AYSNBB369X8HWN9K.png)
[00:07:03](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=423.492069s)
### 如何打造 AI Agent？直接用 LLM
- AI Agent 再次爆红并非新技术本身。
- LLM 变强后，人们开始考虑能否直接用 **Large Language Model** 来实现拥有 Agent 的渴望。
- 拿**下棋**做例子。

![00:08:59](hover-notes-images/screenshot-01K4M22F97BVR0GD218WRTWF18.png)
[00:08:59](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=539.856248s)

![00:11:27](hover-notes-images/screenshot-01K4M26QSF89AQHJ3WZEFKKPXT.png)
[00:11:27](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=687.581278s)
### LLM 能不能下棋？
- **BIG-bench**
- [https://arxiv.org/abs/2206.04615](https://arxiv.org/abs/2206.04615)
- **BIG-bench** 是语言模型领域常用的 benchmark。
- 2022年（ChatGPT 之前）就有人尝试用当时的语言模型下西洋棋。
- 需要将棋盘上的黑子和白子的位置转换成文字描述，输入给语言模型。
- 语言模型会根据棋盘状态给出下一步的建议。
- 右上角图中，橙色线是正确答案，绿色线是当时各语言模型给出的答案。
- 当时没有一个语言模型给出正确答案。
- 即使当时的语言模型没有给出正确的答案，但它们选择的路径符合西洋棋规则。
- 较弱的模型会随意移动，不理解西洋棋的规则。
- 这是早期的研究，现在有更强大的**LLM**。
- ChatGPT-01 和 D6R-1 两个模型下西洋棋。
- 两个模型杀得难分难解，但实际上它们太弱了。
- 不符合西洋棋的规则，例如把兵当做马来用。
- D6R-1 模型下棋时会**无视规则**，比如主教越过棋子，或者突然在对方阵地**空降**自己的棋子吃掉对方。
- D6R-1 甚至能在棋盘上**凭空变出**一个“城堡”棋子。
- 最后，D6R-1 用自己的“城堡”吃掉自己的兵，然后**宣布获胜**，让 ChatGPT-01 投降。
- ChatGPT-01 思考后承认失败并投降。这表明 LLM 仍然**不理解**西洋棋的真正规则。
- LLM 在下棋方面仍有进步空间。
- 重点在于如何让 LLM 更好地作为 **AI Agent** 运作。
- 目标是使语言模型在作为 AI Agent 时运行更顺利。
### 从 LLM 的角度来看 Agent
- LLM 得到一个目标（Goal）。
- LLM 得到一个观察（Observation）。
- LLM 得到 **Goal** 和 **Observation**。
- 根据 **Observation** 决定下一步 **Action**。
- **Action** 影响外部环境，产生新的 **Observation**。
- LLM 不断重复这个过程。
- LLM 凭借其文字接龙能力完成上述过程。
- 从 LLM 角度来看，将其作为 AI Agent 使用时，它做的仍然是文字接龙。

![00:12:01](hover-notes-images/screenshot-01K4M27DZWM0J1DHJAAVNYHRCH.png)
[00:12:01](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=721.7491s)
- **AI Agent** 并非 LLM 新技术，更像是 LLM 的应用。
- 本课程不涉及模型训练，依赖现有语言模型能力。
- AI Agent 并非最近才热门，2023年春天已火过一次，例如：
- AutoGPT
- AgentGPT
- BabyAGI
- Godmode
- 2023 年春天，许多人使用 ChatGPT 作为底层语言模型来构建 **AI Agent**。
- 当时最流行的 **AI Agent** 包括 AutoGPT、AgentGPT、BabyAGI 和 Godmode。
- 2023 年的机器学习课程中，有一节课专门讨论了当时的 **AI Agent**。
- 2023 年 **AI Agent** 的热潮消退，因为人们发现这些 AI Agent 没有想象中那么有用。
- **以 LLM 运行 AI Agent 的优势**
- 传统 Agent (如 AlphaGo):
    - 只能执行有限的、事先设定好的行为。
    - AlphaGo 只能在 19x19 的棋盘上选择落子位置。
    - 行为选择局限于 19x19 个选项。

![00:14:27](hover-notes-images/screenshot-01K4M2ACVS7A66TZYRY370WQE7.png)
[00:14:27](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=867.458474s)
- **以 LLM 运行 AI Agent 的优势**
- LLM 有了几乎无限的可能。
- LLM 可以讲任何话，产生各式各样近乎无穷无尽的输出。
- AI Agent 可以采取的行动不再有局限，有更多的可能性。
- LLM 可以凭借其有各式各样输出的能力，直接呼叫一些工具来帮忙解决它本来解决不了的问题。

![00:15:36](hover-notes-images/screenshot-01K4M2BT2G1RCAXMTSFWYH223W.png)
[00:15:36](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=936.911922s)
- 传统 Agent 需要定义 **Reward**。例如，写代码时出现编译错误，则 Reward 为 -1。Reward 的数值通常难以确定。
- LLM Agent 不需要人为定义 Reward，可以直接读取编译错误日志，并理解日志内容，从而对程序进行修改。

![00:16:12](hover-notes-images/screenshot-01K4M2CHD46RJQXYD54VNS57JY.png)
[00:16:12](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=972.559951s)
### 以 LLM 运行 AI Agent 的优势
- LLM Agent 不需要人为定义 Reward，可以直接读取编译错误日志，理解日志内容，并修改程序。
- 传统 Agent Reward 只有一个数值，而 LLM Agent 直接提供 error 的 log，给 Agent 更丰富的信息，更容易按照环境给的反馈和状态来修改行为。
### AI Agent 案例：AI 村民组成的虚拟村庄
- 2023 年成立。
- 里面的 NPC 全都用语言模型运行。
- NPC 运行方式：
- 每个 NPC 都有预先设定的目标，例如举办情人节派对或准备考试。
- NPC 会观察环境，但由于 LLM 只能读取文字，环境信息需要转换为文字描述。
- 环境信息对 LLM 来说就像是：旁边的人在做什么，例如 Eddy 在读书，厨房水槽是空的，Isabella 正在装饰房间等。
- 根据这些观察，LLM 决定下一步行动。

![00:17:29](hover-notes-images/screenshot-01K4M2E34BKYA014KHZXVFMVG7.png)
[00:17:29](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1049.031301s)
- NPC 设定目标，例如举办派对、准备考试。
- LLM 读取文字化的环境信息（例如：Eddy 在读书，厨房水槽是空的）。
- LLM 根据观察决定行动。
- 2023 年，有人用 AI 运行 Minecraft 的 NPC 实验。
- AI Agent 案例：Minecraft 中 AI 组织了自己的交易金融体系、政府、宪法，并自己管理。
### AI Agent 案例：让 AI 使用电脑
- 之前的游戏可能不容易接触，对现实世界影响小。
- 可能会接触到的 AI Agent 是让 AI 真正使用电脑。
- 听起来有点怪，AI 本身就是电脑，但现在要像人类一样使用另一个低端电脑来做事。
- 例子：Cloud Computer Use 和 ChatGPT 的 Operator。
- Operator 界面会建议可以做的事情，例如订披萨、预约下周的行程。

![00:19:10](hover-notes-images/screenshot-01K4M2G4VC909Z1P7NQJC00QVQ.png)
[00:19:10](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1150.093032s)
### AI Agent 案例：让 AI 使用电脑
- 目标：用户的输入（例如，订披萨、网上购物）。
- Observation：电脑的屏幕画面（可直接将图片或电脑画面作为输入）。
- Agent 的决定：按下键盘上的哪个键或鼠标的哪个按钮。
- 让 AI 使用电脑并非最近才开始。
- World of Bits: An Open-Domain Platform for Web-Based Agents (ICML, 2017)
- 2017 年的论文 *World of Bits* 尝试使用 AI Agent。该论文将自己定位为 **Web-based Agent**。
- 当时可互动的页面较为原始。
- 当时没有大型语言模型，因此采用 CNN 直接接收屏幕画面作为输入。
- 输出是鼠标点击位置或键盘按键。
- 探索 AI Agent 是否能在网络世界中工作。
- 2023年暑假开始出现 Mind2Web, WebArena, Visual WebArena 等，与今天的 Operator 类似。
- 让语言模型看屏幕画面或 HTML 代码，然后自己决定下一步行动。
- 期望最终解决问题。

![00:21:22](hover-notes-images/screenshot-01K4M2JV003PR9K85JX3CJ225C.png)
[00:21:22](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1282.331197s)

![00:21:37](hover-notes-images/screenshot-01K4M2K56XCM55HDG8M28CW7FM.png)
[00:21:37](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1297.994962s)
- **AI Agent 案例：用 AI 训练模型**
- 目标：通过 strong baseline。
- 提供训练数据给 LLM。
- LLM 写程序，用训练数据训练模型。
- 得到模型的正确率，根据正确率重新写程序。
- 如此循环往复。
- 有很多知名的用 AI 来训练模型的案例。

![00:22:12](hover-notes-images/screenshot-01K4M2KVG5RFW2HGFYJS6A3J49.png)
[00:22:12](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1332.238509s)
### AI Agent 案例：用 AI 训练模型
- AI 可以查看技术报告标题，了解研究方向，例如：
- **Machine Learning Engineer Agent**
- 使用 **multi-agent framework** 解决 **data science competition** (AutoCargo)。
- 通过作业体验 AI Agent 在机器学习课程中的应用。
### AI Agent 案例：用 AI 做研究
- Google 推出 AI Cosientist，但模型未公开。
- AI Cosientist 主要用于研究，但目前有局限，无法实际进行实验。
### AI Agent 案例：用 AI 做研究
- 给 AI 提供研究想法，AI 给出完整的 proposal。
- Google 推出 AI Cosientist，用 AI Agent 辅助研究人员。
- AI Cosientist 模型未公开。
- 实际效果未知，可能存在夸大宣传。
### 邁向更加真實的互動情境
- 目前 AI Agent 的互动方式局限于**回合制互动**：`Observation` -> `Action`。

![00:23:53](hover-notes-images/screenshot-01K4M2NX16N6HWCMJZ2B80XED5.png)
[00:23:53](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1433.003149s)
- 目前 AI Agent 的互动方式局限于**回合制互动**：`Observation` -> `Action`。
- 需要更**即时**的互动，因为外在环境不断改变。
- 模型在决定执行 `Action 1` 时，外在环境可能已改变，模型应立即转换行动。
- 语音对话需要这种互动模式。
- 文字对话，如使用 ChatGPT，大家比较熟悉。

![00:24:26](hover-notes-images/screenshot-01K4M2PJJFVM62Q6XD30A5G66T.png)
[00:24:26](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1466.04315s)
- 人与人之间的对话并非简单的回合制互动。
- 对话中可能出现互相打断或同时提供反馈的情况。
- 这些反馈可能没有特定语义，仅表示“我在听”。
- 这种反馈对于流畅交流至关重要。
- 目标：使 AI 在语音互动中更像人与人之间的互动，而非一问一答。

![00:25:25](hover-notes-images/screenshot-01K4M2QS7G7VJ850R6MYSXYRZC.png)
[00:25:25](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1525.358575s)
- GPT-4o 的 **Voice Mode** (高级语音模式) 在某种程度上实现了这种**即时互动**。
- 例如，用户说“讲个故事”，这是 AI 观察到的第一个 `Observation`。
- AI 开始讲故事，用户说“ok”。这个“ok”是第二个 `Observation`。
- 对于 AI 来说，这个 `Observation` 不需要改变当前行为，故事继续讲下去。
- 但如果用户说“这不是我想听的故事”，AI 需要立即识别出这个 `Observation` 意味着需要改变行为。

![00:25:44](hover-notes-images/screenshot-01K4M2R5P69TY7YN10EPRRCJXT.png)
[00:25:44](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1544.497883s)
### 邁向更加真實的互動情境(續)
- GPT-4o的**Voice Mode**实现了某种程度的**即时互动**。
- 更**即时**的互动：模型在决定执行`Action 1`时，外在环境可能已改变，模型应立即转换行动。
- 语音对话需要这种互动模式。
- 目标：使 AI 在语音互动中更像人与人之间的互动，而非一问一答。
- 如何做到这种即时互动（非回合制互动）超出本课程范围。
- 可阅读相关文章，评估现有语音模型互动能力。
- 文章对可互动的语音模型做了比较完整的调研(截至今年1月)。
### 邁向更加真實的互動情境(續)
- 课程中引用的论文原则：
- 尽量使用 **arXiv** 链接。
- **arXiv**：
    - 用于发布研究，先于期刊或会议。
    - AI 领域变化快，传统发表周期长，不适用。
- `arXiv` 上的文章通常比国际会议更及时，AI 领域发展迅速，传统审稿周期太长。
- 很多重要文章直接发布在 `arXiv` 上，甚至不投稿国际会议。
- 国际会议现在更像是“经典回顾”，因为最新研究几乎都在 `arXiv` 上。
- `arXiv` 允许直接公开，无需审稿，确保研究成果能迅速被全世界看到。

![00:28:20](hover-notes-images/screenshot-01K4M2VB6MRVNZSHHYKF27Y51Z.png)
[00:28:20](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1700.51875s)
### AI Agent 关键能力剖析
- 三个面向分析AI Agent的关键能力：
- AI 如何根据经验调整行为
- AI 如何使用工具
- AI 如何执行
### AI 如何根据经验调整行为
- AI Agent需根据经验调整行为。
- 例子：AI程序员接到任务，写程序。
- 编译后有错误信息，AI应根据错误信息修正程序。
- 收到反馈时，传统做法需要定义 **Reward**。

![00:29:52](hover-notes-images/screenshot-01K4M2X74VC2XZW6CNHZJE4NG4.png)
[00:29:52](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1792.62187s)
- 传统做法需定义 **Reward**。
- 本课程**不训练模型**，所以不调整参数。
- 直接给LLM错误信息，它下次写的程序就会不一样。
- LLM根据错误信息修正程序，不微调参数。
- **AI 如何根据经验调整行为**
- 即使是同一个模型，不同的输入会导致不同的输出。
- 如果 LLM 接收到包含错误信息的输入，它接下来的输出结果可能更准确。
- 大量证据表明，语言模型可以根据反馈改变行为，无需调整参数。
- LLM 根据错误信息修正程序，不微调参数。

![00:31:07](screenshot-01K4M3004VEKM72J7Q61PZYJ9E.png)
[00:31:07](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1867.547103s)
-  **AI 如何根据经验调整行为**：将过去的经验都存起来，让模型根据过去的经验调整行为，即把过去所有发生的事情一股脑给它。
- 语言模型每次做决策时都要回忆一生的经历。
- 也许在第 100 步还行，到第 1 万步时，过去的经验太长了，人生信息太多，可能没有足够的算力来回顾一生。
- **AI 如何根据经验调整行为**（续）
- LLM 每次做决策时都要回忆一生的经历可能导致算力不足。
- 有些人拥有超忆症，能记住一生中所有发生的事情，就像一个影印机。
- 超忆症也被认为是一种疾病。
- 拥有超常自传式记忆的人也被称为超忆症患者。
- 超忆症患者可能不到100人。
- 记住所有事情对患者来说可能是一种负担。
- 语言模型不需要记住一生的所有经历，只需记住最近的经历。
- 语言模型需要一种机制来记住最近的经历，并忘掉很久以前的经历。
- **记忆体 (Memory)**：记住最近的经历，忘掉很久以前的经历。
- **检索 (Retrieval)**：从记忆体中检索相关信息。
-
- 检索增强生成(Retrieval Augmented Generation, RAG)：从数据库中检索相关信息，再生成答案。
- 记忆体和检索是根据经验调整行为的关键。
- 例子：AI 程序员写程序，编译后有错误信息，AI 根据错误信息修正程序，并记住这次错误，下次避免。
- AI Agent 通过记忆体记住最近的经历，通过检索从数据库中检索相关信息，从而根据经验调整行为。
- **AI 如何使用工具**
- LLM 可以呼叫外部工具来完成任务。
- 工具是预先写好的程序。
- LLM 决定何时使用哪个工具。
- 例子：LLM 无法进行数学计算，可以呼叫计算器工具。
- LLM 可以将文字发送给计算器工具，计算器工具返回结果。
- LLM 还可以使用搜索引擎工具。
- LLM 可以将关键词发送给搜索引擎工具，搜索引擎工具返回搜索结果。
- LLM 无法访问互联网，但可以使用搜索引擎工具来访问互联网。
- 工具是预先写好的程序，LLM 决定何时使用哪个工具。

![00:33:42](hover-notes-images/screenshot-01K4M334TMKB5XMYJF9V0PEVWT.png)
[00:33:42](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=2022.305226s)

![00:33:37](hover-notes-images/screenshot-01K4M331CN8QD16YYVK319VXZG.png)
[00:33:37](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=2017.036885s)
- 即使是同一个模型，不同的输入会导致不同的输出。
- LLM 接收到包含错误信息的输入，它接下来的输出结果可能更准确。
- 大量证据表明，语言模型可以根据反馈改变行为，无需调整参数。
- LLM 根据错误信息修正程序，不微调参数。
-  **AI 如何根据经验调整行为**：将过去的经验都存起来，让模型根据过去的经验调整行为，即把过去所有发生的事情一股脑给它。
- 语言模型每次做决策时都要回忆一生的经历。
- 也许在第 100 步还行，到第 1 万步时，过去的经验太长了，人生信息太多，可能没有足够的算力来回顾一生。
- **AI 如何根据经验调整行为**（续）
- LLM 每次做决策时都要回忆一生的经历可能导致算力不足。
- 有些人拥有超忆症，能记住一生中所有发生的事情，就像一个影印机。
- 超忆症也被认为是一种疾病。
- 拥有超常自传式记忆的人也被称为超忆症患者。
- 超忆症患者可能不到100人。
- 记住所有事情对患者来说可能是一种负担。
- 语言模型不需要记住一生的所有经历，只需记住最近的经历。
- 语言模型需要一种机制来记住最近的经历，并忘掉很久以前的经历。
- **记忆体 (Memory)**：记住最近的经历，忘掉很久以前的经历。
- **检索 (Retrieval)**：从记忆体中检索相关信息。
- 检索增强生成(Retrieval Augmented Generation, RAG)：从数据库中检索相关信息，再生成答案。
- 记忆体和检索是根据经验调整行为的关键。
- 例子：AI 程序员写程序，编译后有错误信息，AI 根据错误信息修正程序，并记住这次错误，下次避免。
- AI Agent 通过记忆体记住最近的经历，通过检索从数据库中检索相关信息，从而根据经验调整行为。
- **AI 如何使用工具**
- LLM 可以呼叫外部工具来完成任务。
- 工具是预先写好的程序。
- LLM 决定何时使用哪个工具。
- 例子：LLM 无法进行数学计算，可以呼叫计算器工具。
- LLM 可以将文字发送给计算器工具，计算器工具返回结果。
- LLM 还可以使用搜索引擎工具。
- LLM 可以将关键词发送给搜索引擎工具，搜索引擎工具返回搜索结果。
- LLM 无法访问互联网，但可以使用搜索引擎工具来访问互联网。
- 工具是预先写好的程序，LLM 决定何时使用哪个工具。
- 超忆症患者日常生活可能受影响，因为不断回忆人生，易陷入冗长回忆，难以抽象思考。
- 记忆被琐事占据，影响抽象思维。
- AI Agent 记住一生所有经历并非好事，当人生过长时，可能不利。
- `Memory`：AI Agent 调整行为的方式之一，类似于人类的**长期记忆**。
- 将过去的 `Observation` 和 `Action` 存储在 `Memory` 中。
- 当 AI Agent 遇到新的 `Observation` 时，可以从 `Memory` 中检索相关信息，帮助其做出正确的决策。
- **AI 如何根据经验调整行为**：
- 语言模型可以根据反馈改变行为，无需调整参数。
- 语言模型每次做决策时都要回忆一生的经历。
- 将过去的经验都存起来，让模型根据过去的经验调整行为，即把过去所有发生的事情一股脑给它。

![00:31:15](hover-notes-images/screenshot-01K4M38J7C1JP0YBYBT2P8CKST.png)
[00:31:15](https://www.youtube.com/watch?v=M2Yg1kwPpts&t=1875.333949s)
- LLM每次做决策时都要回忆一生的经历可能导致算力不足。
- 有些人拥有**超忆症**，能记住一生中所有发生的事情，就像一个影印机。
- **超忆症**也被认为是一种疾病。
- 拥有超常自传式记忆的人也被称为**超忆症**患者。
- **超忆症**患者可能不到100人。
- 记住所有事情对患者来说可能是一种负担。
- 语言模型不需要记住一生的所有经历，只需记住最近的经历。
- LLM 需要记住最近的经历，并忘掉很久以前的经历。
- 记住所有事情对患者来说可能是一种负担。
- 语言模型每次做决策时都要回忆一生的经历。
- 有些人拥有超忆症，能记住一生中所有发生的事情，就像一个影印机。
- 超忆症也被认为是一种疾病。
- 拥有超常自传式记忆的人也被称为超忆症患者。
- **超忆症**患者生活可能受影响，陷入冗长回忆，影响抽象思考。
- `Memory`：AI Agent 调整行为的方式，类似于人类的**长期记忆**。
- 存储过去的 `Observation` 和 `Action`。
- 新 `Observation` 时，从 `Memory` 检索相关信息，辅助决策。
- AI Agent 不需记住一生所有经历，人生过长可能不利。
- 记住所有经历，难以抽象思考。
- 让 AI Agent 记住一生所有经历，每次决策都基于一生经验可能不利。
- **记忆体 (Memory)**
- 类似于人类的**长期记忆**。
- 存储过去的 `Observation` 和 `Action`。
- 新 `Observation` 时，从 `Memory` 检索相关信息，辅助决策。
- AI Agent 不需记住一生所有经历，人生过长可能不利。
- 记住所有经历，难以抽象思考。
- 让 AI Agent 记住一生所有经历，每次决策都基于一生经验可能不利。