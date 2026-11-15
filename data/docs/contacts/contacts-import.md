---
doc_id: contacts-import
title: Importing contacts
modules: [contacts]
version: 1
---

## CSV

Prepare your file first, then upload it. An import can have up to 50,000 rows and the file can be up to 25 MB. The file must be a CSV encoded as UTF-8.

1. Open your spreadsheet and make sure the first row contains column headings, such as `First name`, `Last name` and `Email`.
2. Check that the file has no more than 50,000 rows and is under 25 MB. If it is larger, split it into several files and import them one at a time.
3. Save or export the file as CSV with UTF-8 encoding.
4. In Contacts, go to **Contacts → Import contacts**.
5. Select the CSV file, or drag it into the upload area.
6. Select **Next** to continue to field mapping. Imports run in the background, so you can leave the page after you start one. You receive a notification when the import finishes.

To review recent imports, go to **Contacts → Import contacts → History**. History keeps 30 days of imports.

If you want to add people to a campaign audience instead, see *Importing contacts into a campaign audience*.

## Mapping fields

After you upload the file, match each column in the CSV to a contact field. Only mapped columns are imported.

1. For each column, open the field list next to the column heading and select the contact field it belongs to. Columns whose headings match a field name are matched for you; check them anyway.
2. To leave a column out, set it to **Don't import**.
3. If a column has no matching field, create a custom field first. Go to **Contacts → Field settings** and add a field of the right type: text, number, date, dropdown, checkbox or URL. Your account can have up to 100 custom contact fields. Then return to the import and map the column.
4. To set the owner of the imported contacts, map a column that contains the owner's name or email address to the **Owner** field. Every contact has exactly one owner. If you don't map an owner, each imported contact is owned by you, because you created it through the import.

## Duplicates

The import matches duplicates by email address. A row whose email address is already on a contact in your account counts as a duplicate. Choose how to treat these rows before you start.

1. On the duplicate handling step, review the options:
   - **Skip** leaves the existing contact unchanged and does not import the row. This is the default.
   - **Update existing** overwrites the mapped fields on the existing contact with values from the row.
   - **Create new** adds the row as a new contact, even though a contact with that email address exists.
2. Select the option you want. If you aren't sure, keep **Skip**, which never changes existing contacts.
3. Start the import. When the notification arrives, open **Contacts → Import contacts → History** to review the result for that import.
