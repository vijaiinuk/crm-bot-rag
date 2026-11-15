---
doc_id: reports-scheduled-exports
title: Scheduling exports
modules: [reports]
version: 1
---

## Schedule an export

You can schedule a recurring export of any saved report you can open. The export is emailed to the recipients you choose, so no one has to run the report by hand.

1. Go to **Reports → Scheduled exports**.
2. Select **New scheduled export**, then choose the saved report you want to export from the **Report** list.
3. Under **Frequency**, choose **Daily**, **Weekly** or **Monthly**. For weekly exports, pick the day of the week. For monthly exports, pick the day of the month.
4. Under **Format**, choose **CSV** or **XLSX**. Then, in **Recipients**, enter up to 10 email addresses.
5. Select **Save**. The export appears in the **Scheduled exports** list with its next run date.

Keep these points in mind:

- An account can have up to 100 scheduled exports. If you reach the limit, stop or remove an export you no longer need before you create a new one.
- Report data refreshes every 15 minutes, so each export contains the data as of its most recent refresh.
- A report only shows data from modules the person viewing it can use. If your report draws on a module you can't use, that data doesn't appear in the report or in your exports.

## Export formats

Choose the format in the **Format** field when you create or edit a scheduled export.

| Format | File type | Best for |
|---|---|---|
| **CSV** | `.csv` | Importing the data into another tool, or opening it in any text editor or spreadsheet program. |
| **XLSX** | `.xlsx` | Opening the data directly in a spreadsheet program, where you can sort, filter and build your own charts. |

Both formats are available for daily, weekly and monthly exports. To change the format of an existing export, open it from the **Scheduled exports** list, change **Format** and select **Save**. The new format applies from the next run.

## Stop a scheduled export

Stop an export when no one needs the emails any more, or when you need to free up a place under the 100-export limit.

1. Go to **Reports → Scheduled exports**.
2. Find the export in the list and open its row menu.
3. Select **Delete**, then confirm. The export no longer runs and no further emails are sent.

Deleting a scheduled export doesn't delete the saved report it was based on. You can open the report from **Reports** and schedule a new export for it at any time.
