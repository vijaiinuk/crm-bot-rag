---
doc_id: campaigns-email-templates
title: Designing email templates
modules: [campaigns]
version: 1
---

## Create a template

1. Go to **Campaigns → Templates**.
2. Select **New template**, then enter a name in the **Template name** field. Choose a name your team will recognize, such as "Spring promotion" or "Welcome message".
3. Enter the text for the email in the **Subject** field, then write your message in the editor. Add formatting, images and links as you would in any email.
4. To personalize the message, place your cursor where you want the value to appear and type a merge field in double braces, for example `{{contact.first_name}}`. See the merge field table below for the fields you can use.
5. Select **Save**. The template is now available to any email you create in Campaigns.

Every email uses a template, so create your templates before you build a campaign or a triggered email. You don't need to add an unsubscribe link yourself. Every email gets one automatically, and unsubscribed contacts never receive campaign or triggered emails.

## Merge fields

A merge field is replaced with the matching value from each contact's record when the email is sent. Type the field exactly as shown, including the double braces.

| Merge field | What it inserts | Example |
|---|---|---|
| `{{contact.first_name}}` | The contact's first name | Dana |
| `{{contact.last_name}}` | The contact's last name | Okafor |
| `{{contact.email}}` | The contact's email address | dana@example.com |
| `{{contact.company}}` | The name of the contact's company | Brightwater Ltd |

If a contact has no value stored for a field, that part of the message is left blank. Check the contact records in your audience before you send, and write the surrounding text so it still reads well without the value, for example "Hello," instead of "Hello {{contact.first_name}},".

## Send a test email

1. Go to **Campaigns → Templates** and open the template you want to check.
2. Select **Send test**, enter your own email address in the **Recipient** field, and select **Send**.
3. Open the message in your inbox. Check that the subject, layout and links look right, and that each merge field shows a real value instead of the braces. If something is wrong, return to the template, make the change, select **Save**, and send another test.

A test email is a way to preview your template. It doesn't send to any audience and doesn't activate any triggered email. Triggered emails are saved as **Draft** and send only after you select **Activate** to set them to **Active**.
