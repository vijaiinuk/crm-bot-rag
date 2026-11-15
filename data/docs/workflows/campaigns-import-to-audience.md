---
doc_id: campaigns-import-to-audience
title: Importing contacts into a campaign audience
modules: [contacts, campaigns]
version: 1
---

## Before you start

You need a CSV file of contacts. Check these points before you upload it:

- The file is encoded as UTF-8, is 25 MB or smaller, and has no more than 50,000 rows.
- The file includes a consent column. Only rows where this column is **Yes** are added to the audience.
- Each row has an email address. The import uses it to detect duplicates of contacts you already have.
- An audience holds up to 100,000 contacts. If the audience is already close to that limit, the import may not fit.

If you want imported contacts to belong to someone other than you, add a column with the owner. Every contact has exactly one owner. Unless the import sets the owner, you own each contact the import creates.

For general import options, see *Importing contacts*.

## Import the CSV

1. Go to **Contacts → Import contacts**.
2. Upload your CSV file.
3. Match each column in your file to a contact field. Match the consent column too, and match the owner column if you have one. To import into a field that doesn't exist yet, create it first under **Field settings**.
4. Choose how to handle duplicates. Contacts are matched by email address. Select **Skip** (the default), **Update existing** or **Create new**.
5. Review the summary of the mapping and the duplicate setting.
6. Continue to the last step of the import, where you can add the contacts to an audience. Complete the next section before you start the import.

## Add the contacts to an audience

The last step of the import offers **Add to audience** because your account has Campaigns.

1. On the last step of the import, select **Add to audience**.
2. Choose the audience that should receive the contacts, or enter a name to create a new one.
3. Confirm that the consent column is the one you matched earlier. Only rows with **Yes** in that column are added.
4. Start the import.

The import runs in the background, so you can keep working. You receive a notification when it finishes. To review the result later, go to **Contacts → Import contacts → History**, which keeps 30 days of imports.

To see the audience, go to **Campaigns → Audiences**. An audience is built from contact filters and updates automatically. For details on filters, see *Building audiences*.

## Check consent

Consent decides who ends up in the audience, so check it before and after the import.

Before you import, open your CSV and look at the consent column. A row is added only when its value is **Yes**. Rows with any other value, or a blank value, are not added to the audience. If your file uses another word, such as "true" or "opted in", replace it with **Yes** for the people who have agreed, and save the file as UTF-8.

If your file has no consent column, the contacts can't be added to an audience. Add the column and import the file again.

After the import finishes, open the audience under **Campaigns → Audiences** and compare its size with the number of **Yes** rows in your file. A difference can come from rows that were skipped as duplicates or that did not have **Yes** in the consent column.

Consent at import doesn't override later changes:

- Every email includes an unsubscribe link automatically.
- Contacts who unsubscribe never receive campaign or triggered emails.
- If an email hard bounces, the contact is marked **Bounced** and excluded from future sends.
