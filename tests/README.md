# Regression tests

Install development-only dependencies with `npm install --prefix tests`, then run `npm test --prefix tests`. These dependencies are excluded from Cloudflare assets. Worker tests mock OpenAI, so passing them does not establish live provider acceptance. Frontend tests use jsdom and do not replace visual browser checks.
