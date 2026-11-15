---
doc_id: deals-stage-automation
title: Automating deal stage changes
modules: [deals]
version: 1
---

## Triggers

A trigger decides when a stage automation starts. Each automation has one trigger, and each stage can have up to 10 automations.

1. Go to **Deals → Stage settings**.
2. Select the pipeline, then select the stage the automation belongs to.
3. Open the **Automations** tab and select **New automation**.
4. Under the trigger setting, choose **Deal enters this stage** to run when a deal moves into the stage, or **Deal leaves this stage** to run when a deal moves out of it.
5. Add at least one action (see *Actions* below), then select **Save**. The automation is saved as **Paused** and does nothing until you switch it to **Active**.

To react to both events, create two automations on the same stage, one for each trigger.

## Actions

Actions are what the automation does to the deal once the trigger fires. One automation can have up to 5 actions.

1. In the automation you are editing, select **Add action**.
2. Choose one of the built-in actions:
   - **Update a field** sets a deal field to a value you specify, for example setting a **Next step** field to "Send proposal".
   - **Change owner** reassigns the deal to the user you pick.
   - **Notify a user** sends a notification to the user you pick, with a message you write.
3. Fill in the settings for the action you chose, such as the field and its new value, the new owner, or the user and message to notify.
4. To add more actions, select **Add action** again, up to 5 in total. Then select **Save**.

If your account includes other modules, they may add more choices to the **Add action** list. For examples, see *Creating follow-up tasks when a deal changes stage* and *Emailing contacts when a deal changes stage*.

## Testing an automation

Test every new automation before you rely on it. Use a deal that doesn't belong to a real customer so that owner changes and notifications don't reach anyone by surprise.

1. Go to **Deals → Stage settings**, select the pipeline and stage, open the **Automations** tab, and switch the automation from **Paused** to **Active**.
2. Go to **Deals** to open the **Pipeline board**. Drag your test deal into the stage if the trigger is **Deal enters this stage**, or out of the stage if the trigger is **Deal leaves this stage**.
3. Wait up to 1 minute. Automations run within 1 minute of the stage change.
4. Return to the **Automations** tab and open **Run history**. Check that the run appears and that the deal shows the expected field value or owner. Run history keeps the last 90 days of runs.

If the run doesn't appear or the result is wrong, check that the automation is **Active** and that you chose the right trigger. Then edit the automation and test again. If you want to stop an automation while you make changes, switch it back to **Paused**.

If you closed your test deal as won or lost while testing, it no longer appears on the **Pipeline board**. Use the **Closed** filter to find it.
