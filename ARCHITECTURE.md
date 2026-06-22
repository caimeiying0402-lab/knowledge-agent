# Personal AI OS 架构设计

## 第一层：数据采集层（Collection Layer）

负责收集所有原始信息。

数据来源：

* 微信截图
* 网页链接
* 飞书文档
* 简历
* 岗位JD
* 面试记录
* 收藏内容

输出：

Raw Data

---

## 第二层：数据处理层（Processing Layer）

负责把原始信息变成结构化信息。

Skills：

### OCR Skill

输入：

截图

输出：

文本

---

### Parser Skill

输入：

网页、文档

输出：

正文内容

---

### Summary Skill

输入：

原始文本

输出：

标题
摘要
标签
分类

---

输出：

Structured Data

---

## 第三层：知识层（Knowledge Layer）

负责长期存储。

存储：

SQLite

内容：

标题
摘要
标签
分类
来源

---

向量库：

Chroma

内容：

Embedding

作用：

RAG检索

---

## 第四层：Agent Layer

### Knowledge Agent

负责知识整理

调用：

OCR Skill
Summary Skill

---

### Career Agent

负责岗位匹配

调用：

Resume Skill
Job Search Skill
Matching Skill

---

### Discovery Agent

负责规则挖掘

调用：

Rule Mining Skill
Recommendation Skill

---

## 第五层：Learning Layer

负责自学习

记录：

点击
收藏
忽略

形成：

Preference Dataset

---

## 第六层：Recommendation Layer

负责猜你喜欢

根据：

兴趣标签
历史行为
知识库内容

推荐：

文章
岗位
工具
项目

---

最终形成：

Personal AI OS