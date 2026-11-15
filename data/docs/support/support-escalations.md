---
doc_id: support-escalations
title: Escalation rules
modules: [support]
version: 1
---

## Create an escalation rule

Escalation rules act on tickets that stay unresolved too long. Each rule can have up to 3 levels, and each level either notifies a team lead or moves the ticket to another queue. If you want to escalate to the account owner instead, see *Escalating a ticket to the account owner*.

1. Go to **Support → Escalations**.
2. Select **New escalation rule**.
3. In **Rule name**, enter a name that describes the rule, for example "Urgent tickets, no response". In **Queue**, choose the queue the rule watches.
4. In **Applies to**, choose the ticket **Priority** values (**Urgent**, **High**, **Normal**, **Low**) that trigger the rule.
5. Under **Level 1**, set **Wait time**, then choose an **Action**: **Notify team lead** or **Move to queue**. If you choose **Move to queue**, select the destination queue.
6. Select **Add level** to configure Level 2 and Level 3 if you need them. Then turn on **Active** and select **Save**.

A ticket is always in exactly one queue, so when a level moves a ticket, it leaves its current queue and follows the assignment rule of the destination queue (**Round robin** or **Least busy**).

## Escalation levels

Each level runs only after the previous level's wait time has passed and the ticket is still unresolved. The values below are examples. You can set your own.

| Level | Example wait time | Available actions | Typical use |
|---|---|---|---|
| **Level 1** | 30 minutes | **Notify team lead** or **Move to queue** | Alert the team lead that the ticket needs attention. |
| **Level 2** | 2 hours | **Notify team lead** or **Move to queue** | Move the ticket to a more experienced queue. |
| **Level 3** | 4 hours | **Notify team lead** or **Move to queue** | Make a final move or notification before the ticket breaches its target. |

Levels stop when the ticket status changes to **Resolved** or **Closed**. You can have up to 3 levels per rule. You can't add a fourth.
