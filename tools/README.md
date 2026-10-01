# hoi4_text_extract.py — 从钢铁雄心4 mod 里导出国策 / 事件 / 决议文案

把 mod 里散落在脚本和本地化文件中的文案，整理成一份按国策树、事件、决议分组的 Markdown（可选 JSON），方便直接阅读。
写的时候针对的是 **烈焰升腾（The Fire Rises）** 和 **潜龙腾渊** 的中国线，但对任何 HOI4 mod 都能用。

只需要 Python 3.8+，不需要装任何库。

## 1. 找到 mod 文件夹

在 Steam 订阅后，mod 在：

```
<Steam 安装目录>/steamapps/workshop/content/394360/<创意工坊ID>/
```

| mod | 创意工坊 ID |
| --- | --- |
| 潜龙腾渊（新版已内置 TFR 本体） | 3504418504 |
| [TFR]烈焰升腾中国建制派内容优化&修复 | 3430389589 |

文件夹里应该能看到 `common/`、`events/`、`localisation/` 等目录。

## 2. 先看看里面有什么

```bash
python hoi4_text_extract.py --list "D:/Steam/steamapps/workshop/content/394360/3504418504"
```

会列出所有国策树（以及它们属于哪个国家标签）、事件命名空间和决议分类，用来判断建制派对应的是哪棵树、哪些事件。

## 3. 导出

```bash
# 中国（按国家标签；具体是 CHI 还是 PRC 等，以 --list 列出的国家标签为准）
python hoi4_text_extract.py --tag CHI -o 中国文案.md  "<mod 文件夹>"

# 指定国策树 / 事件命名空间 / 决议分类（名字里包含即可，可重复）
python hoi4_text_extract.py --tree china --namespace china --category china -o 建制派.md "<mod 文件夹>"

# 只搜某句话在哪
python hoi4_text_extract.py --keyword 乘风好去 "<mod 文件夹>"

# 子 mod 叠在本体上（本体在前，子 mod 在后，后者覆盖前者）
python hoi4_text_extract.py --tag CHI -o out.md "<TFR 本体>" "<建制派优化 submod>"
```

常用参数：

| 参数 | 作用 |
| --- | --- |
| `--list` | 只列出国策树 / 事件命名空间 / 决议分类 |
| `--tag CHI` | 只要和该国家标签相关的内容 |
| `--tree` / `--namespace` / `--category` | 按国策树 id、事件命名空间、决议分类筛选（各管各的部分） |
| `--only focus` | 只导出某一类（`focus` `event` `decision` `idea`，可重复） |
| `--keyword 词` | 只保留文案或 id 里含这个词的条目（可重复，命中任意一个即可） |
| `--keep-codes` | 保留 `§Y` 颜色代码和 `£` 图标代码（默认去掉） |
| `--language english` | 导出其他语言（默认 `simp_chinese`） |
| `-o 文件.md` / `--json 文件.json` | 输出到文件 |

## 说明

- 文案中的 `[ROOT.GetName]`、`$变量$` 这类动态文本会原样保留，游戏里会被替换成实际内容。
- 同一事件有多个按条件切换的描述（`desc = { text = ... trigger = ... }`）时，会全部列出。
- 导出结果只供自己阅读欣赏，文案版权归各 mod 制作组所有，请勿二次发布。
