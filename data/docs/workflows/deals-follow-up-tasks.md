---
doc_id: deals-follow-up-tasks
title: Creating follow-up tasks when a deal changes stage
modules: [deals, activities]
version: 1
---

## Before you start

You need at least one pipeline with stages. If you haven't created one yet, set it up in **Deals → Stage settings** first. Your account must also include Activities, because the **Create task** action only appears in the **Add action** list when it does.

A stage automation has one trigger and up to 5 actions, and a stage can have up to 10 automations. This guide uses the **Create task** action so that a task is created each time a deal enters or leaves a stage. For other actions, such as **Update a field** or **Notify a user**, see *Automating deal stage changes*. For tasks that repeat on a schedule, see *Recurring and automatic tasks*.

## Add a task action to a stage

1. Go to **Deals → Stage settings**.
2. Select the pipeline, then select the stage that should create the task.
3. Open the **Automations** tab and add a new automation.
4. For the trigger, choose **Deal enters this stage** to create the task when a deal arrives, or **Deal leaves this stage** to create it when a deal moves on.
5. Select **Add action**, then choose **Create task**.
6. Enter the task details, such as a title and description, and save the automation. New automations are saved as **Paused**, so switch the automation to **Active** for it to run.

After you activate the automation, it runs within 1 minute of each stage change. To check that it worked, open **Run history** on the **Automations** tab. It shows the last 90 days of runs.

## Assign the task

1. In the **Create task** action, find the assignee setting. By default, the task is assigned to the deal owner. Leave it as it is if the person who owns the deal should do the follow-up. A task has one assignee.
2. To send the task to someone else, choose a different user as the assignee.
3. Set the due date as a number of days after the stage change, then save the automation. For example, enter 3 to make the task due three days after the deal moves.

If you want a reminder, you can set one when you work with the task itself. A reminder can be set from 5 minutes to 7 days before the due date.

Assignees find the new task in **Activities → My tasks**. Tasks that pass their due date show in red there.
