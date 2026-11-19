# Rider-app UI references (where the `/rider` design comes from)

The images themselves are not stored in this repo (they belong to Zomato / the video creators).
Open the links to see them. Colours were sampled from the pixels of these images.

## Official Play Store listing
- Zomato Delivery Partner: https://play.google.com/store/apps/details?id=com.zomato.delivery
  - 7 of 8 images are marketing posters. Screenshot 8 shows the real app (Bazaar tab):
    - grey "Offline" pill toggle with knob, top-left;
    - round buttons top-right: orange emergency beacon (SOS), bell, profile photo;
    - bottom tabs: **Feed · Pocket · Gigs · Offers · Bazaar**;
    - white page, light-grey rounded cards, geometric rounded typeface.
- Blinkit Delivery Partner: https://play.google.com/store/apps/details?id=app.blinkit.onboarding
  - Earnings, Gigs, Offers, Vehicle, Payout and Insurance screens. Same family: white, "← Title" + Help,
    black pill tabs, black-header cards, black primary buttons ("Claim now").

## Public rider tutorial videos (thumbnails show the real order screens)
| Video | What it shows |
|---|---|
| https://www.youtube.com/watch?v=-i-1vMGCOzQ | **New order**: map with black round rider/restaurant markers + dotted line, "× Deny" black pill, "New order" green-outlined tag, "Estimated earnings ₹92.81", breakdown box (Trip pay / Return pay), "Pickup: 1.06 kms \| Drop: 10.3 kms", grey "Pick up" tag, restaurant + address, "4 mins away", green "Accept order" bar with black round arrow knob |
| https://www.youtube.com/watch?v=MP28-0eepiQ | Same New order layout |
| https://www.youtube.com/watch?v=HqzOiUVb7pg | "Collect 2 orders" variant, "Accept order" bar |
| https://www.youtube.com/watch?v=Np7RNOKTjcM | New order with "Rain surge" in the breakdown, "Pick up" tag |
| https://www.youtube.com/watch?v=P3kZWfXQRI4 | **Feed**: Offline toggle, SOS, "?", avatar; "View details"; black-header **Today's progress** (Earnings, Trips, Time on orders, Gigs/History with →); bronze partner-tier card; tabs **Feed · Pocket · Gigs · Bazaar · Updates** |
| https://www.youtube.com/watch?v=02njhxpgXHY | **Order list**: Pickup 1 / Pickup 2 / Drop 1 / Drop 2 timeline with green check dots, "Order: 4506610063", "Pickup: …", "Customer: …" |

## Sampled colours
| Element | Colour |
|---|---|
| Accept / action bar | #2CD86C (black text, black round knob) |
| Deny pill, "Today's progress" header, knob | #000000 |
| "Pick up" tag | #606060 |
| Earnings breakdown box | #F4F4F4 |
| Offline toggle | #A4A4A4 |
| Partner-tier card (we reuse its style for the DropSync card) | #A07864 |

## What we deliberately did NOT copy
- No Zomato / Blinkit logo or wordmark; the app is labelled a concept prototype.
- The typeface is Outfit (Google Fonts), a free look-alike, not Zomato's own font.
- No made-up money: estimated earnings are a flat ₹25 marked "demo" (the PDF's cited ₹20–30 per order, ref [12]).
- The partner-tier (bronze) card is replaced by a DropSync card, because we have no tier data.
- Pocket, Gigs, Bazaar and Updates tabs are present for realism but show "Prototype: only Feed and the order flow are built".
