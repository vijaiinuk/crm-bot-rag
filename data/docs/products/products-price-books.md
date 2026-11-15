---
doc_id: products-price-books
title: Price books
modules: [products]
version: 1
---

## Create a price book

An account can have up to 20 price books. Each price book holds one price per currency for every product it includes.

1. Go to **Products → Price books**.
2. Select **New price book**.
3. In **Name**, enter a name that tells your team when to use the price book, for example "Partner 2025". Add an optional **Description**.
4. Under **Currencies**, select each currency you sell in, then enter a price for each product. Products are identified by their SKU.
5. Select **Save**.

If the **New price book** button is unavailable, your account already has 20 price books. Delete one you no longer use before you create another.

## Currency prices

Each product in a price book has one price per currency. You can't enter two prices for the same product in the same currency within one price book. To offer a second price, create another price book.

| Column | What it shows | Notes |
|---|---|---|
| **SKU** | The product's unique SKU | Read-only. Edit the SKU on the product itself. |
| **Product** | The product name | Read-only. |
| **Currency** | One of the currencies enabled for the price book | Each product appears once for each currency. |
| **Price** | The unit price in that currency | Enter a number with up to two decimal places. |

To add a currency to an existing price book, open the price book from **Products → Price books**, select **Edit prices**, and add the currency. Enter a price for every product you want to sell in that currency, then select **Save**.

An archived product can't be added to new quotes, but it stays on existing ones. Its prices remain in the price book.

## Set the default price book

Exactly one price book is the default at any time. Your account uses it whenever a price book isn't chosen explicitly.

1. Go to **Products → Price books**.
2. Find the price book you want to use as the default, select the **⋯** menu at the end of its row, and then select **Make default**.
3. Select **Confirm**. The **Default** label moves to this price book, and the previous default becomes a regular price book.

If you also use bundles, see *Creating a bundle* for how bundle prices relate to product prices.
