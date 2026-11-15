---
doc_id: quotes-approvals
title: Quote approvals
modules: [quotes]
version: 1
---

## Approval rules

Approval rules decide who reviews a quote before it can be sent. Any discount above 20% needs approval, and you choose the approvers in the rules.

1. Go to **Quotes → Approvals**.
2. Open the **Approval rules** tab.
3. Select the rule you want to change, or select **Add rule** to create a new one.
4. In the **Approvers** field, choose one or more people who can approve quotes that meet the rule.
5. Select **Save**.

After you save, the rule applies to quotes you submit from then on. Quotes already waiting for approval keep the approvers they were assigned when they were submitted.

## Approve or reject a quote

When a quote needs your approval, its status changes to **Pending approval**. The quote stays in that status until an approver acts on it. You can't send it until it is approved.

1. Go to **Quotes → Approvals** and open the quote you want to review. Check the line items, the discount and the total, and read any note from the quote's author.
2. Select **Approve** if the quote is acceptable, or **Reject** if it is not. If you reject a quote, add a comment that explains what needs to change.
3. Confirm your choice. An approved quote moves to **Approved**, and the author can then use **Send quote** to email it to the customer as a PDF attachment. A rejected quote goes back to the author, who can revise it and submit it again.

## Approval limits

Approval is triggered by the discount on a quote. Any discount above 20% needs approval. A discount of exactly 20% or less does not need approval, so the quote can go straight from **Draft** to being ready to send.

A quote is checked each time it is submitted. If you change the discount after a quote is approved, the quote may need approval again. Check the status in the quote list before you send it.

Keep these related limits in mind when you build and approve quotes:

- Each quote is numbered automatically in the format Q-00001, so you don't enter a quote number yourself.
- A quote can have up to 200 line items.
- A quote is valid for 30 days by default. You can set the expiry to any value from 1 to 365 days in **Quote builder**. If a quote passes its expiry date before the customer responds, its status changes to **Expired**.

Approvers only act on quotes that are in **Pending approval**. After a quote is **Approved** and sent, it moves through **Sent** and then ends as **Accepted**, **Declined** or **Expired**.

If you also use Deals, see the Deals documentation for how deals relate to the quotes built from them.
