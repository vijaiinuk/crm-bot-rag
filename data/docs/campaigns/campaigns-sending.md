---
doc_id: campaigns-sending
title: Sending a campaign
modules: [campaigns]
version: 1
---

## Schedule a send

1. Go to **Campaigns** and select the **Campaigns** tab.
2. Open the campaign you want to send. If you haven't created one yet, select the option to create a new campaign and give it a name.
3. Choose the **Audiences** you want to send to. An audience is built from contact filters, updates automatically, and holds up to 100,000 contacts, so the recipient list reflects your filters at the time of sending.
4. Choose an email template. Every email uses a template, and you can personalize the content with merge fields in double braces, for example `{{contact.first_name}}`.
5. Select the date and time for the send, then confirm the schedule. The campaign sends at the time you chose.

Before you confirm, check that the template includes the content you want. You don't need to add an unsubscribe link yourself, because the system adds one to every email automatically.

## Unsubscribes

Every email you send from Campaigns includes an unsubscribe link. The link is added automatically, so you don't need to insert it in your template. When a contact selects the link, they are unsubscribed.

Unsubscribed contacts never receive campaign or triggered emails. This applies even if the contact matches the filters of an audience you send to. The contact stays in the audience, but the system skips them when it sends. You don't need to remove unsubscribed contacts from your audiences by hand.

Because unsubscribes apply to both campaign and triggered emails, a contact who unsubscribes from one kind of email stops receiving the other kind too.

## Bounce handling

A bounce happens when an email can't be delivered to a contact's address. When a hard bounce occurs, which means the address is permanently undeliverable, the system marks the contact **Bounced** and excludes them from future sends. This applies to both campaigns and triggered emails, so you don't need to take any action to stop further sends to that address.

To review the contacts affected, open the audience you sent to and check for contacts with the **Bounced** status. If a contact's email address was entered incorrectly, correct it on the contact record before you plan your next send. Removing bad addresses regularly helps keep your audiences accurate.
