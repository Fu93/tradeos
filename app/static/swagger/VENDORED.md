# Vendored Swagger UI

Files in this folder are copied unchanged from the npm package `swagger-ui-dist@5.33.3` (Apache-2.0, see
`LICENSE.swagger-ui`, `NOTICE`, `swagger-ui-bundle.js.LICENSE.txt`), so `/api/docs` loads no third-party host and
the Content-Security-Policy (`script-src 'self'`, no inline script) stays strict. `swagger-init.js` is TradeOS's own
3-line starter.

    3861ec4cc8e7b9fa9f250280da9350436e418137788282c753b9a2ac5fb7bd2f  swagger-ui-bundle.js
    1ac324f7dcd27e4b9386b4bd6421271ec147e922a22c05ba24b11515e9aa6321  swagger-ui.css

To update: `npm pack swagger-ui-dist`, copy the same files, re-check `/api/docs` in a browser, update these hashes.
