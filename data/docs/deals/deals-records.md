---
doc_id: deals-records
title: Working with deals
modules: [deals]
version: 1
---

## Create a deal

You create a deal in a pipeline. The deal starts in the stage you choose and appears as a card on the **Pipeline board**.

1. Go to **Deals**. The **Pipeline board** opens.
2. If your account has more than one pipeline, select the pipeline you want from the pipeline list at the top of the board.
3. Select **New deal**.
4. Enter a **Deal name** and a **Value**. Set the **Expected close date**, and change **Owner** if the deal belongs to someone else. By default, you are the owner.
5. In the **Stage** field, choose the stage where the deal starts, then select **Save**. The deal appears as a card in that stage's column.

Each stage has a probability from 0 to 100%. The deal uses the probability of its current stage. If an administrator needs to add or rename stages, they do it in **Deals → Stage settings**.

## Move a deal between stages

Move a deal whenever it progresses, or goes back, in your sales process.

1. Go to **Deals** and find the deal's card on the **Pipeline board**.
2. Drag the card to the column of the new stage and drop it. Alternatively, open the deal, select the **Stage** field, and choose the new stage.
3. Check that the card now appears in the new column.

If the old or new stage has active automations, they run within 1 minute of the move. Depending on how the stage is set up, an automation might update a field, change the deal owner or notify a user. If a field or owner changes after you move a deal, an automation is the likely cause. To see which automations are configured, open **Deals → Stage settings**, choose the pipeline and stage, and select the **Automations** tab. **Run history** on that tab lists the runs from the last 90 days.

## Close a deal as won or lost

Close a deal when the outcome is final. Closing removes the deal from the board, so you can't drag a closed deal between stages.

1. Go to **Deals** and open the deal from the **Pipeline board**.
2. Select **Close deal**.
3. Choose **Won** or **Lost**. If you choose **Lost**, select a **Lost reason** so your team can see why deals fall through.
4. Confirm the **Close date** and select **Save**. The deal leaves the **Pipeline board**.

To find a closed deal later, go to **Deals** and apply the **Closed** filter. The filter lists both won and lost deals. Open any deal in the list to review its details.
