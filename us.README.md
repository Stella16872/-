# Us — 双人陪伴页

单文件 App 原型：`us.html`。手机浏览器打开就行，不需要服务器、不需要账号，**也不需要联网**。

## 第一次打开

会先让你填三样：你的名字、Ta 的名字、在一起的第一天。填完才进开屏。
之前版本里的示例数据（名字、日记、聊天、待办）已经全部清掉，存储也换了新的命名空间，
旧数据不会再冒出来。想再来一次：设置里有「清空所有数据」。

## 三个主页面

**开屏** — 「How close do you feel today?」抓住最右边的爱心，一路拖到最左边那个小圆环，
手写签名跟着心尖一路长出来铺满整行。**必须拉到底才开锁**；没拉满松手会弹回原位。
抓的时候手指落在爱心上或它右边都行；只要手指划到最左端就算拉满，
不管当初是从哪儿抓的。连续两次没拉满会出现「直接进入」，免得被卡住。

今天的亲密度不在这儿记了——开屏是开锁的仪式，值去首页的 Closeness 卡片里拖。

**Home** — 问候 / 天气 / 今日低语 / Us·Day N / **Closeness** / Monthly Anniversary /
**Moments · Wishlist · Letters** 入口 / Steps · Heart Rate / Sleep · Cycle / Body。

**Chats** — 你们俩的一条对话。可以切换「以谁的身份说」，两个人共用一台设备时能来回写。
点一下气泡会露出「删除这条」，再点一下收起。

**Diary** — 双人切换、Today's To Do、月历。

## 二级页

| 从哪进 | 到哪 | 干什么 |
|---|---|---|
| 点 Closeness 卡 | **Closeness** | 拖爱心记下今天的值；30 天曲线、平均/最高/记录天数、全部记录 |
| 点 Moments | **Moments** | 自己加要记住的日子，选「每年」或「只此一次」，自动倒数排序；点某一行可以改，× 删除 |
| 点 Wishlist | **Wishlist** | 想一起做的事，做完打勾，记下哪天做的 |
| 点 Letters | **Letters** | 写给以后的信，设一个开封日；没到日子是封着的黑卡，只显示还有几天 |
| 点今日低语黑卡 | **Whispers** | 顶部直接写今天的低语，写新的旧的自动归档；下面是更早的记录 |
| Diary 里的「全部日记」 | **全部日记** | 按日期倒序列出，可全文搜索，命中处高亮 |
| 点 Today's To Do | **To Do** | 未完成 / 已完成两栏 |
| Diary 的笔 / 点月历某天 | **写日记** | 边写边存 |

首页 Monthly Anniversary 下面那两格，显示的是**最近的两个 Moments**，加了才有。

## 哪些是真算的

按今天实算、每分钟刷新：Day N、月纪念日日期与倒数、Moments 倒数、经期 Day N 与下次预计、
亲密度的平均与对比。
月历：今天是金粉渐变圆点，纪念日和 Moments 标 ♥，写过日记或记过待办的日子标点（实心=你，空心=Ta）。

**Steps / Heart Rate / Sleep / Body 现在是手动记录的真数据**：点卡片就能填今天的值，
按日期存。步数是最近 7 天柱状图（今天描金），心率是 7 天折线，睡眠是 7 天记录格 +
平均时长，Body 显示今天的四项。没填的日子留空，不会编数字。
（网页读不到 HealthKit，想自动同步得做成原生 App 或接健康数据导出。）
天气仍是手填的。

## 设置里还有

- **外观**：跟随系统 / 浅色 / 深色。深色是深紫黑配金粉，不是简单反色。
- **导出备份**：存成一个 JSON 文件。**导入备份**：读回来。换手机靠这个。
- **清空所有数据**：两次确认，不可撤销。

改「今日低语」时，旧的那句会自动收进 Whispers 的 Earlier。

## 设计

暖象牙底 + 香槟金 + 灰调玫瑰。金和粉只做点缀：
金在描边、纪念日弧、今日步数柱、小标题；粉在心形、心率线、经期弧、你的气泡；
底色右上和左下各一处极淡晕染，叠一层细颗粒。
标题 Cormorant Garamond，正文中文用苹方。

**字体已内嵌进 HTML**，不联网也是对的样子。用的是可变字重版本（300–700 一个文件覆盖，
拉丁子集 37.6 KB，base64 后约 50 KB），所以整个文件 133 KB。
中文没法内嵌（一套中文衬线动辄几 MB），回落到系统宋体，iPhone 上是 Songti SC。
Cormorant 默认是旧式数字（7、9 会掉到基线以下，0 长得像 O），已统一改成等高数字，
需要对齐的数字再加等宽。

> Cormorant Garamond：Copyright 2015 The Cormorant Project Authors
> (github.com/CatharsisFonts/Cormorant)，SIL Open Font License 1.1。

## 存在哪

全部在这台设备的 `localStorage`，键名前缀 `us.v2.`，不上传任何地方。
清浏览器数据会一起没掉，重要的话记得先导出备份。

> **Mac 上双击打开本地文件要注意**：Safari 在 `file://` 下会禁掉 localStorage，
> 页面能用但关掉就全没了。首页顶部会出现一条粉色提示告诉你这件事。
> 想正常保存，用手机浏览器打开，或者把文件放到任意网页服务器上
> （比如仓库开了 GitHub Pages 就直接访问 `/us.html`）。

头像是「金粉渐变圆 + 名字首字」的占位。换照片：图片放同目录，把
`<div class="avatar" id="avPartner"></div>` 改成
`<div class="avatar"><img src="你的图.jpg"></div>`。

## 装到 iPhone 桌面

Safari 打开 → 分享 → 添加到主屏幕。已加全屏 meta，从桌面点开没有地址栏。

---

# projects.html — 项目索引

同目录下还有一个 `projects.html`，是所有 GitHub 项目的导航页：
`https://stella16872.github.io/-/projects.html`

**它会自己更新**：每次打开都实时调 GitHub 公开 API 读一遍仓库列表，
新项目推上去、开好 Pages，刷新这页就自动出现，不用改代码。
读不到 GitHub 时（断网、限流）退回到内置的快照，并在顶部标明。

给仓库填了 Description（仓库页右上角 About 旁边的齿轮），这里会跟着显示。

几个需要特殊处理的项目写在 `projects.html` 里的 `OVERRIDE`：
Simulator 根目录没有 index.html 所以链接带文件名；`-` 拆成 Us 和年上・信两条；
article-generator（Flask 后端）和 desktop-pet（桌面程序）标为 Pages 跑不了。

---

# 让 Ta 真的回话（worker.js）

Chats 里的对方默认只是个占位——你写什么它都不会回。想让它真的由 Claude 来回，
需要一个中转，因为 **API 密钥绝对不能写进 `us.html`**（仓库是公开的，等于把
账号余额挂在网上）。`worker.js` 就是这个中转，也是唯一碰到密钥的地方。

## 部署（全程在浏览器里点，不用装任何东西）

1. console.anthropic.com 生成一个 API key，账户里充点钱
2. dash.cloudflare.com → Workers & Pages → Create → Create Worker → 起名 → Deploy
3. Edit code，把 `worker.js` 全部内容粘进去 → Deploy
4. Settings → Variables and Secrets，加两条 **Secret**：
   - `ANTHROPIC_API_KEY` — 第 1 步的 key
   - `SHARED_SECRET` — 你自己编一串暗号
5. 打开 app → 设置 → 填「接口地址」（Worker 网址）和「暗号」（和上面一致）

配好后 Chats 顶部会显示「已接上」。你以自己的身份发消息，Ta 就会回；
以 Ta 的身份发则不会触发（那是你替他写）。

## 会发送什么

每次只带：两个人的名字、在一起第几天、你今天的低语、你今天没做完的待办、
今天的亲密度，加上最近 30 条对话。

**日记不会发送。** 那是最私密的部分，默认留在本机。想让它也知道，跟我说。

## 几件要知道的事

- **它不是同一个 Claude。** 不记得你和 Claude Code 里聊过什么，只知道上面
  那些每次带过去的内容。
- 模型默认 `claude-opus-5`。想省钱在 Worker 里加环境变量 `MODEL`，
  换成 `claude-sonnet-5` 或 `claude-haiku-4-5`。陪伴式的短对话，Haiku 就够。

## 接 DeepSeek（或别家）

Worker 里三条环境变量：

| 变量 | 填什么 |
|---|---|
| `BASE_URL` | `https://api.deepseek.com` |
| `API_FORMAT` | `openai` |
| `MODEL` | `deepseek-chat`（要会推理的用 `deepseek-reasoner`） |

密钥那条改叫 `API_KEY`（老的 `ANTHROPIC_API_KEY` 仍然认）。
地址写 `https://api.deepseek.com`、`.../v1`、或写全 `.../chat/completions` 都行，
Worker 会自己补齐，不会拼出 `/v1/v1/`。

DeepSeek 比 Claude 便宜一个数量级，对陪伴式短对话完全够用。
只是它跟 Claude 是两个不同的模型，说话的味道不一样，你试试看喜不喜欢。

## 用第三方中转站

Worker 支持把请求转去别的地址，加两个环境变量即可：

- `BASE_URL` — 中转站给你的地址（默认 `https://api.anthropic.com`）；写到域名、
  写到 `/v1`、或写全路径都可以
- `API_FORMAT` — 中转站若是 OpenAI 格式（`/v1/chat/completions` + `Bearer`）就填
  `openai`；兼容官方格式的填 `anthropic` 或不填

Chats 顶部会显示**这次实际用的模型名**（上游返回的 `model` 字段）。
中转站如果偷偷把 Opus 换成便宜模型，这里就会露出来。

**要想清楚再用**：你发过去的每一句都会经过那个中转站——两个人的名字、
今天的低语、待办、全部聊天记录。它能看到，也能存下来。这个 app 装的
恰恰是最私密的东西。日记默认不发送，但其余的都会过一遍。
另外转售 API 通常不被官方允许，中转站随时可能断，预付的钱也可能拿不回来。
- Worker 里有限流：一次最多 40 轮、总字数 12000，防止网址被人捡去跑大任务。
- 出错时聊天里会出现一条粉色提示，写明原因（暗号不对、余额不足等）。
