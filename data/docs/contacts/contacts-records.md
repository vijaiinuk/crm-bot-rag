---
doc_id: contacts-records
title: Contacts and companies
modules: [contacts]
version: 1
---

## Create a contact

1. Go to **Contacts**.
2. Select **New contact**.
3. Enter the contact's first name, last name and email address. The email address is the field the CRM uses to match duplicates if you import contacts later, so enter it accurately.
4. Fill in any other fields you need, such as phone number, job title or your own custom fields. If your account has custom contact fields, they appear below the standard fields.
5. Select **Save**.

The contact opens on its own page. You are set as the contact's owner automatically.

If you have many people to add, you can bring them in from a CSV file instead. Go to **Contacts → Import contacts** and upload the file. A file can have up to 50,000 rows and 25 MB, and it must be encoded as UTF-8. Imports run in the background, and you receive a notification when one finishes.

## Link a contact to a company

1. Open the contact from **Contacts**, then select **Edit**.
2. In the **Company** field, start typing the company name and choose it from the list. If the company doesn't exist yet, go to **Contacts → Companies**, create it, and then return to the contact.
3. Select **Save**.

The company name now appears on the contact. To see everyone linked to a company, go to **Contacts → Companies** and open the company. Its page lists the contacts linked to it.

## Contact owner

Every contact has exactly one owner. The owner is the person on your team who is responsible for the relationship with that contact. A contact can't have several owners, and it can't be left without one.

When you create a contact yourself, you become its owner. The exception is an import: if the CSV file sets an owner for a row, the contact is assigned to that user instead. If the file doesn't set an owner, the user who runs the import owns the new contacts.

When you import contacts whose email addresses already exist in your account, the import matches them by email address. In the import settings, you choose how to handle each match:

- **Skip** leaves the existing contact unchanged. This is the default.
- **Update existing** overwrites the existing contact's fields with the values from the file.
- **Create new** adds a separate contact for the row.

To review a recent import, go to **Contacts → Import contacts → History**. The history keeps 30 days of imports.
