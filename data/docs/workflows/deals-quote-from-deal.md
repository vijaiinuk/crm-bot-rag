---
doc_id: deals-quote-from-deal
title: Creating a quote from a deal
modules: [deals, quotes, products]
version: 1
---

## Before you start

You need two things in place before you create a quote:

- **An open deal.** The **Create quote** button appears only on open deals, and only when your account has Quotes. Deals closed as won or lost leave the **Pipeline board**. To find one, use the **Closed** filter.
- **Products in a price book.** You add products from the deal's price book. This is the default price book unless the deal sets another. If the price book has no price in the deal's currency, you can't add that product. An archived product can't be added to new quotes.

The quote copies the deal's name, company and amount. Each quote is numbered automatically in the format Q-00001, and it can have up to 200 line items.

For details on price books, see *Price books*. For every option in the quote editor, see *Building a quote*.

## Create the quote from the deal

1. Go to **Deals**. The **Pipeline board** opens.
2. Find the deal you want to quote and open it. If you can't see it, check that it's still open. Closed deals appear only under the **Closed** filter.
3. Select **Create quote**. The **Quote builder** opens with a new quote in **Draft** status.
4. Check the details copied from the deal: the quote name, the company and the amount. Correct anything that's wrong in the **Quote builder**.
5. Set the expiry. A quote is valid for 30 days by default. Enter a number of days from 1 to 365 if you need a different period.
6. Select **Save**. The quote keeps its automatic number, for example Q-00001, and stays in **Draft** until you send it or submit it for approval.

## Add products from a price book

1. In the **Quote builder**, go to the line items section and select **Add products**. The list shows products from the deal's price book.
2. Search by product name or SKU. Every product has a unique SKU, so searching by SKU finds exactly one product. Select the checkbox next to each product you want, then select **Add**.
3. For each line item, set the quantity. If you want to give a discount, enter it on the line item. Any discount above 20% needs approval before you can send the quote.
4. Review the line items and the total, then select **Save**. If a discount is above 20%, submit the quote for approval. The status changes to **Pending approval**, and an approver reviews it. Approvers are set in **Quotes → Approvals → Approval rules**. When the approver approves the quote, the status changes to **Approved**.

## Send and track the quote

1. In the **Quote builder**, check that the status is **Draft** or **Approved**. A quote that is **Pending approval** can't be sent until it's approved.
2. Select **Send quote**.
3. Confirm the recipient's email address, edit the subject and message if you want, and select **Send**. The quote goes out by email as a PDF attachment, and its status changes to **Sent**.
4. Go to **Quotes** to follow the quote. The status changes to **Accepted** or **Declined** when the customer responds, or to **Expired** when the expiry passes without a response.
