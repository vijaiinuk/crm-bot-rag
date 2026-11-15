---
doc_id: support-sla-policies
title: SLA policies
modules: [support]
version: 1
---

## Set up an SLA policy

An SLA policy sets first response and resolution targets for each ticket priority. A policy applies to new tickets only, so existing tickets keep the targets they had when they were created. Before you start, create the queues and escalation rules you want to use.

1. Go to **Support → SLA policies**.
2. Select **New SLA policy**.
3. In **Policy name**, enter a name, for example `Premium customers`.
4. In **Applies to**, select one or more queues. Every ticket is in exactly one queue, so the queue is the simplest way to decide which tickets a policy covers.
5. In the **Urgent** row, enter a **First response** target in hours and minutes, for example `0h 30m`.
6. In the same row, enter a **Resolution** target, for example `4h 00m`.
7. Repeat steps 5 and 6 for the **High**, **Normal** and **Low** rows.
8. In **Business hours**, choose **Default** or **Custom**. See *Business hours* below for the details.
9. In **On breach**, select the escalation rule to run when a target is missed. Leave it empty if you don't want an escalation.
10. Select **Save**. The policy appears at the bottom of the **SLA policies** list.
11. Drag the policy to its place in the list. When a new ticket matches more than one policy, the first matching policy by order wins, so put your most specific policies at the top.
12. Create a test ticket in one of the selected queues and open it. Check that the **SLA** panel shows the targets you entered for its priority.

## Business hours

SLA targets count only the time inside business hours. By default, business hours are Monday to Friday, 09:00 to 17:30, in your account's time zone. A ticket created at 17:00 on Friday therefore uses only 30 minutes of its target before the clock stops until Monday at 09:00.

To use different hours for a policy:

1. Go to **Support → SLA policies** and open the policy.
2. In **Business hours**, choose **Custom**.
3. Select the days that count, and enter a start time and an end time for each one. Clear a day to exclude it entirely.
4. Select **Save**.

Custom hours also use the account's time zone. The new hours apply to the policy's new tickets only.

## SLA breaches

A breach happens when a ticket reaches its first response target or resolution target without the work being done. The ticket is marked as breached on its **SLA** panel and in the **Tickets** list, so you can filter for it and work through the backlog.

If you selected an escalation rule in **On breach**, it runs at the moment of the breach. Escalation rules have up to 3 levels. Each level can do one of two things: notify a team lead, or move the ticket to another queue. For example, level 1 can notify the team lead, level 2 can notify again after a further wait, and level 3 can move the ticket to a senior queue. To create or edit rules, go to **Support → Escalations**.

Moving a ticket to another queue does not change the policy that was applied when the ticket was created. The ticket keeps its original targets, even if the new queue is covered by a different policy.

Changing a ticket's status to **Resolved** stops the resolution timer. If the ticket is still **Resolved** after 7 days, it closes automatically and its status changes to **Closed**.
