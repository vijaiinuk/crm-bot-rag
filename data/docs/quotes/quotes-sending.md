---
doc_id: quotes-sending
title: Sending quotes
modules: [quotes]
version: 1
---

## Send a quote as a PDF

Quotes are sent by email as PDF attachments. Each quote is numbered automatically in the format Q-00001 and can have up to 200 line items.

1. Go to **Quotes → Quote builder** and open the quote you want to send. Check the line items, discounts and totals.
2. If any discount is above 20%, submit the quote for approval. The status changes to **Pending approval**. Approvers are set in **Quotes → Approvals → Approval rules**. Wait until the status changes to **Approved**.
3. Click **Send quote**. Confirm the recipient's email address, then edit the subject line and message if needed.
4. Click **Send quote** again to send the email. The quote PDF is attached automatically, and the status changes to **Sent**.

## Quote expiry

A quote is valid for 30 days by default. You can set the expiry to any value from 1 to 365 days. When the validity period ends and the customer has not responded, the status changes to **Expired**.

1. Go to **Quotes → Quote builder** and open the quote.
2. In the expiry setting, enter the number of days the quote stays valid, from 1 to 365. If you leave the default, the quote is valid for 30 days.
3. Save the quote, then send it. Check the quote record at any time to see its current status and whether it has expired.

## Quote statuses

Each quote has one status at a time. The status shows where the quote is in the approval and sending process.

| Status | Meaning |
|---|---|
| **Draft** | The quote is being built and has not been submitted or sent. |
| **Pending approval** | The quote includes a discount above 20% and is waiting for an approver to review it. |
| **Approved** | An approver has approved the quote. It is ready to send. |
| **Sent** | The quote has been emailed to the customer as a PDF attachment. |
| **Accepted** | The customer has accepted the quote. |
| **Declined** | The customer has declined the quote. |
| **Expired** | The validity period ended before the customer accepted or declined. |
