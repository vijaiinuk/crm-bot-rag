---
doc_id: support-escalate-to-owner
title: Escalating a ticket to the account owner
modules: [support, contacts]
version: 1
---

## Before you start

Escalating to the account owner sends the ticket to the person who owns the customer's company in your CRM. Before you begin, check that:

- The ticket is linked to a contact.
- The contact is linked to a company.
- The company has an owner. The account owner is the owner of the company linked to the ticket's contact.

The account owner can be a different person from the owner of the contact. Every contact has exactly one owner, and a new contact is owned by the user who created it unless an import set the owner. For escalation, only the company's owner counts.

If the company has no owner, ask an administrator to set one first. For more about ownership, see *Assigning contact owners*. To have tickets escalate automatically instead, see *Escalation rules*.

## Find the account owner

1. Go to **Support → Tickets** and open the ticket you want to escalate.
2. In the ticket details, select the contact's name to open the contact record.
3. In the contact record, select the linked company, or go to **Contacts → Companies** and search for it. The owner shown on the company is the account owner. Note the name.

If the contact has no linked company, the ticket has no account owner and you can't escalate it this way.

## Escalate the ticket

1. Go to **Support → Tickets** and open the ticket.
2. Check the ticket's status (**New**, **Open**, **Waiting on customer**, **Resolved** or **Closed**) and its priority. Resolved tickets close automatically after 7 days, so escalate a resolved ticket before then if the customer still needs help.
3. Add an internal note that summarizes the problem, what you have already tried, and what you need from the owner. The owner sees this note when they open the ticket.
4. Select the **Escalate to account owner** action on the ticket.
5. Confirm the escalation. Check that the account owner's name matches the one you found on the company.

The ticket stays in its current queue. Every ticket is in exactly one queue, and this action doesn't change that.

## Notify the owner

The **Escalate to account owner** action notifies the owner for you. Use these steps to confirm the owner has what they need.

1. Stay on the ticket after you confirm the escalation. The owner receives two notifications: one in the app and one by email.
2. If the situation is time-sensitive, contact the owner directly as well, for example by chat or phone. Mention the ticket subject and priority so they can find it quickly.
3. Reply to the customer to say their issue has been passed to their account owner, and set the ticket status to **Waiting on customer** only if you need information from them. Otherwise leave it as it is, so your SLA timers keep running as your policy defines.
