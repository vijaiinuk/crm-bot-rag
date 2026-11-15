---
doc_id: quotes-builder
title: Building a quote
modules: [quotes]
version: 1
---

## Create a quote

1. Go to **Quotes → Quote builder**.
2. Select **New quote**. The CRM assigns the next number automatically in the format Q-00001, and the quote opens with the status **Draft**.
3. In the **Deal** field, choose the deal the quote is for. The customer and contact details fill in from the deal.
4. In the **Expiry** field, enter the number of days the quote stays valid. The default is 30 days. You can enter any value from 1 to 365.
5. Select **Save**. The quote stays in **Draft** until you send it or submit it for approval, so you can come back and keep editing.

A quote moves through these statuses: **Draft**, **Pending approval**, **Approved**, **Sent**, **Accepted**, **Declined** and **Expired**.

## Line items

A quote can have up to 200 line items. Add each product or service as its own line so the customer sees a clear breakdown.

1. Open the quote in **Quotes → Quote builder** and go to the **Line items** section.
2. Select **Add line item**, then enter a **Description**, a **Quantity** and a **Unit price**. The **Line total** is calculated for you.
3. Repeat step 2 for each item you want to include. To change the order, drag a line by its handle. To remove a line, select the delete icon at the end of the row.
4. Check the **Subtotal** at the bottom of the section, then select **Save**.

If you reach the 200-line limit, combine similar items into a single line, for example one line for a bundle of licences instead of one line per licence.

## Discounts

You can discount a single line item or the whole quote. Any discount above 20% needs approval before you can send the quote.

1. Open the quote in **Quotes → Quote builder**.
2. To discount one line, enter a percentage in the **Discount %** field on that row. To discount the whole quote, enter a percentage in the **Quote discount** field below the line items.
3. Check the **Total** to confirm the discounted amount, then select **Save**. If the discount is 20% or less, the quote stays in **Draft** and you can select **Send quote** when you are ready. The CRM sends it by email as a PDF attachment.
4. If the discount is above 20%, select **Submit for approval**. The status changes to **Pending approval**, and the people named as approvers are notified. When an approver approves the quote, the status changes to **Approved** and you can select **Send quote**.

Administrators set approvers in **Quotes → Approvals → Approval rules**. To check where a quote is in the process, open **Quotes → Approvals** and look at its status.
