---
doc_id: contacts-custom-fields
title: Custom contact fields
modules: [contacts]
version: 1
---

## Field types

Custom fields store information that the standard contact fields don't cover. Your account can have up to 100 custom contact fields. Each field uses one of these types, and you can't change the type after you save the field.

| Type | What it stores | Example |
|---|---|---|
| Text | Free text, up to 255 characters | Preferred contact hours |
| Number | Whole or decimal numbers | Number of employees |
| Date | A calendar date | Contract renewal date |
| Dropdown | One value chosen from a list of options you define | Lead source |
| Checkbox | A yes or no value | Attended onboarding webinar |
| URL | A web address | LinkedIn profile page |

## Add a custom field

1. Go to **Contacts → Field settings**.
2. Select **Add field**.
3. In **Field name**, enter the label that users will see on the contact record, for example "Renewal date". Use a name that is different from your other fields.
4. In **Field type**, choose one of the types from the table above. If you choose **Dropdown**, enter each option on its own line in the **Options** box.
5. Select **Save**.

The new field appears on every contact record. Existing contacts show it empty until someone fills it in.

If you reach the limit of 100 custom fields, you can't add another until you delete one you no longer use.

## Required fields

A required field must have a value before anyone can save a contact. Use this setting only for information your team always needs, because it applies to everyone who creates or edits contacts.

1. Go to **Contacts → Field settings** and select the custom field you want to change.
2. Turn on **Required**.
3. Select **Save**.

From then on, users must complete the field when they create a contact. When they edit an existing contact that has the field empty, they must complete it before saving. To make the field optional again, turn off **Required** and save.
