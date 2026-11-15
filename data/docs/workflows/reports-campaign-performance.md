---
doc_id: reports-campaign-performance
title: Reporting on campaign performance
modules: [campaigns, reports]
version: 1
---

## Before you start

You need a sent campaign. The **Campaign performance** data source in **Report builder** only has data once at least one campaign has gone out. Your account must also include Campaigns, because **Report builder** offers this data source only to accounts that have it.

You need access to both Campaigns and Reports. A report only shows data from modules the person viewing it can use, so anyone you share it with must also be able to use Campaigns to see the campaign figures.

New reports and dashboards are private until you share them. Report data refreshes every 15 minutes, so figures for a campaign that just finished sending may take a short while to settle.

For general report-building options, see *Building a report*. For dashboard layout and sharing, see *Creating dashboards*.

## Build a campaign report

1. Go to **Reports → Report builder**.
2. Create a new report and select **Campaign performance** as the data source.
3. Choose the metrics you want to show: sent, delivered, opened, clicked, unsubscribed and bounced. Start with sent, delivered, opened and clicked if you want a quick view of engagement.
4. Filter the report to the campaign or campaigns you want to measure. For example, select only your most recent send to see its results on their own.
5. Choose how to display the results. Use a table for a side-by-side comparison of several campaigns, a bar chart to compare metrics, or a number for a single headline figure such as clicked.
6. Name the report, for example "Spring promotion results", and save it. The report is private until you share it. To share it, select users or teams and set each to **Can view** or **Can edit**.

## Add it to a dashboard

1. Go to **Reports → Dashboards** and open the dashboard you want to add the report to, or create a new one.
2. Add a widget and choose the saved report as its source. Select a widget type: number, bar chart, line chart, table or funnel. A funnel suits the path from sent through delivered, opened and clicked.
3. Place the widget on the dashboard and save. A dashboard holds up to 24 widgets, so remove one you no longer need if the dashboard is full. Share the dashboard with the people who need it, as **Can view** or **Can edit**.

## Metrics explained

| Metric | What it tells you |
| --- | --- |
| Sent | The number of emails the campaign sent. |
| Delivered | The number of sent emails that reached a recipient's mailbox. |
| Opened | The number of delivered emails that were opened. |
| Clicked | The number of delivered emails in which a recipient selected a link. |
| Unsubscribed | The number of recipients who used the unsubscribe link that every email includes. Unsubscribed contacts never receive campaign or triggered emails. |
| Bounced | The number of emails that could not be delivered. A hard bounce marks the contact **Bounced** and excludes them from future sends. |
