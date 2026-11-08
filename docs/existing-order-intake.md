# Existing PayPal Sandbox capture intake

The MCP gateway supports a Sandbox order made by the agent, or a **new** Sandbox order made by the merchant before
the agent acts. A third path, available only on the private operator-gated persistent profile, accepts an **existing**
PayPal Sandbox capture. The merchant enters its capture ID and a buyer label. TradeOS reads that capture through the
connected merchant's PayPal credentials, requires `COMPLETED` and the configured demo sneaker amount/currency, and
then issues an order-specific return pass. The agent never receives a tool that takes a capture ID.

This verifies the payment under the connected PayPal Sandbox account, not the buyer's identity or an external store
record. The merchant attests that the capture belongs to the labelled buyer and demo sneakers. It is not a Shopify or
ERP integration, does not support arbitrary products, and is not enabled on the public shared demo.
Only the pass hash is stored on the audit chain; the raw pass appears once in the merchant's response. A merchant
order permits one request, with the first authenticated agent credential bound to that request when available. The
database refuses to attach the same capture to another case, even after archiving it. Once the pass expires, an
anonymous agent can no longer read with it; the authenticated agent that made the request can still read with its
verified credential. The dashboard retains the case and evidence.

Before the first request, the private operator can revoke the pass from the order page or with
`POST /merchant/orders/{case_id}/revoke-return-pass` using operator Basic authentication. Revocation is chained,
idempotent, and prevents both request intake and pass-based status reads. A pass already used for a request cannot be
revoked retroactively; the request remains in the audit trail. The request checks the pass again under the same case
lock as revocation, so a concurrent revoke cannot race past authorization.

For a production merchant, letting the **agent** submit an arbitrary PayPal capture ID would still let it probe or act
on someone else's purchase. The private merchant intake keeps that ability out of MCP.

Remaining contract for real store orders:

1. Connect an authenticated store order record to the PayPal capture and merchant-side buyer reference. The current
   path reads the PayPal capture but takes the product and buyer label from an operator assertion.
2. The merchant issues a short-lived, single-purpose return authorization for that buyer and order. An agent presents
   this authorization with the buyer's message. TradeOS binds it to one order and one authenticated agent credential;
   failure returns the same generic response for unknown and unauthorized orders.
3. `request_return` is idempotent for that authorization. It can create a case and ask for a decision, never approve or
   refund. The existing policy, Safety Gate, audit chain and PayPal refund guard apply unchanged. A person must approve
   agent-originated money actions even if merchant autonomy is enabled.
4. The merchant can revoke the authorization before intake. Expiry is enforced; duplicate captures and repeat
   requests are refused. Future integration must also reject mismatched buyer/order/capture, and a
   PayPal capture owned by another merchant all fail closed with zero refund calls. The audit trail records verified
   identifiers and decisions without storing a reusable raw authorization.

Acceptance evidence for a real store integration should cover a previously captured order with a verified store
buyer link, an exchange with zero refund calls, a revoked or replayed authorization, a guessed capture ID, and an
order that PayPal reports as belonging to another merchant. Only after those checks should the product claim that
buyer agents can return **existing external merchant orders**.
