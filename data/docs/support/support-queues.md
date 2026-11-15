---
doc_id: support-queues
title: Ticket queues
modules: [support]
version: 1
---

## Create a queue

Every ticket is in exactly one queue, so create a queue for each team or type of work that needs its own list of tickets, such as Billing or Technical support.

1. Go to **Support → Queues**.
2. Select **New queue**.
3. In the **Name** field, enter a name that your agents will recognize. In **Description**, add a short note about which tickets belong in the queue.
4. Select **Save**. The queue appears in the list on the **Queues** page and is ready for assignment rules.

## Assignment rules

An assignment rule decides which agent receives each new ticket that arrives in the queue. Choose one rule per queue.

1. Go to **Support → Queues** and select the queue you want to change.
2. Open the **Assignment** tab.
3. In the **Members** field, add the agents who should receive tickets from this queue. Only the agents you add are considered by the rule.
4. In the **Assignment rule** field, choose one of the following:
   - **Round robin**: tickets go to the members in turn, so each member receives the same number over time.
   - **Least busy**: each ticket goes to the member who currently has the fewest tickets assigned to them.
5. Select **Save**. The rule applies to tickets that enter the queue from now on. Tickets already assigned stay with their current agents.

If you need to move a ticket to a different queue, open it from **Support → Tickets** and change its queue. The ticket then follows the assignment rule of the new queue. An escalation rule can also move a ticket to another queue automatically. For details, see **Escalations** in the Support menu.
