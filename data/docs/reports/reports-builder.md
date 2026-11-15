---
doc_id: reports-builder
title: Building a report
modules: [reports]
version: 1
---

## Choose a data source

The data source decides which records and fields are available in the report. Pick it before you add filters or grouping.

1. Go to **Reports → Report builder** and select **New report**.
2. In the **Data source** field, select the type of record you want to report on, such as deals, contacts or tickets. The list shows only the modules you can use.
3. Select **Continue**. The builder opens with a preview and a list of fields for that source.

Anyone you share the report with sees only data from modules they can use. If a viewer has no access to the source module, the report shows no data for them.

## Filters and grouping

Filters narrow the records in the report. Grouping organizes the results into rows or chart segments.

1. In the **Filters** panel, select **Add filter**, choose a field, such as **Created date** or **Owner**, and set a condition and value. Repeat for each filter. Records must match all filters to appear.
2. For date fields, select a range from the **Date range** list, such as **Last 30 days** or **This quarter**, or select **Custom** to enter exact start and end dates.
3. In the **Group by** field, select the field you want to group results by. To add a second level, select **Add grouping** and choose another field. Groups appear in the order you add them.
4. In the **Values** panel, select what to calculate for each group, such as **Count** or **Sum**, and the field to calculate on.
5. Select **Run preview** to check the results. Adjust the filters, grouping or values until the preview shows what you need.

Report data refreshes every 15 minutes, so a record you changed a moment ago may not appear in the preview right away.

## Save a report

A new report is private until you share it, so only you can see it at first.

1. Select **Save**, enter a name in the **Report name** field, and select **Save report**. The report now appears under **Reports**.
2. To share it, select **Share**, then search for the users or teams you want to add.
3. Set each person or team to **Can view** or **Can edit**, then select **Done**. People with **Can view** can open and run the report. People with **Can edit** can also change its source, filters and grouping.

After you save the report, you can add it to a dashboard under **Reports → Dashboards**, or set up a recurring export under **Reports → Scheduled exports**.
