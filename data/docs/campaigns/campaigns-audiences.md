---
doc_id: campaigns-audiences
title: Building audiences
modules: [campaigns]
version: 1
---

## Build an audience

An audience is a group of contacts that matches the filters you set. It updates automatically, so contacts who start or stop matching your filters join or leave the audience without any action from you.

1. Go to **Campaigns → Audiences**.
2. Select **New audience**, then enter a name in the **Audience name** field. Use a name that describes the group, such as "Trial users in Germany".
3. Under **Include contacts where**, select **Add filter**. Choose a contact field, an operator (for example **is**, **is not**, **contains** or **is empty**), and a value.
4. Add more filters as needed. Filters in the same group must all match for a contact to be included. To include contacts that match any one of several conditions, select **Add group** and build the alternative conditions there.
5. Check the contact count shown in the **Preview** panel, then select **Save**. The audience now appears on the **Audiences** tab, where you can select it when you set up a campaign.

## Exclusions

Use exclusions to keep specific contacts out of an audience even when they match your include filters. Exclusions take priority over include filters.

1. Open the audience from **Campaigns → Audiences**, then select **Edit**.
2. Under **Exclude contacts where**, select **Add filter**. Choose the field, operator and value that describe the contacts you want to leave out, for example a **Customer status** of **Active customer**.
3. Check that the **Preview** count has dropped as you expect, then select **Save**.

You don't need to exclude unsubscribed or bounced contacts yourself. Unsubscribed contacts never receive campaign emails, and a hard bounce marks the contact **Bounced** and excludes them from future sends. These contacts can still match your filters and appear in the **Preview** count, but they are skipped when an email goes out.

## Audience size limits

An audience holds up to 100,000 contacts. If your filters match more than that, the audience is limited to 100,000 contacts, so narrow your filters to make sure the contacts you care about are included. Try adding a filter on country, signup date or last activity, or split a large group into several audiences with different filters.

Because audiences update automatically, the number of matching contacts can change between the time you save an audience and the time you send to it. Check the contact count on the **Audiences** tab before you send. If an audience that was near the limit grows past 100,000, tighten its filters.
