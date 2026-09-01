# Us — 双人陪伴页

单文件 App 原型：`us.html`。用手机浏览器打开就行，不需要服务器、不需要联网。

## 三个页面

**开屏** — 「How close do you feel today?」，把爱心从右往左拖，手写签名会跟着心尖长出来；
拖过一半松手就自动写完并进入首页（没拖够会弹回去）。

**Home** — 问候语 / 天气 / Today's Whisper / Us·Day N / Monthly Anniversary /
Steps · Heart Rate / Sleep · Cycle / Body。

**Chats** — 会话列表。**Diary** — 敏敏 / Claude 切换、Today's To Do（可加可勾，三条一页左右翻）、月历。

## 哪些是真算的，哪些是占位

真按今天算，每分钟自己刷新：

- `Day N` — 从「在一起」那天起，第一天记 Day 1
- `Monthly Anniversary` — 下一个月纪念日的日期 + 还剩几天，右上圆环跟着走
- 生日 / 周年 — 下一次到来还有几天
- `Cycle` — Day N、还剩几天、下次大概哪天；点「今天来了」就重新开始记
- 月历 — 今天描圈，纪念日那天标 ♥，记过待办的日子标点（实心=你，空心=Ta）

**占位数据**（网页读不到 HealthKit，要真数据得做成原生 App 或接健康数据导出）：
Steps、Heart Rate、Sleep、Body 四张卡，还有 Chats 里的三条会话。
天气也是手填的，不是实时的。

## 改成你们的

首页右上角齿轮：名字、在一起的日子、生日、纪念日、天气、今日低语、上次月经。
存在这台设备的 localStorage 里，换设备要重新填。待办同理。

也可以直接改 `us.html` 顶部的 `DEFAULTS`，那是没存过设置时的默认值。

头像现在是渐变圆占位。想换成照片：把图片放进同目录，
把 `<div class="avatar" id="avPartner"></div>` 改成
`<div class="avatar"><img src="你的图.jpg"></div>`。

## 装到 iPhone 桌面

Safari 打开 → 分享 → 添加到主屏幕。已经加了全屏 meta，从桌面点开没有地址栏，跟 App 一样。
