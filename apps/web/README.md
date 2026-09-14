# ServiceFlow web

Next.js (App Router), React 19, TypeScript and Tailwind. See the
[repository README](../../README.md) for the whole stack.

```bash
npm ci
npm run dev          # http://localhost:3000, expects the API at NEXT_PUBLIC_API_URL
npx eslint src e2e   # lint
npx tsc --noEmit     # types
npm run build        # production build (standalone output, used by the Dockerfile)
```

The browser never holds the API token: sign-in stores it in an httpOnly cookie
and `/api/proxy/*` attaches it server-side.

End-to-end tests (`e2e/`) run against a running stack:

```bash
docker compose up --build -d     # from the repository root
../../scripts/e2e.sh
```
