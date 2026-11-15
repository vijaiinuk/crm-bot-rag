---
doc_id: campaigns-deal-triggers
title: Emailing contacts when a deal changes stage
modules: [campaigns, deals]
version: 1
---

## Before you start

When a deal enters a stage, a stage automation can send a triggered campaign email to the deal's contacts. You set this up in two places: **Campaigns** for the email, and **Deals → Stage settings** for the automation.

Make sure you have the following:

- A pipeline with the stage you want to use. An account can have up to 10 pipelines, each with up to 20 stages.
- An email template. Every email uses a template, and you can personalize it with merge fields in double braces, such as `{{contact.first_name}}`.
- A triggered email that uses that template. If you don't have one yet, see *Setting up triggered emails*.
- Contacts linked to the deal. The email goes only to contacts linked to the deal.

Keep these sending rules in mind:

- A triggered email sends a given contact at most one email per 24 hours.
- An account can send up to 10,000 triggered emails a day.
- Every email includes an unsubscribe link automatically.
- Unsubscribed contacts never receive the email.
- Contacts marked **Bounced** after a hard bounce are excluded from future sends.

For more on stage automations in general, see *Automating deal stage changes*.

## Connect a stage to a campaign

1. Go to **Campaigns** and open the **Triggered emails** tab. Find the triggered email you want to send. New triggered emails are saved as **Draft**, and only active ones send. If the status is **Draft**, open the email and select **Activate** so its status changes to **Active**.
2. Go to **Deals → Stage settings**.
3. Pick the pipeline, then pick the stage that should trigger the email.
4. Open the stage's **Automations** tab and create a new automation. For the trigger, choose **Deal enters this stage**.
5. Select **Add action**, then choose **Send triggered email** and select your triggered email from the list. If **Send triggered email** isn't in the list, your account doesn't have Campaigns.
6. Save the automation. New automations are saved as **Paused**, so switch it to **Active**. A stage can have up to 10 automations, and each automation can have up to 5 actions.

## Choose recipients

1. In **Deals → Stage settings**, pick the pipeline and stage, then open the **Automations** tab.
2. Open the automation that contains the **Send triggered email** action.
3. In the action's settings, choose who receives the email: all of the deal's linked contacts, or the primary contact only.
4. Save the automation and confirm its status is still **Active**.

Whichever option you choose, unsubscribed contacts and contacts marked **Bounced** are skipped.

## Check it works

1. Go to **Deals** to open the **Pipeline board**. Move a test deal into the stage. Use a deal whose linked contact is an address you can read, such as your own.
2. Wait up to 1 minute. Automations run within 1 minute of the stage change. Then go to **Deals → Stage settings**, pick the pipeline and stage, and open **Run history** on the **Automations** tab. **Run history** shows runs from the last 90 days, so you can confirm that the automation ran for your test deal.
3. Check the contact's inbox. If the email didn't arrive, check the following:
   - The automation is **Active**, not **Paused**.
   - The triggered email is **Active**, not **Draft**.
   - The contact hasn't already received this triggered email in the past 24 hours.
   - The contact hasn't unsubscribed and isn't marked **Bounced**.
   - The deal has a linked contact that matches your recipient choice.
