# WhatsApp and Email: how PDFs are sent

## The Send menu

Everywhere a receipt, statement or debt reminder can be sent, there is one **Send ▾** button. It opens two choices: **WhatsApp** and **Email**.
(Free plan: the same menu, but it sends a *link* to the receipt instead of the PDF. Pro puts the PDF itself in.)

| Where you are | WhatsApp | Email |
|---|---|---|
| **Server has the WhatsApp Cloud API set up** (optional, below) | Asks "Send on WhatsApp?" then the **server delivers the PDF straight into the customer's WhatsApp**. No other app opens | Phone: share sheet with the PDF attached. Computer: PDF is saved, the mail app opens with recipient, subject and message already written |
| **A phone** (Android Chrome, iPhone Safari) | The phone's share sheet opens with the **PDF file already attached**. Tap **WhatsApp**, pick the contact, send | Same sheet. Tap your mail app (Gmail, Mail): the PDF is attached, the subject and message are filled in |
| **A computer** | The PDF is saved, then the customer's WhatsApp chat opens with the message written. Attach the saved PDF | The PDF is saved, then your mail app opens with everything written except the attachment |

Cancelling the share sheet does nothing, silently.

### What a web page can and cannot do (why there is a share sheet at all)

* A `wa.me` link can carry text but **can never carry a file**. That is a WhatsApp limitation, not something the app can work around.
* A website **cannot choose the app** inside a phone's share sheet, and cannot attach a file to a specific app. The only browser feature that moves a real file
  into WhatsApp or Mail is the **share sheet** (the Web Share API), where you tap the app once. That is what this app uses, with the PDF attached.
* The **only** way to get a PDF into a customer's WhatsApp with no sheet and no tapping is the **WhatsApp Business Cloud API**, where our server sends it.
  That is the optional "direct" mode below.
* An email cannot be pre-attached by a `mailto:` link either. Again the share sheet attaches the file. On a computer, the PDF is saved and you attach it.

## Direct delivery with the WhatsApp Business Cloud API (optional)

The server uploads the PDF to WhatsApp and sends it as a **document message** to the customer's number. The server builds the PDF **and** looks up the number itself.
The browser can only say "send receipt X", never choose a file or a number. So the endpoint cannot be used to message strangers or send arbitrary files.
It is also limited to 40 sends per shop per hour, 20 per user per 10 minutes, and 10 per customer per day, and every attempt is logged in the `outbound_messages` table.

### Trade-offs you must accept before switching it on

1. **The customer sees the message from *your* Oja Loom WhatsApp Business number, not from the shop owner.** If they reply, the reply goes to that number.
   Plan who watches it (or say "this number is for receipts only" in the template).
2. **Meta charges per message** (template/"utility" conversations) and sets limits. Check Meta's current rate card for Nigeria. You, the operator, pay.
3. **The number must be registered with the Cloud API.** Normally that means it can no longer be used in the regular WhatsApp or WhatsApp Business phone app. Meta has been adding a "coexistence" option, so check its current rules before choosing which number to use.
4. **Message templates need Meta's approval** before they can be sent to customers who have not messaged you in the last 24 hours (which is nearly always the case for receipts).
5. Until your business is verified, Meta limits how many people you can message. Start in test mode, which only lets you message a small list of recipients you add yourself in Meta's API Setup page.

It is off unless you configure it. With it off, everything above (share sheet, saved PDF + chat) still works. This was tested here only against a **mock** of Meta's API;
please send one real test message to yourself before relying on it.

### Setup (one-off)

1. **Meta Business account** → *business.facebook.com*. Create an app of type **Business**, add the **WhatsApp** product.
2. Add and verify your sending phone number. Note its **Phone number ID** (WhatsApp → API Setup).
3. **Permanent token:** Business Settings → Users → **System users** → add one (Admin) → assign it the app and the WhatsApp account → *Generate token* with
   the **`whatsapp_business_messaging`** and **`whatsapp_business_management`** permissions, never expiring. (The temporary 24-hour token on the API Setup page is for testing only.)
4. **Create the two templates** (WhatsApp Manager → Message templates). Category **Utility**, language **English**. Use these exactly: the server sends the values in this order.

   **`ojaloom_receipt`**: Header: **Document** (upload any sample PDF) · Body:
   ```
   Hello {{1}}, here is your receipt {{2}} from {{3}}. {{4}} Thank you for your business.
   ```
   Samples: `Chioma` · `OL-0001` · `Ada Fabrics` · `Total ₦15,000.00, balance due ₦10,000.00.`

   **`ojaloom_statement`**: Header: **Document** · Body:
   ```
   Hello {{1}}, here is your statement of account from {{2}}. {{3}} Thank you.
   ```
   Samples: `Chioma` · `Ada Fabrics` · `Balance owing: ₦10,000.00.`

   Wait for **Approved**. If you rename a template or use another language, set `OJALOOM_WA_TEMPLATE_RECEIPT`, `OJALOOM_WA_TEMPLATE_STATEMENT` or `OJALOOM_WA_TEMPLATE_LANG`.
5. **Give the server the settings**
   * In `deploy/gcp/config.sh` set `WA_PHONE_ID="<your phone number ID>"`, then run `./01-setup.sh`.
   * Run `./02-secrets.sh` and paste the token at the *WhatsApp Cloud API access token* prompt.
   * `./03-deploy.sh`.
6. **Check:** `https://api.example.com/api/boot` now contains `"whatsapp_direct":true`. In the app, **Send ▾ → WhatsApp** on a receipt whose customer has *your own* number, and confirm it arrives.

### Errors you may see (and what they mean)

| The app says | Cause |
|---|---|
| "WhatsApp could not deliver to that number. It may not be on WhatsApp." | Wrong number or the customer is not on WhatsApp |
| "That number is not allowed to receive messages…" | Test mode: add the recipient in Meta's API Setup page |
| "WhatsApp delivery is not available right now." | Token expired/revoked, template not approved or named differently, or Meta is down. The server log has the numeric error code and Meta's trace id (never the token or the phone number) |
| "This customer has no valid WhatsApp number on file." | Add or correct the customer's phone number |

On any failure the app offers to **share from the phone instead**, so a problem with direct delivery never blocks sending a receipt.
Delivery status (sent/delivered/read) is not tracked; the `outbound_messages` table records that Meta accepted the message.

## Customer support chat

The green button at the bottom-right of every screen (and "Chat with support" in the mobile *More* menu, and in Settings) opens
`https://wa.me/2347074235945` with a message that already names the shop. The number is the build setting `SUPPORT_WHATSAPP` (default `2347074235945`,
which is 07074235945 in international format) and `OJALOOM_SUPPORT_WHATSAPP` for the Terms page.
