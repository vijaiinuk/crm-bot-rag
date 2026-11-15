---
doc_id: products-catalogue
title: Managing the product catalogue
modules: [products]
version: 1
---

## Add a product

Each product in the catalogue needs a SKU that no other product uses. Have the SKU ready before you start.

1. Go to **Products**.
2. Select **Add product**.
3. Enter a **Name** and a **SKU**. If the SKU already belongs to another product, the form shows an error and you must enter a different one.
4. Fill in the optional fields you need, such as **Category**, **Unit** and **Description**. For details on each field, see *Product fields* below.
5. Select **Save**. The product appears in the product list with the status **Active**.

A new product has no price until you add it to a price book. Go to **Products → Price books**, open a price book and enter one price for each currency that price book supports. An account can have up to 20 price books, and exactly one of them is the default.

To sell the product as part of a package, you can include it in a bundle. A bundle contains 2 to 50 products. Its price is either the sum of its products' prices or a fixed bundle price. You manage bundles under **Products → Bundles**.

## Archive a product

Archive a product when you stop selling it. Archiving doesn't delete the product or its history. An archived product can't be added to new quotes, but it stays on any existing quotes that already include it.

1. Go to **Products** and open the product you want to retire.
2. Select **Archive**.
3. Confirm when prompted. The status changes to **Archived**, and the product no longer appears when you choose products for new quotes.

## Product fields

Every product has the standard fields in the table below. Only **Name** and **SKU** are required.

| Field | Required | Description |
|---|---|---|
| **Name** | Yes | The product name as your team sees it in the catalogue and on quotes. |
| **SKU** | Yes | A unique identifier for the product. No two products can share a SKU. |
| **Category** | No | A label for grouping products, such as "Subscriptions" or "Services". Use it to filter the product list. |
| **Unit** | No | How you count the product, such as "seat", "licence" or "hour". |
| **Description** | No | A short text describing what the product is. |
| **Status** | Set by the system | Shows **Active** for products you can sell, or **Archived** for products you've retired. |
| **Price** | Set in price books | The price isn't stored on the product itself. Each price book holds one price per currency for the product. |
