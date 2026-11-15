---
doc_id: support-tickets
title: Working with tickets
modules: [support]
version: 1
---

## Create a ticket

1. Go to **Support → Tickets** and select **New ticket**.
2. Enter the customer's name or email address in the requester field, then add a subject and a description of the problem.
3. Choose a **Priority**: **Urgent**, **High**, **Normal** or **Low**. Choose the queue for the ticket. Every ticket is in exactly one queue, so you can't leave this field empty. If you don't pick an assignee, the queue's assignment rule (**Round robin** or **Least busy**) picks one for you.
4. Select **Create**. The ticket opens with the status **New**.

The first matching SLA policy, by order, applies to the ticket when you create it, using the priority you chose. SLA policies apply to new tickets only, so changing policies later doesn't affect tickets that already exist. Response and resolution targets are counted within business hours, which by default are Monday to Friday, 09:00 to 17:30, in your account's time zone.

## Ticket statuses

Every ticket has one status at a time. You can change the status from the ticket's detail page.

| Status | Meaning | What to do next |
|---|---|---|
| **New** | The ticket was just created and nobody has worked on it yet. | Review the ticket and send a first response. |
| **Open** | An agent is working on the ticket. | Continue the work and reply to the customer. |
| **Waiting on customer** | You asked the customer for information and are waiting for a reply. | Follow up if the customer doesn't respond. |
| **Resolved** | You have fixed the problem or answered the question. | Reopen the ticket if the customer replies. Otherwise it closes automatically after 7 days. |
| **Closed** | The ticket is finished. | No further action is needed. |

If a ticket breaches an SLA target, an escalation rule can notify a team lead or move the ticket to another queue. Escalation rules have up to 3 levels. An administrator sets them up under **Support → Escalations**.

## Close a ticket

1. Go to **Support → Tickets** and open the ticket you want to close.
2. Add a final reply or internal note that describes the solution, then set the status to **Resolved**.
3. Wait 7 days, and the ticket moves to **Closed** automatically. To close it sooner, set the status to **Closed** yourself.
