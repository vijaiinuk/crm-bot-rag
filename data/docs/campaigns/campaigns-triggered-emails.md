---
doc_id: campaigns-triggered-emails
title: Setting up triggered emails
modules: [campaigns]
version: 1
---

## Setup

Triggered emails send automatically when a contact meets a condition you choose. You build them in Campaigns. If you also use Deals, see *Emailing contacts when a deal changes stage* for deal-stage triggers.

Before you start, make sure the contacts you want to email are in an audience. An audience is built from contact filters, updates automatically, and holds up to 100,000 contacts. You manage audiences on the **Audiences** tab.

1. Go to **Campaigns → Triggered emails**.
2. Select **New triggered email** and enter a name in the **Name** field.
3. In the **Audience** field, choose the audience to send to. In the **Trigger** field, choose the event that sends the email, for example **Contact joins audience**.
4. In the **Template** field, choose the email template to send. To prepare a template first, see the next section.
5. Select **Save**. The triggered email is saved as **Draft**, and drafts never send.
6. Select **Activate**. The status changes to **Active**, and the triggered email starts sending when contacts meet the trigger.

## Templates

Every email uses a template, including triggered emails. You can reuse one template across several triggered emails.

1. Go to **Campaigns → Templates**.
2. Select an existing template to edit it, or select **New template** to create one.
3. Write the subject and body. To personalize the email, insert merge fields in double braces, for example `{{contact.first_name}}`. When the email sends, each merge field is replaced with that contact's own value.
4. Select **Save**. Then go back to **Campaigns → Triggered emails**, open your triggered email, and choose the template in the **Template** field.

You don't need to add an unsubscribe link. Every email gets one automatically.

## Send limits

Send limits apply to every triggered email in your account.

A triggered email sends a given contact at most one email per 24 hours. If a contact meets the trigger again within that period, they don't receive a second email.

Your account can send up to 10,000 triggered emails a day. Plan your audiences and triggers with this total in mind, especially if several triggered emails are active at once.

Some contacts are never emailed, whatever the trigger or the limits:

- Contacts who unsubscribe never receive campaign or triggered emails.
- Contacts whose email hard bounces are marked **Bounced** and excluded from future sends.

Only triggered emails with the status **Active** send. If emails aren't going out, check the **Triggered emails** tab and confirm the status isn't **Draft**.
