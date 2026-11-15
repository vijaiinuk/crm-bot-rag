---
doc_id: deals-pipeline-setup
title: Setting up a pipeline
modules: [deals]
version: 1
---

## Create a pipeline

1. Go to **Deals → Stage settings**.
2. Open the pipeline list at the top of the screen and select **New pipeline**. Your account can have up to 10 pipelines, so the option is unavailable once you reach that limit.
3. Enter a name for the pipeline, for example "Enterprise renewals", and select **Create**.
4. Add your first stages. Each pipeline can have up to 20 stages. Select **Add stage**, enter a stage name, and repeat for each step of your sales process.
5. Set a probability for each stage (see *Stage probabilities* below), then go to **Deals** to check the result on the **Pipeline board**. Each stage appears as a column.

## Edit stages

1. Go to **Deals → Stage settings**.
2. Select the pipeline you want to change from the pipeline list. The stages for that pipeline appear in order, from first to last.
3. To rename a stage, select it, edit the **Stage name** field, and select **Save**.
4. To reorder stages, drag a stage by its handle and drop it in the new position. The order here is the order of the columns on the **Pipeline board**, from left to right.
5. To add a stage, select **Add stage**. You can add stages until the pipeline has 20. To work with automations for a stage, select the stage and open its **Automations** tab.

If you also use other modules that add actions to stages, those actions appear in the **Add action** list on the **Automations** tab when your account has them.

## Stage probabilities

Every stage has a probability from 0 to 100%. The probability is your estimate of how likely a deal in that stage is to be won. A deal in a stage with a probability of 60% is counted as 60% likely to close as won.

To change a probability, go to **Deals → Stage settings**, pick the pipeline, select the stage, and enter a new value in the probability field. Values must be whole numbers between 0 and 100. Changes apply to deals already in the stage as well as deals that enter it later.

A few guidelines help keep probabilities useful:

- Set early stages low and increase the value as deals move toward the end of the pipeline. A first-contact stage might be 10%, a proposal stage 50%, and a negotiation stage 80%.
- Base your numbers on how often deals in each stage have been won in the past, not on how you hope they will go.
- Review the values from time to time, especially after you add, remove or reorder stages, so they still match your process.

When you close a deal as won or lost, it leaves the **Pipeline board**. To see closed deals, use the **Closed** filter on the board.
