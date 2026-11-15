---
doc_id: deals-board-view
title: Using the pipeline board
modules: [deals]
version: 1
---

## Filter the board

Use filters to show only the deals you want to work on. Deals closed as won or lost leave the board, so you need a filter to find them.

1. Go to **Deals** to open the **Pipeline board**.
2. Select the pipeline you want from the pipeline list at the top of the board. Each pipeline has its own stages.
3. Select **Filter** and choose the criteria to apply, such as deal owner or deal value. The board updates and shows only the matching deals.
4. To see deals that were closed as won or lost, select the **Closed** filter. Clear the filter to return to open deals.

## Drag and drop deals

Move a deal to a different stage by dragging its card. The deal takes on the probability of its new stage, from 0 to 100%.

1. On the **Pipeline board**, point to the deal card you want to move, then press and hold.
2. Drag the card to the target stage column and release it. The card stays in the new column, and the stage totals update.
3. If the stage has automations, check that they ran. Automations run within 1 minute of the stage change, and only if they are set to **Active**. A stage with **Deal leaves this stage** or **Deal enters this stage** automations runs them when you move a deal out of or into that stage.

To see what ran, go to **Deals → Stage settings**, pick the pipeline and the stage, open the **Automations** tab, and select **Run history**. It shows the last 90 days of runs.

## Board settings

Board settings are managed in **Stage settings**. You can change how each pipeline and stage behaves on the board.

1. Go to **Deals → Stage settings**.
2. Pick a pipeline. An account can have up to 10 pipelines, and each pipeline can have up to 20 stages.
3. Pick a stage, then set its probability to a value from 0 to 100%. The board uses this value when it calculates stage totals.
4. To automate a stage, open its **Automations** tab and add an automation. A stage can have up to 10 automations, each with one trigger and up to 5 actions. New automations are saved as **Paused**, so switch each one to **Active** before you expect it to run.

If your account has other modules that add actions, they appear in the **Add action** list next to the built-in actions **Update a field**, **Change owner** and **Notify a user**.
