# AG Grid Community 36.2.0 (vendored)

Served from this origin so the Content-Security-Policy can stay `script-src 'self'; style-src 'self'`.
Files are unmodified copies from the `ag-grid-community@36.2.0` npm package:

- `ag-grid-community.min.noStyle.js` (dist/): the grid without the runtime theme injection,
  which would need inline `<style>` elements
- `ag-grid.min.css`, `ag-theme-quartz-no-font.min.css` (styles/): the CSS-file ("legacy") theme
- `LICENSE.txt`: MIT, AG Grid Ltd

Used by the returns inbox (`/inbox`, `app/static/app.js`). To update: `npm pack ag-grid-community@<version>`
and copy the same four files.
