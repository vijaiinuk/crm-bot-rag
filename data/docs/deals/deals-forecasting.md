---
doc_id: deals-forecasting
title: Forecasting deals
modules: [deals, reports]
version: 1
---

## Forecast categories

Every deal has a **Forecast category** field that records how likely you think the deal is to close in the current period. The category is separate from the deal's stage. The stage probability (0 to 100%) is set per stage, while the forecast category is your own judgment about the individual deal.

The categories are:

- **Pipeline**: early deals you can't yet commit to. New deals start here.
- **Best case**: deals that could close if things go well.
- **Commit**: deals you expect to close.
- **Omitted**: deals you want to leave out of the forecast.

You can change the category on the deal record or from the **Pipeline board**. To set it automatically, go to **Deals → Stage settings**, pick a pipeline and a stage, and add an **Update a field** action on the **Automations** tab. Remember that a new automation is saved as **Paused** until you switch it to **Active**.

Deals closed as won or lost leave the board. Select the **Closed** filter to find them.

## Forecast reports

The forecast report totals deal amounts by forecast category. You can group the totals by owner, pipeline or close month.

1. Go to **Reports → Report builder**.
2. Select **Deals** as the data source, then choose **Forecast category** as the grouping.
3. Add the fields you want to total, such as deal amount, and set a close date range for the forecast period.
4. Select **Save**, then give the report a name. The report is private until you share it.
5. Select **Share** and choose users or teams, with **Can view** or **Can edit**.

Report data refreshes every 15 minutes, so a category change can take a short time to show up. People only see data from modules they can use. To keep the report in front of your team, add it to a dashboard in **Reports → Dashboards**, or set up a delivery in **Reports → Scheduled exports**.
