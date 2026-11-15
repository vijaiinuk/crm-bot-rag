---
doc_id: contacts-ownership
title: Assigning contact owners
modules: [contacts]
version: 1
---

## Change the owner

Every contact has exactly one owner. A new contact is owned by the user who creates it, so you change the owner when a contact moves to a different person on your team.

1. Go to **Contacts** and open the contact you want to change.
2. In the contact's details, click the **Owner** field and select the new owner from the list of users.
3. Click **Save**. The new owner appears on the contact right away.

To change the owner of a company, go to **Contacts → Companies** and open the company record. The steps are the same.

## Bulk reassign

Use bulk reassignment when someone leaves the team or when you rebalance territories. You can reassign many contacts in one action instead of opening each record.

1. Go to **Contacts**. To work on a specific person's contacts, filter the list by **Owner**.
2. Select the check box next to each contact you want to move. To select every contact on the page, select the check box in the table header.
3. Click **Change owner** in the toolbar above the list.
4. Select the new owner from the list of users.
5. Click **Reassign** to confirm. Each selected contact now has the new owner, and the list refreshes to show the change.

If you filtered by the previous owner, the reassigned contacts disappear from the filtered list because they no longer match it.

## Owners on import

When you import contacts from a CSV file, the import can set the owner of each contact it creates. If the import doesn't set an owner, each new contact is owned by the user who runs the import.

Start an import from **Contacts → Import contacts**. A file can have up to 50,000 rows and 25 MB, and it must be encoded as UTF-8. Imports run in the background, and you receive a notification when yours finishes. To check the result later, go to **Contacts → Import contacts → History**, which keeps 30 days of imports.

Duplicates are matched by email address, and you choose how to handle them: **Skip**, **Update existing** or **Create new**. The default is **Skip**, which leaves existing contacts as they are. Before you rely on an import to change who owns contacts you already have, choose the duplicate handling carefully. If you need to move existing contacts to a new owner right away, use the bulk reassign steps above.

For the full import procedure, including how to prepare your file and map columns, see *Importing contacts*.
