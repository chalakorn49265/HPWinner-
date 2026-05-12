# HPWinner dashboard — quick start

## English

1. **Questionnaire** — Use the intake template in this repo (`HPWinner_Intake_Questionnaire_v2.xlsx` at the project root), or the current template from your HPWinner team. Fill it out and save the workbook.

2. **Where to put it** — Copy your completed file into the `data/` folder. The filename must include **`filled`** (for example `my_site_2026_filled.xlsx`) so it appears in the app dropdown.

3. **Run the dashboard** — In a terminal:

```bash
cd /Users/chalakorn/Documents/GitHub/HPWinner-
python3 -m pip install -r requirements.txt
python3 -m streamlit run Python_Pipeline/app.py
```

Then open the URL Streamlit prints in your browser.

---

## 中文

1. **问卷** — 使用本仓库根目录的录入模板（`HPWinner_Intake_Questionnaire_v2.xlsx`），或使用 HPWinner 团队提供的最新版模板。填写完成后保存 Excel 工作簿。

2. **存放位置** — 将填好的文件复制到 **`data/`** 目录下。文件名须包含 **`filled`**（例如 `my_site_2026_filled.xlsx`），这样才会出现在应用的下拉列表中。

3. **启动看板** — 在终端执行：

```bash
cd /Users/chalakorn/Documents/GitHub/HPWinner-
python3 -m pip install -r requirements.txt
python3 -m streamlit run Python_Pipeline/app.py
```

然后在浏览器中打开 Streamlit 输出的本地访问地址。
